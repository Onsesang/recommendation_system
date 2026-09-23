from __future__ import annotations

import argparse
import json
from pathlib import Path

from .baselines import generate_baseline_predictions
from .evaluator import evaluate_predictions
from .protocol import DEFAULT_INTERACTIONS, DEFAULT_OUTPUT, build_temporal_protocol
from .report import write_markdown_report


def _prediction(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("prediction must be NAME=PATH")
    name, path = value.split("=", 1)
    if not name or not path:
        raise argparse.ArgumentTypeError("prediction must be NAME=PATH")
    return name, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline recommendation evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--interactions", type=Path, default=DEFAULT_INTERACTIONS)
    prepare.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    prepare.add_argument("--min-user-positives", type=int, default=4)
    prepare.add_argument("--positive-rating", type=float, default=4.0)
    prepare.add_argument("--negatives", type=int, default=100)
    prepare.add_argument("--max-eval-users", type=int, default=None)
    prepare.add_argument("--seed", type=int, default=20260813)

    baselines = sub.add_parser("baselines")
    baselines.add_argument("--protocol-root", type=Path, default=DEFAULT_OUTPUT)
    baselines.add_argument("--output-root", type=Path, default=None)
    baselines.add_argument("--hybrid-weight", type=float, default=0.5)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--protocol-root", type=Path, default=DEFAULT_OUTPUT)
    evaluate.add_argument("--output-root", type=Path, default=None)
    evaluate.add_argument("--prediction", action="append", type=_prediction, required=True)
    evaluate.add_argument("--baseline", default="popularity")
    evaluate.add_argument("--k", type=int, default=10)
    evaluate.add_argument("--bootstrap-samples", type=int, default=5000)
    evaluate.add_argument("--seed", type=int, default=20260813)

    all_parser = sub.add_parser("all")
    all_parser.add_argument("--interactions", type=Path, default=DEFAULT_INTERACTIONS)
    all_parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    all_parser.add_argument("--min-user-positives", type=int, default=4)
    all_parser.add_argument("--negatives", type=int, default=100)
    all_parser.add_argument("--max-eval-users", type=int, default=None)
    all_parser.add_argument("--k", type=int, default=10)
    all_parser.add_argument("--seed", type=int, default=20260813)

    args = parser.parse_args()
    if args.command == "prepare":
        result = build_temporal_protocol(
            interactions_path=args.interactions,
            output_root=args.output_root,
            min_user_positives=args.min_user_positives,
            positive_rating=args.positive_rating,
            negatives_per_case=args.negatives,
            max_eval_users=args.max_eval_users,
            seed=args.seed,
        )
    elif args.command == "baselines":
        result = generate_baseline_predictions(
            protocol_root=args.protocol_root,
            output_root=args.output_root,
            hybrid_weight=args.hybrid_weight,
        )
    elif args.command == "evaluate":
        result = evaluate_predictions(
            predictions=dict(args.prediction),
            protocol_root=args.protocol_root,
            output_root=args.output_root,
            k=args.k,
            baseline=args.baseline,
            bootstrap_samples=args.bootstrap_samples,
            seed=args.seed,
        )
        report_root = Path(args.output_root or args.protocol_root / "results")
        write_markdown_report(report_root / "report.md", result)
    else:
        protocol = build_temporal_protocol(
            interactions_path=args.interactions,
            output_root=args.output_root,
            min_user_positives=args.min_user_positives,
            negatives_per_case=args.negatives,
            max_eval_users=args.max_eval_users,
            seed=args.seed,
        )
        baseline_manifest = generate_baseline_predictions(protocol_root=args.output_root)
        result = evaluate_predictions(
            predictions={name: Path(path) for name, path in baseline_manifest["models"].items()},
            protocol_root=args.output_root,
            k=args.k,
            baseline="popularity",
            seed=args.seed,
        )
        result["protocol"] = protocol
        write_markdown_report(args.output_root / "results/report.md", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
