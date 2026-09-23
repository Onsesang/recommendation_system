from __future__ import annotations

import json
import os
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .common import (
    ROOT,
    append_jsonl,
    load_config,
    read_jsonl,
    save_json,
    sha256_file,
    sha256_text,
    write_jsonl,
)
from .extract import _local_model_path, parse_extraction, render_prompt
from .extract_recall import LENSES, _merge_outputs
from .verify import (
    apply_semantic_guardrails,
    parse_verification,
    render_verification_prompt,
)


VLLM_ROOT = ROOT / "data" / "vllm"
MODEL_ENV = "material_vllm312"
REUSABLE_EXTRACTION_STATUSES = {"success", "partial_invalid_quote"}


class ProgressNotifier:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        state = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        self.notified = {int(value) for value in state.get("notified", [])}
        self.webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    def _send(self, message: str) -> None:
        if not self.webhook_url:
            raise RuntimeError("DISCORD_WEBHOOK_URL is required")
        payload = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    self.webhook_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "material-span-grounding/1.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=20) as response:
                    if response.status not in {200, 204}:
                        raise RuntimeError(f"Discord returned HTTP {response.status}")
                return
            except Exception as exc:  # network failures are retried and then fatal
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"Discord notification failed: {last_error}")

    def update(self, percent: float, detail: str) -> None:
        capped = max(0.0, min(100.0, percent))
        for threshold in range(10, 101, 10):
            if threshold > capped or threshold in self.notified:
                continue
            self._send(
                "\n".join(
                    [
                        f"✅ material_span_grounding vLLM 재실행 {threshold}% 완료",
                        f"현재 단계: {detail}",
                        "백엔드: vLLM 0.27.1 / Qwen3-VL-8B-Instruct / BNB 4-bit",
                        "기존 Transformers 산출물은 보존 중입니다.",
                    ]
                )
            )
            self.notified.add(threshold)
            save_json(
                self.state_path,
                {
                    "notified": sorted(self.notified),
                    "latest_percent": threshold,
                    "latest_detail": detail,
                    "updated_at": datetime.now().astimezone().isoformat(),
                },
            )

    def failure(self, detail: str) -> None:
        try:
            self._send(f"❌ material_span_grounding vLLM 재실행 중단\n{detail}")
        except Exception:
            pass


class VLLMRunner:
    def __init__(self, max_model_len: int = 4096, chunk_size: int = 64) -> None:
        from transformers import AutoProcessor
        from vllm import LLM

        cfg = load_config()
        self.model_id = cfg["model_id"]
        self.model_path = _local_model_path(self.model_id)
        self.chunk_size = chunk_size
        self.processor = AutoProcessor.from_pretrained(
            self.model_path, local_files_only=True
        )
        self.llm = LLM(
            model=self.model_path,
            dtype="bfloat16",
            quantization="bitsandbytes",
            load_format="bitsandbytes",
            max_model_len=max_model_len,
            max_num_seqs=32,
            gpu_memory_utilization=0.90,
            enforce_eager=True,
            seed=42,
        )

    def render(self, prompt: str) -> str:
        message = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        return self.processor.apply_chat_template(
            message, tokenize=False, add_generation_prompt=True
        )

    def generate(self, prompts: list[str], max_tokens: int) -> tuple[list[str], float]:
        from vllm import SamplingParams

        started = time.time()
        outputs = self.llm.generate(
            [self.render(prompt) for prompt in prompts],
            SamplingParams(temperature=0.0, max_tokens=max_tokens, seed=42),
            use_tqdm=False,
        )
        elapsed = time.time() - started
        return [row.outputs[0].text.strip() for row in outputs], elapsed


def _prepare_verification(source_path: Path, root: Path) -> list[dict[str, Any]]:
    source_rows = read_jsonl(source_path)
    rows = []
    for review in source_rows:
        for evidence in review["evidence"]:
            quote = evidence["quote"]
            row = {
                "span_id": sha256_text(f"{review['review_id']}\x1f{quote}")[:20],
                "review_id": review["review_id"],
                "asin": review["asin"],
                "user_id": review["user_id"],
                "quote": quote,
                "review_text": review["text"],
            }
            if "sources" in evidence:
                row["extraction_sources"] = evidence["sources"]
            rows.append(row)
    rows.sort(key=lambda row: (row["review_id"], row["span_id"]))
    if len({row["span_id"] for row in rows}) != len(rows):
        raise ValueError("span_id collision or duplicate span")
    output_path = root / "semantic_verification_input.jsonl"
    write_jsonl(output_path, rows)
    save_json(
        root / "verification_input_manifest.json",
        {
            "input_spans": len(rows),
            "source_reviews": len(source_rows),
            "source_with_evidence": sum(bool(row["evidence"]) for row in source_rows),
            "source_path": str(source_path),
            "source_sha256": sha256_file(source_path),
            "output_path": str(output_path),
            "output_sha256": sha256_file(output_path),
            "protected_test_used": False,
            "backend": "vllm",
        },
    )
    return rows


def run_v1_extraction(
    runner: VLLMRunner,
    input_path: Path,
    root: Path,
    progress: Callable[[int, int], None],
    max_attempts: int = 2,
) -> list[dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    reviews = read_jsonl(input_path)
    output_path = root / "span_extractions.jsonl"
    raw_path = root / "raw_generations.jsonl"
    existing = {
        row["review_id"]: row
        for row in read_jsonl(output_path)
        if row.get("status") in REUSABLE_EXTRACTION_STATUSES
    }
    pending = [row for row in reviews if row["review_id"] not in existing]
    template_path = ROOT / "prompts" / "span_extraction_v1.txt"
    template = template_path.read_text(encoding="utf-8")
    started = time.time()
    progress(len(existing), len(reviews))
    for start in range(0, len(pending), runner.chunk_size):
        original = pending[start : start + runner.chunk_size]
        unresolved = list(original)
        resolved: dict[str, dict[str, Any]] = {}
        for attempt in range(1, max_attempts + 1):
            prompts = []
            for row in unresolved:
                prompt = render_prompt(template, row["review_id"], row["text"])
                if attempt > 1:
                    prompt += (
                        "\nYour previous response failed strict validation. Return the required "
                        "JSON object only. Every quote must be copied exactly from REVIEW."
                    )
                prompts.append(prompt)
            decoded, seconds = runner.generate(prompts, 240)
            retry = []
            raw_rows = []
            for row, raw in zip(unresolved, decoded):
                parsed = parse_extraction(raw, row["review_id"], row["text"])
                raw_rows.append(
                    {
                        "review_id": row["review_id"],
                        "attempt": attempt,
                        "raw_output": raw,
                        "validation_status": parsed["status"],
                        "latency_share_seconds": seconds / max(len(unresolved), 1),
                        "backend": "vllm",
                    }
                )
                if (
                    parsed["status"] in {"parse_failure", "schema_failure"}
                    and attempt < max_attempts
                ):
                    retry.append(row)
                    continue
                resolved[row["review_id"]] = {
                    "review_id": row["review_id"],
                    "asin": row["asin"],
                    "user_id": row["user_id"],
                    "text": row["text"],
                    **parsed,
                    "attempts": attempt,
                    "backend": "vllm",
                }
            append_jsonl(raw_path, raw_rows)
            unresolved = retry
            if not unresolved:
                break
        batch_rows = [resolved[row["review_id"]] for row in original]
        append_jsonl(output_path, batch_rows)
        existing.update({row["review_id"]: row for row in batch_rows})
        progress(len(existing), len(reviews))
    final_rows = [existing[row["review_id"]] for row in reviews]
    write_jsonl(output_path, final_rows)
    save_json(
        root / "extraction_run.json",
        {
            "status": "complete",
            "backend": "vllm",
            "vllm_version": "0.27.1",
            "environment": MODEL_ENV,
            "model": runner.model_id,
            "model_path": runner.model_path,
            "prompt_version": load_config()["prompt_version"],
            "prompt_sha256": sha256_file(template_path),
            "input": str(input_path),
            "input_sha256": sha256_file(input_path),
            "input_reviews": len(reviews),
            "elapsed_seconds_this_process": time.time() - started,
            "max_attempts": max_attempts,
            "output": str(output_path),
            "output_sha256": sha256_file(output_path),
        },
    )
    return final_rows


def run_recall_extraction(
    runner: VLLMRunner,
    input_path: Path,
    root: Path,
    v1_rows: list[dict[str, Any]],
    progress: Callable[[int, int], None],
    max_attempts: int = 2,
) -> list[dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    reviews = read_jsonl(input_path)
    lens_path = root / "lens_extractions.jsonl"
    raw_path = root / "raw_generations.jsonl"
    output_path = root / "span_extractions.jsonl"
    existing = {
        (row["review_id"], row["lens"]): row
        for row in read_jsonl(lens_path)
        if row.get("status") in REUSABLE_EXTRACTION_STATUSES
    }
    tasks = [
        (review, lens)
        for review in reviews
        for lens in LENSES
        if (review["review_id"], lens) not in existing
    ]
    templates = {lens: path.read_text(encoding="utf-8") for lens, path in LENSES.items()}
    total = len(reviews) * len(LENSES)
    started = time.time()
    progress(len(existing), total)
    for start in range(0, len(tasks), runner.chunk_size):
        original = tasks[start : start + runner.chunk_size]
        unresolved = list(original)
        resolved: dict[tuple[str, str], dict[str, Any]] = {}
        best_partial: dict[tuple[str, str], dict[str, Any]] = {}
        for attempt in range(1, max_attempts + 1):
            prompts = []
            for review, lens in unresolved:
                prompt = render_prompt(templates[lens], review["review_id"], review["text"])
                if attempt > 1:
                    prompt += (
                        "\nThe previous response failed exact-quote or JSON validation. "
                        "Rescan the full review and return valid JSON only. Copy every quote "
                        "exactly from REVIEW."
                    )
                prompts.append(prompt)
            decoded, seconds = runner.generate(prompts, 480)
            retry = []
            raw_rows = []
            for (review, lens), raw in zip(unresolved, decoded):
                key = (review["review_id"], lens)
                parsed = parse_extraction(
                    raw, review["review_id"], review["text"], max_items=20
                )
                raw_rows.append(
                    {
                        "review_id": review["review_id"],
                        "lens": lens,
                        "attempt": attempt,
                        "raw_output": raw,
                        "validation_status": parsed["status"],
                        "latency_share_seconds": seconds / max(len(unresolved), 1),
                        "backend": "vllm",
                    }
                )
                candidate = {
                    "review_id": review["review_id"],
                    "asin": review["asin"],
                    "user_id": review["user_id"],
                    "lens": lens,
                    **parsed,
                    "attempts": attempt,
                    "backend": "vllm",
                }
                if parsed["status"] == "partial_invalid_quote" and parsed["evidence"]:
                    previous = best_partial.get(key)
                    if previous is None or len(candidate["evidence"]) > len(previous["evidence"]):
                        best_partial[key] = candidate
                if parsed["status"] != "success" and attempt < max_attempts:
                    retry.append((review, lens))
                    continue
                if parsed["status"] in {"parse_failure", "schema_failure"} and key in best_partial:
                    candidate = best_partial[key]
                resolved[key] = candidate
            append_jsonl(raw_path, raw_rows)
            unresolved = retry
            if not unresolved:
                break
        batch_rows = [resolved[(review["review_id"], lens)] for review, lens in original]
        append_jsonl(lens_path, batch_rows)
        existing.update({(row["review_id"], row["lens"]): row for row in batch_rows})
        progress(len(existing), total)
    final_lens = [
        existing[(review["review_id"], lens)] for review in reviews for lens in LENSES
    ]
    write_jsonl(lens_path, final_lens)
    merged = _merge_outputs(reviews, final_lens, v1_rows)
    for row in merged:
        row["backend"] = "vllm"
    write_jsonl(output_path, merged)
    save_json(
        root / "extraction_run.json",
        {
            "status": "complete" if all(row["status"] == "success" for row in merged) else "incomplete",
            "backend": "vllm",
            "vllm_version": "0.27.1",
            "environment": MODEL_ENV,
            "model": runner.model_id,
            "model_path": runner.model_path,
            "prompt_version": "span_extraction_v2.1_three_lens_union_v1",
            "prompt_sha256": {lens: sha256_file(path) for lens, path in LENSES.items()},
            "input": str(input_path),
            "input_sha256": sha256_file(input_path),
            "reviews": len(reviews),
            "expected_tasks": total,
            "elapsed_seconds_this_process": time.time() - started,
            "max_attempts": max_attempts,
            "v1_spans": sum(row["v1_span_count"] for row in merged),
            "v2_union_spans": sum(row["v2_union_span_count"] for row in merged),
            "output": str(output_path),
            "output_sha256": sha256_file(output_path),
        },
    )
    return merged


def run_verification(
    runner: VLLMRunner,
    root: Path,
    progress: Callable[[int, int], None],
    max_attempts: int = 2,
) -> list[dict[str, Any]]:
    inputs = _prepare_verification(root / "span_extractions.jsonl", root)
    output_path = root / "semantic_verifications.jsonl"
    raw_path = root / "semantic_verification_raw.jsonl"
    existing = {
        row["span_id"]: row
        for row in read_jsonl(output_path)
        if row.get("status") == "success"
    }
    pending = [row for row in inputs if row["span_id"] not in existing]
    prompt_path = ROOT / "prompts" / "semantic_verification_v1_1.txt"
    template = prompt_path.read_text(encoding="utf-8")
    started = time.time()
    progress(len(existing), len(inputs))
    for start in range(0, len(pending), runner.chunk_size):
        original = pending[start : start + runner.chunk_size]
        unresolved = list(original)
        resolved: dict[str, dict[str, Any]] = {}
        for attempt in range(1, max_attempts + 1):
            prompts = []
            for source in unresolved:
                prompt = render_verification_prompt(template, source)
                if attempt > 1:
                    prompt += (
                        "\nThe previous response failed strict schema validation. Return exactly "
                        "one valid JSON object and copy span_id and quote unchanged."
                    )
                prompts.append(prompt)
            decoded, seconds = runner.generate(prompts, 300)
            retry = []
            raw_rows = []
            for source, raw in zip(unresolved, decoded):
                parsed = apply_semantic_guardrails(
                    parse_verification(raw, source), source
                )
                raw_rows.append(
                    {
                        "span_id": source["span_id"],
                        "attempt": attempt,
                        "raw_output": raw,
                        "validation_status": parsed["status"],
                        "latency_share_seconds": seconds / max(len(unresolved), 1),
                        "backend": "vllm",
                    }
                )
                if parsed["status"] != "success" and attempt < max_attempts:
                    retry.append(source)
                    continue
                resolved[source["span_id"]] = {
                    **source,
                    **parsed,
                    "attempts": attempt,
                    "backend": "vllm",
                    "reused_from_v1": False,
                }
            append_jsonl(raw_path, raw_rows)
            unresolved = retry
            if not unresolved:
                break
        batch_rows = [resolved[row["span_id"]] for row in original]
        append_jsonl(output_path, batch_rows)
        existing.update({row["span_id"]: row for row in batch_rows})
        progress(len(existing), len(inputs))
    final_rows = [existing[row["span_id"]] for row in inputs]
    write_jsonl(output_path, final_rows)
    successful = [row for row in final_rows if row.get("status") == "success"]
    save_json(
        root / "verification_run.json",
        {
            "status": "complete" if len(successful) == len(inputs) else "incomplete",
            "backend": "vllm",
            "vllm_version": "0.27.1",
            "environment": MODEL_ENV,
            "model": runner.model_id,
            "model_path": runner.model_path,
            "prompt_version": load_config()["verification_prompt_version"],
            "prompt_sha256": sha256_file(prompt_path),
            "input_sha256": sha256_file(root / "semantic_verification_input.jsonl"),
            "input_spans": len(inputs),
            "schema_success": len(successful),
            "accepted": sum(row.get("accepted") is True for row in successful),
            "rejected": sum(row.get("accepted") is False for row in successful),
            "semantic_guardrail_applied": sum(
                bool(row.get("semantic_guardrail")) for row in successful
            ),
            "elapsed_seconds_this_process": time.time() - started,
            "max_attempts": max_attempts,
            "output": str(output_path),
            "output_sha256": sha256_file(output_path),
        },
    )
    return final_rows


def _dataset_metrics(root: Path) -> dict[str, Any]:
    extracted = read_jsonl(root / "span_extractions.jsonl")
    verified = read_jsonl(root / "semantic_verifications.jsonl")
    accepted = [row for row in verified if row.get("status") == "success" and row.get("accepted")]
    users: dict[str, set[str]] = defaultdict(set)
    for row in accepted:
        users[str(row["asin"])].add(str(row.get("user_id") or row["review_id"]))
    return {
        "reviews": len(extracted),
        "exact_spans": sum(len(row.get("evidence", [])) for row in extracted),
        "reviews_with_evidence": sum(bool(row.get("evidence")) for row in extracted),
        "verified": len(verified),
        "accepted": len(accepted),
        "rejected": sum(row.get("status") == "success" and row.get("accepted") is False for row in verified),
        "target_products": len(users),
        "multi_user_products": sum(len(value) >= 2 for value in users.values()),
    }


def _comparison(old_root: Path, new_root: Path) -> dict[str, Any]:
    def spans(root: Path) -> set[tuple[str, str]]:
        return {
            (row["review_id"], evidence["quote"])
            for row in read_jsonl(root / "span_extractions.jsonl")
            for evidence in row.get("evidence", [])
        }

    old_spans, new_spans = spans(old_root), spans(new_root)
    old_verify = {
        (row["review_id"], row["quote"]): row.get("accepted")
        for row in read_jsonl(old_root / "semantic_verifications.jsonl")
        if row.get("status") == "success"
    }
    new_verify = {
        (row["review_id"], row["quote"]): row.get("accepted")
        for row in read_jsonl(new_root / "semantic_verifications.jsonl")
        if row.get("status") == "success"
    }
    shared = set(old_verify) & set(new_verify)
    return {
        "old_spans": len(old_spans),
        "new_spans": len(new_spans),
        "shared_spans": len(old_spans & new_spans),
        "span_jaccard": len(old_spans & new_spans) / max(len(old_spans | new_spans), 1),
        "shared_verified_spans": len(shared),
        "accepted_decision_agreement": sum(old_verify[key] == new_verify[key] for key in shared) / max(len(shared), 1),
    }


def build_final_report() -> dict[str, Any]:
    roots = {
        "pilot_v1": VLLM_ROOT / "pilot" / "v1",
        "pilot_v2": VLLM_ROOT / "pilot" / "v2",
        "dense_100x5": VLLM_ROOT / "dense_100x5" / "v2",
        "dense_500": VLLM_ROOT / "dense_500" / "v2",
    }
    metrics = {name: _dataset_metrics(root) for name, root in roots.items()}
    comparisons = {
        "pilot_v1": _comparison(ROOT / "data" / "output", roots["pilot_v1"]),
        "pilot_v2": _comparison(ROOT / "data" / "v2", roots["pilot_v2"]),
        "dense_100x5": _comparison(ROOT / "data" / "dense" / "simple_100x5" / "v2", roots["dense_100x5"]),
    }
    result = {
        "status": "complete",
        "backend": "vllm",
        "vllm_version": "0.27.1",
        "environment": MODEL_ENV,
        "protected_test_used": False,
        "datasets": metrics,
        "transformers_comparison": comparisons,
    }
    result_root = ROOT / "experiments" / "10_vllm_rerun" / "results"
    save_json(result_root / "metrics.json", result)
    rows = "\n".join(
        f"| {name} | {value['reviews']:,} | {value['exact_spans']:,} | {value['accepted']:,} | {value['target_products']:,} | {value['multi_user_products']:,} |"
        for name, value in metrics.items()
    )
    comparison_rows = "\n".join(
        f"| {name} | {value['old_spans']:,} | {value['new_spans']:,} | {value['span_jaccard']:.2%} | {value['accepted_decision_agreement']:.2%} |"
        for name, value in comparisons.items()
    )
    report = f"""# vLLM 전체 재실행 결과

> 실행일: 2026-08-13  
> 백엔드: vLLM 0.27.1, Qwen3-VL-8B-Instruct, BitsAndBytes 4-bit  
> 데이터: train-only, protected test 미사용

## 결과 요약

| 데이터 | 리뷰 | exact span | accepted | target 상품 | 다중 사용자 상품 |
|---|---:|---:|---:|---:|---:|
{rows}

## 기존 Transformers 결과와 비교

| 데이터 | 기존 span | vLLM span | span Jaccard | 공통 span 판정 일치율 |
|---|---:|---:|---:|---:|
{comparison_rows}

백엔드가 달라지면 greedy decoding이어도 양자화 커널과 수치 연산 차이로 생성 경계가
달라질 수 있다. 따라서 기존 결과를 섞지 않고 별도 경로에 보존했으며, 이후 사람 검수와
M0/M1 재평가는 이 vLLM 산출물만 사용한다.
"""
    result_root.mkdir(parents=True, exist_ok=True)
    (result_root / "report.md").write_text(report, encoding="utf-8")
    (ROOT / "notion" / "11_VLLM_RERUN_RESULTS.md").write_text(report, encoding="utf-8")
    return result


def run_all_vllm() -> dict[str, Any]:
    notifier = ProgressNotifier(VLLM_ROOT / "progress.json")
    try:
        runner = VLLMRunner()
        pilot_input = ROOT / "data" / "input" / "reviews_pilot.jsonl"
        pilot_v1_root = VLLM_ROOT / "pilot" / "v1"
        pilot_v1 = run_v1_extraction(
            runner,
            pilot_input,
            pilot_v1_root,
            lambda done, total: notifier.update(5 * done / max(total, 1), f"pilot v1 추출 {done:,}/{total:,}"),
        )
        pilot_v1_verified = run_verification(
            runner,
            pilot_v1_root,
            lambda done, total: notifier.update(5 + 5 * done / max(total, 1), f"pilot v1 의미 검증 {done:,}/{total:,}"),
        )

        datasets = [
            ("pilot", pilot_input, VLLM_ROOT / "pilot" / "v2"),
            ("dense 100x5", ROOT / "data" / "dense" / "simple_100x5" / "reviews_product_dense.jsonl", VLLM_ROOT / "dense_100x5" / "v2"),
            ("dense 500", ROOT / "data" / "dense" / "reviews_product_dense.jsonl", VLLM_ROOT / "dense_500" / "v2"),
        ]
        extraction_totals = [
            len(read_jsonl(path)) * len(LENSES) for _, path, _ in datasets
        ]
        extraction_base = 0
        for (name, input_path, output_root), task_total in zip(datasets, extraction_totals):
            run_recall_extraction(
                runner,
                input_path,
                output_root,
                pilot_v1,
                lambda done, total, base=extraction_base, label=name: notifier.update(
                    10 + 60 * (base + done) / sum(extraction_totals),
                    f"{label} Recall v2 추출 {done:,}/{total:,}",
                ),
            )
            extraction_base += task_total

        verification_totals = []
        for _, _, root in datasets:
            verification_totals.append(len(_prepare_verification(root / "span_extractions.jsonl", root)))
        verification_base = 0
        for (name, _, root), span_total in zip(datasets, verification_totals):
            run_verification(
                runner,
                root,
                lambda done, total, base=verification_base, label=name: notifier.update(
                    70 + 30 * (base + done) / max(sum(verification_totals), 1),
                    f"{label} 의미 검증 {done:,}/{total:,}",
                ),
            )
            verification_base += span_total
        result = build_final_report()
        notifier.update(100, "전체 vLLM 재실행·비교 보고서 생성 완료")
        return {"status": "complete", "pilot_v1_verified": len(pilot_v1_verified), **result}
    except BaseException as exc:
        notifier.failure(f"{type(exc).__name__}: {exc}")
        raise
