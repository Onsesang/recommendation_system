#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from material_span.extract import run_extraction
from material_span.extract_recall import run_recall_extraction
from material_span.density import build_product_dense_sample
from material_span.dense_m0_m1 import run_dense_m0_m1
from material_span.human_audit import analyze_and_write
from material_span.product_targets import build_product_targets
from material_span.report import build_report
from material_span.recall_report import build_recall_report
from material_span.sample import build_sample
from material_span.simple_m0_m1 import run_simple_m0_m1
from material_span.verify import prepare_verification_input, run_verification
from material_span.verify_recall import (
    prepare_recall_verification,
    run_recall_verification,
)
from material_span.verify_report import build_verification_report
from material_span.vllm_pipeline import run_all_vllm


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen exact material-span pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("--limit", type=int, default=1000)
    extract = sub.add_parser("extract")
    extract.add_argument("--batch-size", type=int, default=8)
    extract.add_argument("--max-attempts", type=int, default=2)
    sub.add_parser("report")
    sub.add_parser("verify-prepare")
    verify = sub.add_parser("verify")
    verify.add_argument("--batch-size", type=int, default=8)
    verify.add_argument("--max-attempts", type=int, default=2)
    sub.add_parser("verify-report")
    sub.add_parser("audit-report")
    density = sub.add_parser("density")
    density.add_argument("--min-users", type=int, default=5)
    density.add_argument("--max-reviews-per-product", type=int, default=10)
    density.add_argument("--max-products", type=int, default=500)
    density.add_argument("--output-root", type=Path, default=None)
    sub.add_parser("simple-m0-m1")
    dense_m0_m1 = sub.add_parser("dense-m0-m1")
    dense_m0_m1.add_argument("--root", type=Path, default=None)
    dense_m0_m1.add_argument("--augment-sparse", action="store_true")
    recall_extract = sub.add_parser("recall-extract")
    recall_extract.add_argument("--batch-size", type=int, default=6)
    recall_extract.add_argument("--max-attempts", type=int, default=2)
    recall_extract.add_argument("--output-root", type=Path, default=None)
    recall_extract.add_argument("--max-reviews", type=int, default=None)
    recall_extract.add_argument("--review-id", action="append", default=[])
    recall_extract.add_argument("--input", type=Path, default=None)
    recall_prepare = sub.add_parser("recall-verify-prepare")
    recall_prepare.add_argument("--output-root", type=Path, default=None)
    recall_verify = sub.add_parser("recall-verify")
    recall_verify.add_argument("--batch-size", type=int, default=8)
    recall_verify.add_argument("--max-attempts", type=int, default=2)
    recall_verify.add_argument("--output-root", type=Path, default=None)
    recall_report = sub.add_parser("recall-report")
    recall_report.add_argument("--output-root", type=Path, default=None)
    all_parser = sub.add_parser("all")
    all_parser.add_argument("--limit", type=int, default=1000)
    all_parser.add_argument("--batch-size", type=int, default=8)
    sub.add_parser("vllm-rerun")
    product_targets = sub.add_parser("product-targets")
    product_targets.add_argument("--input-root", type=Path, default=None)
    product_targets.add_argument("--output-root", type=Path, default=None)

    args = parser.parse_args()
    if args.command == "sample":
        result = build_sample(args.limit)
    elif args.command == "extract":
        result = run_extraction(args.batch_size, args.max_attempts)
    elif args.command == "report":
        result = build_report()
    elif args.command == "verify-prepare":
        result = prepare_verification_input()
    elif args.command == "verify":
        result = run_verification(args.batch_size, args.max_attempts)
    elif args.command == "verify-report":
        result = build_verification_report()
    elif args.command == "audit-report":
        result = analyze_and_write()
    elif args.command == "density":
        result = build_product_dense_sample(
            min_users=args.min_users,
            max_reviews_per_product=args.max_reviews_per_product,
            max_products=args.max_products,
            output_root=args.output_root,
        )
    elif args.command == "simple-m0-m1":
        result = run_simple_m0_m1()
    elif args.command == "dense-m0-m1":
        result = run_dense_m0_m1(args.root, augment_sparse=args.augment_sparse)
    elif args.command == "recall-extract":
        result = run_recall_extraction(
            args.batch_size,
            args.max_attempts,
            args.output_root,
            args.max_reviews,
            set(args.review_id),
            args.input,
        )
    elif args.command == "recall-verify-prepare":
        result = prepare_recall_verification(args.output_root)
    elif args.command == "recall-verify":
        result = run_recall_verification(
            args.batch_size, args.max_attempts, args.output_root
        )
    elif args.command == "recall-report":
        result = build_recall_report(args.output_root)
    elif args.command == "product-targets":
        kwargs = {}
        if args.input_root is not None:
            kwargs["input_root"] = args.input_root
        if args.output_root is not None:
            kwargs["output_root"] = args.output_root
        result = build_product_targets(**kwargs)
    elif args.command == "all":
        sample_result = build_sample(args.limit)
        extraction_result = run_extraction(args.batch_size)
        stage1_report = build_report()
        verification_input = prepare_verification_input()
        verification_result = run_verification(args.batch_size)
        result = {
            "sample": sample_result,
            "extract": extraction_result,
            "report": stage1_report,
            "verification_input": verification_input,
            "verify": verification_result,
            "verification_report": build_verification_report(),
        }
    else:
        result = run_all_vllm()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
