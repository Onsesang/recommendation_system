# Experiment 15: Human Audit

Local, single-reviewer, blind-first audit for the v3 atomic tactile-class experiment.

```bash
cd /home/user/onsesang/material_span_grounding
/home/user/onsesang/miniconda3/envs/texture/bin/streamlit run experiments/15_human_audit/app.py
```

After any amount of annotation:

```bash
/home/user/onsesang/miniconda3/envs/texture/bin/python experiments/15_human_audit/analyze_human_audit.py
```

Do not hand-edit `audit_manifest.json`. Human fields remain absent from the manifest and are written only to `annotations/human_audit.csv` when the reviewer saves the blind form.
