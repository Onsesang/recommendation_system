from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .database import iso_now


@dataclass
class Trace:
    trace_id: str
    name: str
    session_hash: str
    started_at: str
    inputs: dict[str, Any]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, Any] | None = None
    error: str | None = None
    ended_at: str | None = None


class TraceRecorder:
    """LangSmith-ready run boundary with a dependency-free local JSONL sink."""

    def __init__(self, root: Path, *, project: str, langsmith_enabled: bool = False) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.project = project
        self.langsmith_enabled = bool(langsmith_enabled)

    def start(self, *, name: str, session_id: str, inputs: dict[str, Any]) -> Trace:
        return Trace(
            trace_id=str(uuid.uuid4()),
            name=name,
            session_hash=hashlib.sha256(session_id.encode()).hexdigest()[:16],
            started_at=iso_now(),
            inputs=inputs,
        )

    @staticmethod
    def tool(trace: Trace, *, name: str, inputs: dict[str, Any], output_summary: dict[str, Any]) -> None:
        trace.tool_calls.append(
            {"name": name, "inputs": inputs, "output_summary": output_summary, "at": iso_now()}
        )

    def finish(self, trace: Trace, *, outputs: dict[str, Any] | None = None, error: str | None = None) -> None:
        trace.outputs = outputs
        trace.error = error
        trace.ended_at = iso_now()
        payload = {
            **trace.__dict__,
            "project_name": self.project,
            "run_type": "chain",
            "langsmith_ready": True,
            # This flag means the future exporter was requested in configuration.
            # v1 always writes locally; it does not claim that a remote export occurred.
            "langsmith_export_configured": self.langsmith_enabled,
        }
        path = self.root / f"{trace.started_at[:10]}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
