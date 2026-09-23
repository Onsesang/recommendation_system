#!/usr/bin/env python3
"""Dependency-free backend for the material-span human audit UI."""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
STATIC_ROOT = APP_ROOT / "static"
DATA_ROOT = APP_ROOT / "data"
ITEMS_PATH = DATA_ROOT / "items.json"
ANNOTATIONS_PATH = DATA_ROOT / "annotations.json"
LIVE_CSV_PATH = DATA_ROOT / "human_semantic_audit_live.csv"
MISSING_SPANS_PATH = DATA_ROOT / "missing_spans.json"
MISSING_CSV_PATH = DATA_ROOT / "human_missing_spans_live.csv"
RECALL_CHECKS_CSV_PATH = DATA_ROOT / "human_review_recall_checks_live.csv"
SOURCE_CSV_PATH = (
    PROJECT_ROOT / "experiments/02_semantic_verification/human_semantic_audit.csv"
)
FALLBACK_IMAGE_ROOT = DATA_ROOT / "images"

ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
SPAN_PATTERN = re.compile(r"^[a-f0-9]{20}$")
REVIEW_PATTERN = SPAN_PATTERN
MISSING_SPAN_PATTERN = SPAN_PATTERN
ALLOWED_SCOPE = {
    "main_fabric",
    "lining",
    "component",
    "whole_garment",
    "outer_surface",
    "unknown",
}
ALLOWED_PROPERTY_STATUS = {
    "present",
    "absent",
    "uncertain",
    "comparative",
    "mixed",
}
ALLOWED_INTENSITY = {"none", "slight", "moderate", "strong", "unknown"}
ALLOWED_SENTIMENT = {"positive", "negative", "neutral", "mixed", "unknown"}
ALLOWED_EVIDENCE = {
    "direct_touch",
    "worn_experience",
    "visual_only",
    "product_behavior",
    "unspecified",
}
ALLOWED_OBSERVABILITY = {"low", "medium", "high", "unknown"}
ALLOWED_ACTION = {"good", "bad", "edit"}
MAX_BODY_BYTES = 64 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--image-root", type=Path, default=None)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Optional versioned audit data directory containing items.json and source CSV",
    )
    parser.add_argument(
        "--quality-root",
        type=Path,
        default=None,
        help="Optional directory for this audit's quality metrics and status report",
    )
    return parser.parse_args()


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


class AuditStore:
    def __init__(
        self,
        image_root_override: Path | None = None,
        *,
        items_path: Path = ITEMS_PATH,
        annotations_path: Path = ANNOTATIONS_PATH,
        missing_spans_path: Path = MISSING_SPANS_PATH,
        source_csv_path: Path = SOURCE_CSV_PATH,
        live_csv_path: Path = LIVE_CSV_PATH,
        missing_csv_path: Path = MISSING_CSV_PATH,
        recall_checks_csv_path: Path = RECALL_CHECKS_CSV_PATH,
        quality_root: Path | None = None,
        update_quality: bool = True,
    ) -> None:
        manifest = json.loads(items_path.read_text(encoding="utf-8"))
        self.items = manifest["items"]
        self.dataset_version = manifest.get("dataset_version", "semantic_audit_v1")
        self.item_by_id = {item["span_id"]: item for item in self.items}
        self.items_by_review: dict[str, list[dict]] = {}
        for item in self.items:
            self.items_by_review.setdefault(item["review_id"], []).append(item)
        self.image_root = image_root_override or Path(manifest["image_root"])
        self.annotations_path = annotations_path
        self.missing_spans_path = missing_spans_path
        self.source_csv_path = source_csv_path
        self.live_csv_path = live_csv_path
        self.missing_csv_path = missing_csv_path
        self.recall_checks_csv_path = recall_checks_csv_path
        self.quality_root = quality_root
        self.update_quality = update_quality
        self.lock = threading.RLock()
        if self.annotations_path.exists():
            self.document = json.loads(self.annotations_path.read_text(encoding="utf-8"))
        else:
            self.document = {
                "schema_version": 1,
                "revision": 0,
                "updated_at": None,
                "annotations": {},
            }
            atomic_json_write(self.annotations_path, self.document)
        if self.missing_spans_path.exists():
            self.recall_document = json.loads(
                self.missing_spans_path.read_text(encoding="utf-8")
            )
        else:
            self.recall_document = {
                "schema_version": 1,
                "revision": 0,
                "updated_at": None,
                "missing_spans": {},
                "review_checks": {},
            }
            atomic_json_write(self.missing_spans_path, self.recall_document)
        self.recall_document.setdefault("missing_spans", {})
        self.recall_document.setdefault("review_checks", {})
        self.export_csv()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "items": self.items,
                "dataset_version": self.dataset_version,
                "annotations": self.document["annotations"],
                "missing_spans": self.recall_document["missing_spans"],
                "review_checks": self.recall_document["review_checks"],
                "revision": self.document["revision"],
                "recall_revision": self.recall_document["revision"],
                "export_url": "/api/export",
                "missing_export_url": "/api/export-missing",
                "recall_checks_export_url": "/api/export-recall-checks",
            }

    def validate(self, span_id: str, payload: dict) -> dict:
        if span_id not in self.item_by_id:
            raise ValueError("Unknown span_id")
        action = payload.get("action")
        if action not in ALLOWED_ACTION:
            raise ValueError("action must be good, bad, or edit")
        annotator_id = str(payload.get("annotator_id", "")).strip()
        if not annotator_id or len(annotator_id) > 80:
            raise ValueError("annotator_id is required and must be at most 80 characters")
        accepted = payload.get("human_accepted")
        if not isinstance(accepted, bool):
            raise ValueError("human_accepted must be a boolean")

        item = self.item_by_id[span_id]
        defaults = item["qwen"]
        claim = str(payload.get("human_claim", "")).strip()
        scope = str(payload.get("human_scope", "")).strip()
        property_status = str(payload.get("human_property_status", "")).strip()
        visual_observability = str(
            payload.get("human_visual_observability", "")
        ).strip()
        comment = str(payload.get("comment", "")).strip()
        if accepted:
            claim = claim or defaults["claim"]
            scope = scope or defaults["scope"]
            property_status = property_status or defaults["property_status"]
            visual_observability = (
                visual_observability or defaults["visual_observability"]
            )
            if not claim:
                raise ValueError("human_claim is required for accepted spans")
            if scope not in ALLOWED_SCOPE:
                raise ValueError("Invalid human_scope")
            if property_status not in ALLOWED_PROPERTY_STATUS:
                raise ValueError("Invalid human_property_status")
            if visual_observability not in ALLOWED_OBSERVABILITY:
                raise ValueError("Invalid human_visual_observability")
        if any(len(value) > 5000 for value in (claim, comment)):
            raise ValueError("claim or comment is too long")

        return {
            "span_id": span_id,
            "action": action,
            "human_accepted": accepted,
            "human_claim": claim if accepted else "",
            "human_scope": scope if accepted else "",
            "human_property_status": property_status if accepted else "",
            "human_visual_observability": visual_observability if accepted else "",
            "annotator_id": annotator_id,
            "comment": comment,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self, span_id: str, payload: dict) -> dict:
        annotation = self.validate(span_id, payload)
        with self.lock:
            self.document["annotations"][span_id] = annotation
            self.document["revision"] += 1
            self.document["updated_at"] = annotation["updated_at"]
            atomic_json_write(self.annotations_path, self.document)
            self.export_csv()
            return {
                "annotation": annotation,
                "revision": self.document["revision"],
            }

    def delete(self, span_id: str) -> dict:
        if span_id not in self.item_by_id:
            raise ValueError("Unknown span_id")
        with self.lock:
            removed = self.document["annotations"].pop(span_id, None)
            if removed is not None:
                self.document["revision"] += 1
                self.document["updated_at"] = datetime.now(timezone.utc).isoformat()
                atomic_json_write(self.annotations_path, self.document)
                self.export_csv()
            return {
                "deleted": removed is not None,
                "revision": self.document["revision"],
            }

    def export_csv(self) -> None:
        with self.source_csv_path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            fieldnames = reader.fieldnames or []
            source_rows = list(reader)
        self.live_csv_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.live_csv_path.name}.",
            suffix=".tmp",
            dir=self.live_csv_path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=fieldnames)
                writer.writeheader()
                for row in source_rows:
                    annotation = self.document["annotations"].get(row["span_id"])
                    if annotation:
                        row.update(
                            {
                                "human_accepted": str(annotation["human_accepted"]),
                                "human_claim": annotation["human_claim"],
                                "human_scope": annotation["human_scope"],
                                "human_property_status": annotation[
                                    "human_property_status"
                                ],
                                "human_visual_observability": annotation[
                                    "human_visual_observability"
                                ],
                                "annotator_id": annotation["annotator_id"],
                                "comment": annotation["comment"],
                            }
                        )
                    writer.writerow(row)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_name, self.live_csv_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        self.export_recall_csvs()
        if not self.update_quality:
            return
        try:
            from material_span.human_audit import analyze_and_write

            quality_kwargs = (
                {"result_dir": self.quality_root} if self.quality_root else {}
            )
            analyze_and_write(
                self.live_csv_path,
                self.missing_csv_path,
                self.recall_checks_csv_path,
                **quality_kwargs,
            )
        except Exception as error:
            print(f"Quality report update failed: {error}", flush=True)

    def _validate_missing_payload(self, item: dict, payload: dict) -> dict:
        annotator_id = str(payload.get("annotator_id", "")).strip()
        if not annotator_id or len(annotator_id) > 80:
            raise ValueError("annotator_id is required and must be at most 80 characters")
        quote = str(payload.get("quote", "")).strip()
        claim = str(payload.get("claim", "")).strip()
        comment = str(payload.get("comment", "")).strip()
        if not quote or quote not in item["review"]:
            raise ValueError("quote must be an exact, non-empty substring of the full review")
        if not claim:
            raise ValueError("claim is required")
        if len(quote) > 2000 or len(claim) > 5000 or len(comment) > 5000:
            raise ValueError("quote, claim, or comment is too long")
        fields = {
            "scope": (ALLOWED_SCOPE, "scope"),
            "property_status": (ALLOWED_PROPERTY_STATUS, "property_status"),
            "intensity": (ALLOWED_INTENSITY, "intensity"),
            "sentiment": (ALLOWED_SENTIMENT, "sentiment"),
            "evidence_basis": (ALLOWED_EVIDENCE, "evidence_basis"),
            "visual_observability": (ALLOWED_OBSERVABILITY, "visual_observability"),
        }
        validated = {}
        for name, (allowed, label) in fields.items():
            value = str(payload.get(name, "")).strip()
            if value not in allowed:
                raise ValueError(f"Invalid {label}")
            validated[name] = value
        return {
            "quote": quote,
            "claim": claim,
            **validated,
            "annotator_id": annotator_id,
            "comment": comment,
        }

    def save_missing(self, payload: dict, missing_span_id: str | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            existing = None
            if missing_span_id is not None:
                existing = self.recall_document["missing_spans"].get(missing_span_id)
                if existing is None:
                    raise ValueError("Unknown missing_span_id")
                source_span_id = existing["source_span_id"]
            else:
                source_span_id = str(payload.get("source_span_id", "")).strip()
            item = self.item_by_id.get(source_span_id)
            if item is None:
                raise ValueError("Unknown source_span_id")
            values = self._validate_missing_payload(item, payload)
            review_items = self.items_by_review[item["review_id"]]
            if any(candidate["quote"] == values["quote"] for candidate in review_items):
                raise ValueError("This quote was already extracted; edit its existing annotation")
            duplicate = next(
                (
                    record
                    for key, record in self.recall_document["missing_spans"].items()
                    if key != missing_span_id
                    and record["review_id"] == item["review_id"]
                    and record["quote"] == values["quote"]
                ),
                None,
            )
            if duplicate:
                raise ValueError("This exact missing span is already registered for the review")
            if missing_span_id is None:
                missing_span_id = secrets.token_hex(10)
                while missing_span_id in self.recall_document["missing_spans"]:
                    missing_span_id = secrets.token_hex(10)
            record = {
                "missing_span_id": missing_span_id,
                "source_span_id": source_span_id,
                "review_id": item["review_id"],
                "asin": item["asin"],
                **values,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
            self.recall_document["missing_spans"][missing_span_id] = record
            self._commit_recall_document(now)
            return {"missing_span": record, "revision": self.recall_document["revision"]}

    def delete_missing(self, missing_span_id: str) -> dict:
        with self.lock:
            removed = self.recall_document["missing_spans"].pop(
                missing_span_id, None
            )
            if removed is not None:
                self._commit_recall_document(datetime.now(timezone.utc).isoformat())
            return {
                "deleted": removed is not None,
                "revision": self.recall_document["revision"],
            }

    def save_review_check(self, review_id: str, payload: dict) -> dict:
        if review_id not in self.items_by_review:
            raise ValueError("Unknown review_id")
        annotator_id = str(payload.get("annotator_id", "")).strip()
        if not annotator_id or len(annotator_id) > 80:
            raise ValueError("annotator_id is required and must be at most 80 characters")
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            record = {
                "review_id": review_id,
                "checked": True,
                "annotator_id": annotator_id,
                "updated_at": now,
            }
            self.recall_document["review_checks"][review_id] = record
            self._commit_recall_document(now)
            return {"review_check": record, "revision": self.recall_document["revision"]}

    def delete_review_check(self, review_id: str) -> dict:
        if review_id not in self.items_by_review:
            raise ValueError("Unknown review_id")
        with self.lock:
            removed = self.recall_document["review_checks"].pop(review_id, None)
            if removed is not None:
                self._commit_recall_document(datetime.now(timezone.utc).isoformat())
            return {
                "deleted": removed is not None,
                "revision": self.recall_document["revision"],
            }

    def _commit_recall_document(self, updated_at: str) -> None:
        self.recall_document["revision"] += 1
        self.recall_document["updated_at"] = updated_at
        atomic_json_write(self.missing_spans_path, self.recall_document)
        self.export_csv()

    def export_recall_csvs(self) -> None:
        missing_fields = [
            "missing_span_id",
            "source_span_id",
            "review_id",
            "asin",
            "quote",
            "claim",
            "scope",
            "property_status",
            "intensity",
            "sentiment",
            "evidence_basis",
            "visual_observability",
            "annotator_id",
            "comment",
            "created_at",
            "updated_at",
        ]
        self._write_csv(
            self.missing_csv_path,
            missing_fields,
            sorted(
                self.recall_document["missing_spans"].values(),
                key=lambda row: (row["review_id"], row["created_at"]),
            ),
        )
        check_fields = ["review_id", "checked", "annotator_id", "updated_at"]
        self._write_csv(
            self.recall_checks_csv_path,
            check_fields,
            sorted(
                self.recall_document["review_checks"].values(),
                key=lambda row: row["review_id"],
            ),
        )

    @staticmethod
    def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def image_path(self, asin: str) -> Path | None:
        if not ASIN_PATTERN.fullmatch(asin):
            return None
        candidates = [self.image_root / f"{asin}.jpg"]
        candidates.extend(FALLBACK_IMAGE_ROOT.glob(f"{asin}.*"))
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None


class AuditHandler(BaseHTTPRequestHandler):
    server_version = "MaterialAudit/1.0"

    @property
    def store(self) -> AuditStore:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, format_string: str, *args: object) -> None:
        print(
            f"{self.address_string()} - [{self.log_date_time_string()}] "
            + format_string % args,
            flush=True,
        )

    def send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_file(
        self,
        path: Path,
        content_type: str | None = None,
        download_name: str | None = None,
        cache_control: str | None = None,
    ) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("X-Content-Type-Options", "nosniff")
        if download_name:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{download_name}"'
            )
        else:
            self.send_header("Cache-Control", cache_control or "public, max-age=3600")
        self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid Content-Length") from error
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Invalid request body size")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise ValueError("Invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route == "/":
            self.send_file(
                STATIC_ROOT / "index.html",
                "text/html; charset=utf-8",
                cache_control="no-cache",
            )
        elif route == "/static/app.css":
            self.send_file(
                STATIC_ROOT / "app.css",
                "text/css; charset=utf-8",
                cache_control="no-cache",
            )
        elif route == "/static/app.js":
            self.send_file(
                STATIC_ROOT / "app.js",
                "application/javascript; charset=utf-8",
                cache_control="no-cache",
            )
        elif route == "/api/items":
            self.send_json(self.store.snapshot())
        elif route == "/api/health":
            self.send_json(
                {
                    "status": "ok",
                    "items": len(self.store.items),
                    "reviewed": len(self.store.document["annotations"]),
                }
            )
        elif route == "/api/quality":
            quality_path = (
                self.store.quality_root / "metrics.json"
                if self.store.quality_root
                else PROJECT_ROOT
                / "experiments/03_human_semantic_audit/results/metrics.json"
            )
            if not quality_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self.send_json(json.loads(quality_path.read_text(encoding="utf-8")))
        elif route == "/api/export":
            self.send_file(
                self.store.live_csv_path,
                "text/csv; charset=utf-8",
                "human_semantic_audit_live.csv",
            )
        elif route == "/api/export-missing":
            self.send_file(
                self.store.missing_csv_path,
                "text/csv; charset=utf-8",
                "human_missing_spans_live.csv",
            )
        elif route == "/api/export-recall-checks":
            self.send_file(
                self.store.recall_checks_csv_path,
                "text/csv; charset=utf-8",
                "human_review_recall_checks_live.csv",
            )
        elif route.startswith("/api/image/"):
            asin = route.removeprefix("/api/image/")
            image_path = self.store.image_path(asin)
            if image_path is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self.send_file(image_path)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route == "/api/missing-spans":
            try:
                response = self.store.save_missing(self.read_json())
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(response, HTTPStatus.CREATED)
            return
        if route.startswith("/api/review-checks/"):
            review_id = route.removeprefix("/api/review-checks/")
            if not REVIEW_PATTERN.fullmatch(review_id):
                self.send_json({"error": "Invalid review_id"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                response = self.store.save_review_check(review_id, self.read_json())
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(response)
            return
        if route.startswith("/api/annotations/"):
            span_id = route.removeprefix("/api/annotations/")
            if not SPAN_PATTERN.fullmatch(span_id):
                self.send_json({"error": "Invalid span_id"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                response = self.store.save(span_id, self.read_json())
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(response)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if not route.startswith("/api/missing-spans/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        missing_span_id = route.removeprefix("/api/missing-spans/")
        if not MISSING_SPAN_PATTERN.fullmatch(missing_span_id):
            self.send_json({"error": "Invalid missing_span_id"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            response = self.store.save_missing(
                self.read_json(), missing_span_id=missing_span_id
            )
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(response)

    def do_DELETE(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route.startswith("/api/missing-spans/"):
            missing_span_id = route.removeprefix("/api/missing-spans/")
            if not MISSING_SPAN_PATTERN.fullmatch(missing_span_id):
                self.send_json(
                    {"error": "Invalid missing_span_id"}, HTTPStatus.BAD_REQUEST
                )
                return
            self.send_json(self.store.delete_missing(missing_span_id))
            return
        if route.startswith("/api/review-checks/"):
            review_id = route.removeprefix("/api/review-checks/")
            if not REVIEW_PATTERN.fullmatch(review_id):
                self.send_json({"error": "Invalid review_id"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                response = self.store.delete_review_check(review_id)
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(response)
            return
        if route.startswith("/api/annotations/"):
            span_id = route.removeprefix("/api/annotations/")
            if not SPAN_PATTERN.fullmatch(span_id):
                self.send_json({"error": "Invalid span_id"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                response = self.store.delete(span_id)
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(response)
            return
        self.send_error(HTTPStatus.NOT_FOUND)


class AuditServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: AuditStore) -> None:
        self.store = store
        super().__init__(address, AuditHandler)


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve() if args.data_root else DATA_ROOT
    items_path = data_root / "items.json"
    if not items_path.exists():
        raise SystemExit(
            f"Missing {items_path}. Run the matching audit manifest builder first."
        )
    source_csv_path = (
        data_root / "human_semantic_audit.csv"
        if args.data_root
        else SOURCE_CSV_PATH
    )
    store = AuditStore(
        args.image_root,
        items_path=items_path,
        annotations_path=data_root / "annotations.json",
        missing_spans_path=data_root / "missing_spans.json",
        source_csv_path=source_csv_path,
        live_csv_path=data_root / "human_semantic_audit_live.csv",
        missing_csv_path=data_root / "human_missing_spans_live.csv",
        recall_checks_csv_path=data_root / "human_review_recall_checks_live.csv",
        quality_root=args.quality_root,
    )
    server = AuditServer((args.host, args.port), store)
    print(
        f"Material audit app serving {len(store.items)} items at "
        f"http://{args.host}:{args.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
