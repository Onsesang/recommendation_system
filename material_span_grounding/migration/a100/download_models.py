#!/usr/bin/env python3
"""Download every model at the exact revision recorded by the experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


MODELS = (
    ("Qwen/Qwen3-VL-8B-Instruct", "0c351dd01ed87e9c1b53cbc748cba10e6187ff3b"),
    ("patrickjohncyh/fashion-clip", "7e3ba62ce16b379a1ab479346b66f192e76f51b7"),
    ("facebook/dinov2-small", "ed25f3a31f01632728cabb09d1542f84ab7b0056"),
    ("BAAI/bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--skip-qwen", action="store_true")
    args = parser.parse_args()

    for repo_id, revision in MODELS:
        if args.skip_qwen and repo_id.startswith("Qwen/"):
            print(f"SKIP {repo_id}")
            continue
        path = snapshot_download(
            repo_id=repo_id,
            revision=revision,
            cache_dir=str(args.cache_dir.expanduser()) if args.cache_dir else None,
        )
        print(f"OK {repo_id}@{revision} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
