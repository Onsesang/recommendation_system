# Tactile Cold-Start Qwen v2 — Full Pool

This directory is an isolated rerun of the tactile cold-start experiment. It
does not overwrite v1.

Core protocol:

- include every eligible ASIN; there is no 500-product cap;
- prediction unit is ASIN, split unit is `parent_asin` product family;
- every family seen in v1 is forced into train;
- development and the single locked test contain only previously unseen families;
- all eligible reviews are scanned by a high-recall lexical candidate miner;
- Qwen performs conservative semantic accept/reject and axis grounding on a
  deterministic reviewer-first representative pool;
- primary targets are direction-only `-1/0/+1`; raw intensity is retained;
- human audit is explicitly skipped/pending, never represented as complete.

Run all restart-safe phases with a webhook supplied only through the process
environment:

```bash
TACTILE_DISCORD_WEBHOOK=... \
  /home/user/onsesang/miniconda3/envs/texture/bin/python \
  scripts/run_phase_sequence.py
```

The webhook is never stored in this project. Final Korean Notion-ready results
are written to `notion/TACTILE_COLDSTART_V2_FULL_PHASE_0_TO_11.md`.
