#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text())


def sha(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    config = load(ROOT / "config.json")
    grounding = load(ROOT / "manifests" / "ground_classes.json")
    targets = load(ROOT / "manifests" / "build_targets.json")
    training = load(ROOT / "manifests" / "train_fashionclip.json")
    results = load(ROOT / "artifacts" / "fashionclip_results.json")
    selected = training["selected_by_development"]
    lines = [
        "# Tactile atomic-class Qwen32B + FashionCLIP fine-tuning",
        "",
        f"- Completed: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "- Status: complete",
        "- Existing v2 Phase 0–11: preserved and not rerun",
        "",
        "## Research change",
        "",
        "The original open-vocabulary review spans are preserved, while a derived atomic tactile class representation is added. The prediction task is masked multi-label classification rather than numeric axis regression. Unmentioned classes remain unobserved rather than negative.",
        "",
        "## Data and semantic labeling",
        "",
        f"- Products: {targets['products']:,}",
        f"- Candidate spans processed: {grounding['records']:,}",
        f"- Observed product-class pairs: {targets['observed_pairs']:,}",
        f"- Classes: {', '.join(targets['classes'])}",
        f"- Qwen model: `{grounding['model_id']}`",
        f"- Revision: `{grounding['revision']}`",
        f"- Quantization: `{grounding['quantization']}`",
        "",
        "## FashionCLIP ablation",
        "",
        "| Regime | Dev macro-F1 | Test macro-F1 | Test micro-F1 | Test macro-AP |",
        "|---|---:|---:|---:|---:|",
    ]
    for regime, row in results.items():
        dev, test = row["development"], row["test"]
        lines.append(f"| {regime} | {dev['macro_f1']:.4f} | {test['macro_f1']:.4f} | {test['micro_f1']:.4f} | {(test['macro_average_precision'] or 0):.4f} |")
    lines.extend([
        "", "## Selected method", "",
        f"`{selected}` was selected using development macro-F1 only. Its locked-test macro-F1 is {results[selected]['test']['macro_f1']:.4f}.",
        "", "## Per-class locked-test results", "",
        "| Class | Observed | Positive | Precision | Recall | F1 | AP |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for name, row in results[selected]["test"]["per_class"].items():
        lines.append(f"| {name} | {row['observed']} | {row['positive']} | {row['precision']:.4f} | {row['recall']:.4f} | {row['f1']:.4f} | {row.get('average_precision', 0):.4f} |")
    lines.extend([
        "", "## Reproducibility", "",
        f"- Config SHA-256: `{sha(ROOT / 'config.json')}`",
        f"- Groundings SHA-256: `{sha(ROOT / 'artifacts' / 'class_groundings.jsonl')}`",
        f"- Targets SHA-256: `{sha(ROOT / 'artifacts' / 'product_class_targets.npz')}`",
        "- Family-disjoint train/development/test split was reused without modification.",
        "- Raw reviews, original spans, image-derived evidence, and review-derived evidence remain distinguishable.",
        "",
        "## Interpretation cautions", "",
        "- Labels are Qwen-derived pseudo-labels unless separately human-audited.",
        "- A missing class mention is not evidence that the class is absent.",
        "- Fine-tuning improvements must be interpreted against the frozen baseline and category shortcuts.",
    ])
    notion = ROOT / "notion"; notion.mkdir(exist_ok=True)
    report = notion / "TACTILE_CLASS_MULTILABEL_QWEN32B_FASHIONCLIP_FT.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "manifests" / "final.json").write_text(json.dumps({"status": "complete", "report": str(report), "selected": selected}, indent=2) + "\n")
    print(report); return 0


if __name__ == "__main__": raise SystemExit(main())
