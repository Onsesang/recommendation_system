# A100 Migration Report

## Overall result

**PARTIAL / blocked by host driver compatibility.** Stages 0–8 were
executed without rerunning Phase 0–11 or modifying the NVIDIA kernel driver.
Project/data restoration, path relocation, both Python environments, all four
pinned model snapshots, the `texture` CUDA test, all 43 unit tests, and all
Phase manifests were verified. Final completion remains blocked only by the host
driver being unable to initialize the pinned CUDA 13 PyTorch environment.

## Timing

- Started: 2026-08-25 18:13 KST (first host/GPU inspection)
- Report completed: 2026-08-25 18:48 KST

## Stage 0 — transfer integrity

- Bundle: `/home/user/onsesang/incoming/a100_migration_bundle_20260825`
- `SHA256SUMS.parts`: all 5 entries passed.
- `SHA256SUMS.archives`: both archives passed.
- Project ZIP SHA-256: `dde99f0797281da940cb40f26e037d5bd7ce468543dfc3058b643576bf1039a9`
- External-input ZIP SHA-256: `5ff79b8311ff8fe4e89efca4e01daf795519cb8d41fbf930acca4cc35dc64b6d`
- Both ZIPs also passed `unzip -tq` compressed-data verification.

## Stage 1 — restored layout and inventory

The existing extracted directories were owned by `user:user`. They were not
blindly overwritten. ZIP entries were compared against the restored tree by
existence and uncompressed size. External inputs matched completely. The two
project exceptions reported by a regular-file check were the intentionally
preserved `gcc` and `g++` symbolic links.

| Restored path | Files | Bytes |
|---|---:|---:|
| `material_span_grounding` (at final report collection) | 1,197 | 612,792,918 |
| `seoyoung/data/splits/train.json` | 1 | 8,508,333 |
| `seoyoung/data/interim/recommendation_interactions.parquet` | 1 | 10,235,921 |
| `yoojeong/amazon_reviews_all/review_Amazon_Fashion` | 5 | 712,734,945 |
| `texture_project/images_train` | 21,059 | 5,342,734,238 |
| `texture_project/data/product_images.json` | 1 | 541,728,917 |

## Stage 2 — host and A100

- OS: Ubuntu 22.04.5 LTS, Linux 6.8.0-101-generic, x86_64
- GPU: NVIDIA A100 80GB PCIe
- VRAM: 81,920 MiB
- Compute capability: 8.0
- NVIDIA driver: 560.35.03
- Maximum CUDA compatibility reported by `nvidia-smi`: 12.6
- Filesystem: 1.8 TiB total, initially about 21 GiB free; only 761 MiB free at
  final inventory after environments and three model snapshots.

No driver, system CUDA, `/usr`, or `/etc` changes were made.

## Stage 3 — absolute-path relocation

- Dry-run: `migration/a100/path_relocation_dry_run.json`
- Applied manifest: `migration/a100/path_relocation_manifest.json`
- Changed files: 134
- Replacements: 8,885
- Mapping: `/home/onsesang` -> `/home/user/onsesang`
- Scope: project text extensions accepted by `relocate_paths.py`; no image,
  NPZ, Parquet, Arrow, or model binary was changed.
- Remaining old-home strings are in preserved historical `.log` files and the
  migration handoff/instructions. Historical logs were not rewritten.

## Stage 4 — environments

Miniconda was installed at `/home/user/onsesang/miniconda3`. Anaconda's
`defaults` channel required interactive Terms-of-Service acceptance. No legal
terms were accepted on the user's behalf; the environment channel was changed
to `conda-forge`, and channel-specific low-level runtime pins were allowed to
resolve there. Python and all pinned pip package versions were retained.

| Environment | Python | torch / build CUDA | torchvision | transformers | vLLM | bitsandbytes |
|---|---|---|---|---|---|---|
| `texture` | 3.10.20 | 2.5.1+cu121 / 12.1 | 0.20.1+cu121 | 5.7.0.dev0 from commit `a66638d854ae536e0ca31e8bcfa480adfaf58284` | n/a | 0.49.2 |
| `material_vllm312` | 3.12.13 | 2.13.0+cu130 / 13.0 | 0.28.0+cu130 | 5.15.0 | 0.27.1 | 0.50.0 |

`pip check` reports no broken requirements for `material_vllm312`. The
`texture` environment also matches numpy 2.2.6, pandas 2.3.3, and
scikit-learn 1.7.2.

The safe secret-free template exists at `shopping_agent/.env.example`.

## Stage 5 — pinned models

All available snapshots below passed network-disabled, `local_files_only=True`
config and processor/tokenizer loading.

| Model | Revision | Resolved snapshot | Result |
|---|---|---|---|
| FashionCLIP | `7e3ba62ce16b379a1ab479346b66f192e76f51b7` | `/home/user/onsesang/.cache/huggingface/hub/models--patrickjohncyh--fashion-clip/snapshots/7e3ba62ce16b379a1ab479346b66f192e76f51b7` | PASS |
| DINOv2-small | `ed25f3a31f01632728cabb09d1542f84ab7b0056` | `/home/user/onsesang/.cache/huggingface/hub/models--facebook--dinov2-small/snapshots/ed25f3a31f01632728cabb09d1542f84ab7b0056` | PASS |
| BGE small EN v1.5 | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` | `/home/user/onsesang/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` | PASS |
| Qwen3-VL-8B-Instruct | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` | `/home/user/onsesang/.cache/huggingface/hub/models--Qwen--Qwen3-VL-8B-Instruct/snapshots/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` | PASS (completed 2026-09-03) |

`/home/user/.cache/huggingface` already existed as a real directory, so it was
preserved rather than replaced. Migration commands explicitly set `HF_HOME` and
`HF_HUB_CACHE` to the fixed workspace cache.

## Stage 6 — CUDA and tests

- `texture`: **PASS**. CUDA available; A100 name and capability `(8, 0)`
  detected; 1024x1024 CUDA tensor sum returned `1048576.0`.
- `material_vllm312`: imports and pinned versions **PASS**, CUDA initialization
  **FAIL**. Exact runtime error: `The NVIDIA driver on your system is too old
  (found version 12060)`. The pinned PyTorch build requires CUDA 13.0 while the
  host driver exposes CUDA 12.6 compatibility.
- Root unittest: **PASS**, `Ran 20 tests`, `OK`.
- v2 unittest: **PASS**, `Ran 23 tests`, `OK`.

Logs:

- `migration/a100/bootstrap_a100.log`
- `migration/a100/verify_a100.log`
- `migration/a100/root_unittest.log`
- `migration/a100/v2_unittest.log`
- `migration/a100/download_models_non_qwen.log`

## Stage 7 — existing Phase 0–11 state

No phase runner was invoked. `scripts/run_phase_sequence.py` was not executed.

| Manifest | Status |
|---|---|
| phase0_full_pool | complete |
| phase1_taxonomy | complete |
| phase2_axis_grounding | complete |
| phase3_diagnostics | complete |
| phase4_human_audit | skipped_by_user_pending |
| phase5_targets | complete |
| phase6_7_models | complete |
| phase8_external | complete_with_leeds_unavailable |
| phase9_selective | complete |
| phase10_retrieval | complete |
| phase11_final | complete |

Critical artifact inventory:

| File | Bytes | SHA-256 |
|---|---:|---|
| `data/reviews_full_pool.jsonl` | 31,039,535 | `5a323c90fa7ae3c13e384997ae40147655b7377af9355aa0c8183ee9d25fd429` |
| `data/lexical_tactile_candidates_all.jsonl` | 22,030,644 | `e5ba03252ba2ae2af9d3d1bdf0528b56bbd6087c852ef4cc11943ddf8d0a90cb` |
| `artifacts/axis_groundings.jsonl` | 12,197,883 | `322a0dec2bb91d99ed2e7934b9b6ec61dc3479a2fe2e014707bb5f002c7d0a72` |
| `artifacts/product_axis_targets.jsonl` | 14,238,139 | `017f4e165a2bc1e004418cf7e894df5fe5a290f17dd9e97e75eee35870435fe2` |
| `artifacts/phase6_7_model_results.json` | 82,043 | `41709b696774682deefcaf2728baa40f8c925ccc55e8fcc4ea1d3b7dbba67927` |
| `artifacts/phase9_selective_results.json` | 175,173 | `1b11d9024249fedc0a86c218f20b86735a07719e5b165a853054fbbff814ff91` |
| `artifacts/phase10_retrieval_results.json` | 17,343 | `1ff7e3c8794ee2045b8680b9fef3fb4ae932dcd5cf75289b6c71243e6df759a0` |
| `artifacts/phase11_paper_results.json` | 705,387 | `9e57d05a4c020e0a6c771994d6856463eb8f107a81c7fef6d5a37a4dfbc724cc` |
| `notion/TACTILE_COLDSTART_V2_FULL_PHASE_0_TO_11.md` | 12,048 | `9de5831c64c2053d32742fbead6fc9a4a891fdc606a9d37792182c1663c223e8` |

Paths in this table are relative to `tactile_coldstart_qwen_v2_full`.

## Differences and required external actions

1. Source WSL used driver 591.59 with CUDA 13.1 compatibility; this A100 host
   uses driver 560.35.03 with CUDA 12.6 compatibility. A server administrator
   must provide a driver compatible with the pinned CUDA 13.0 PyTorch build.
   The migration intentionally did not change the driver or silently downgrade
   packages.
2. The original Qwen storage blocker is resolved. After external disk space was
   made available, the exact pinned snapshot was downloaded and verified
   offline on 2026-09-03. About 906 GiB remained free after completion.
3. Conda channel changed from Anaconda `defaults` to `conda-forge` to avoid
   accepting Terms of Service on the user's behalf. Low-level runtime builds
   consequently differ, while requested Python and core package versions match.
4. The pinned transformers Git commit currently identifies itself as
   `5.7.0.dev0`; the source handoff did not provide a numeric transformers
   version for that commit, only the same commit hash.
5. Phase 4 human audit remains intentionally unperformed, and Leeds remains
   unavailable/unconfirmed. These statuses were not upgraded.

After driver remediation, rerun `migration/a100/verify_a100.sh`; do not rerun
Phase 0–11.

## Post-report safe cleanup

At the user's request, verified transfer copies and regenerable installer/cache
files were removed after the migration report was first completed:

- completed external-input ZIP and its three split parts;
- project ZIP;
- downloaded Miniconda installer;
- Conda package/index caches, pip cache, and migration temporary contents.

The removed archive/installer files totaled 11,023,341,423 bytes, plus a small
amount of package metadata/cache. The checksum documents and handoff document
were retained. Restored inputs, both Conda environments, three downloaded model
snapshots, source code, logs, and Phase 0–11 outputs were rechecked and remain
present. Available filesystem space after cleanup was 11,880,095,744 bytes
(about 11.1 GiB, shown as 12 GB by `df -h`). Deleted transfer archives are not
recoverable locally and must be retransmitted from the source if needed.

## 2026-09-03 storage and Qwen completion update

Additional filesystem capacity became available without deleting or modifying
other users' data. The pinned `Qwen/Qwen3-VL-8B-Instruct` revision
`0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` was downloaded into the workspace
Hugging Face cache. All four weight blobs were checked against their expected
sizes and hashes during download; the final missing shard was verified as
4,999,831,048 bytes with SHA-256
`83de00eafe6e0d57ccd009dbcf71c9974d74df2f016c27afb7e95aafd16b2192`.
Network-disabled loading passed with model type `qwen3_vl` and processor class
`Qwen3VLProcessor`. The Qwen cache occupies 17 GiB, and `df -h` reported 906 GiB
free after installation. No NVIDIA driver or Phase 0–11 artifact was changed or
rerun. The CUDA 13/host-driver incompatibility remains the sole migration
blocker.
