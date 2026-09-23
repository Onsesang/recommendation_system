#!/usr/bin/env python3
"""Resume-safe Experiment 17 pipeline. Experiment 16 is always read-only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
import torch
from torch.nn import functional as F

from models_history3 import BERT4Rec, GRU4Rec

ROOT = Path(__file__).resolve().parent
EXP16 = ROOT.parent / "16_strong_recommender_tactile"
DATA = EXP16 / "data"
OLD_ART = EXP16 / "artifacts"
ART = ROOT / "artifacts"
CKPT = ROOT / "checkpoints"
CACHE = ROOT / "caches"
LOG = ROOT / "logs"
MAN = ROOT / "manifests"
TABLE = ROOT / "tables"
CFG = json.loads((ROOT / "configs/experiment.json").read_text())
SEED = CFG["seed"]
MODELS = ["popularity", "bpr", "sasrec", "esasrec", "bert4rec", "gru4rec", "smore"]
DISPLAY = {"popularity": "Popularity", "bpr": "BPR-MF", "sasrec": "SASRec",
           "esasrec": "eSASRec", "bert4rec": "BERT4Rec", "gru4rec": "GRU4Rec",
           "smore": "SMORE-derived"}
CLASSES = ["soft", "firm", "smooth", "rough", "non_elastic", "elastic", "thin",
           "thick", "flexible", "stiff", "warm", "cool", "spongy", "crisp"]


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def atomic_json(path: Path, obj: object) -> None:
    atomic_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    os.replace(tmp, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def sha(path: Path, block: int = 16 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while b := f.read(block):
            h.update(b)
    return h.hexdigest()


def state() -> dict:
    return json.loads((ROOT / "run_state.json").read_text())


def set_state(stage: str, status: str) -> None:
    x = state(); x[stage] = status; atomic_json(ROOT / "run_state.json", x)
    completed = [k for k, v in x.items() if v == "complete"]
    running = [k for k, v in x.items() if v == "running"]
    pending = [k for k, v in x.items() if v == "pending"]
    failed = [k for k, v in x.items() if v == "failed"]
    next_stage = pending[0] if pending else "none"
    body = ("# 실행 상태\n\n"
            f"- Completed: {', '.join(completed) or '없음'}\n"
            f"- Running: {', '.join(running) or '없음'}\n"
            f"- Pending: {', '.join(pending) or '없음'}\n"
            f"- Failed: {', '.join(failed) or '없음'}\n"
            f"- Next command / next stage: `./resume.sh` ({next_stage})\n")
    atomic_text(ROOT / "RUN_STATUS.md", body)


def event(stage: str, status: str, **extra: object) -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    row = {"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "stage": stage, "status": status, **extra}
    with (LOG / "events.jsonl").open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def metric_dict(ranks: np.ndarray) -> dict:
    r = np.asarray(ranks)
    ok = (r > 0) & (r <= 10)
    out = {"users": int(len(r)),
           "ndcg_at_10": float(np.where(ok, 1 / np.log2(np.maximum(r, 1) + 1), 0).mean()),
           "hr_at_10": float(ok.mean()),
           "mrr_at_10": float(np.where(ok, 1 / np.maximum(r, 1), 0).mean())}
    for k in CFG["candidate_k_grid"]:
        out[f"recall_at_{k}"] = float(((r > 0) & (r <= k)).mean())
    return out


def per_user_frame(targets: pd.DataFrame, ranks: np.ndarray, model: str) -> pd.DataFrame:
    r = np.asarray(ranks)
    ok = (r > 0) & (r <= 10)
    out = targets[["uid", "user_id", "iid", "parent_asin", "history_length"]].copy()
    out["model"] = model; out["rank"] = r.astype(np.int32)
    out["ndcg_at_10"] = np.where(ok, 1 / np.log2(np.maximum(r, 1) + 1), 0)
    out["hr_at_10"] = ok.astype(np.int8)
    out["mrr_at_10"] = np.where(ok, 1 / np.maximum(r, 1), 0)
    return out


def exp16_snapshot() -> list[dict]:
    rows = []
    for p in sorted(EXP16.rglob("*")):
        if p.is_file():
            s = p.stat()
            rows.append({"path": str(p.relative_to(EXP16)), "size": s.st_size,
                         "mtime_ns": s.st_mtime_ns})
    return rows


def audit() -> None:
    set_state("audit", "running"); event("audit", "started")
    if not EXP16.is_dir():
        raise FileNotFoundError(EXP16)
    before = MAN / "experiment16_stat_snapshot.json"
    if not before.exists(): atomic_json(before, exp16_snapshot())
    sources = {
        "processed Amazon Fashion split": DATA / "events.parquet",
        "user history cache/source": DATA / "events.parquet",
        "user mapping": DATA / "users.parquet",
        "item mapping/catalog": DATA / "catalog.parquet",
        "ASIN to parent_ASIN mapping": DATA / "child_parent_mapping.parquet",
        "validation event/targets": DATA / "validation_targets.parquet",
        "test event/targets": DATA / "test_targets.parquet",
        "popularity ranking/cache": DATA / "catalog.parquet",
        "BPR checkpoints": OLD_ART / "checkpoints/bpr_lr0.0003.pt",
        "SASRec checkpoints": OLD_ART / "checkpoints/sasrec_lr0.0003.pt",
        "eSASRec checkpoints": OLD_ART / "checkpoints/esasrec_lr0.0003.pt",
        "SMORE checkpoint/features": OLD_ART / "checkpoints/smore_lr0.001.pt",
        "FashionCLIP feature cache": DATA / "smore/image_feat.npy",
        "image cache": OLD_ART / "feature_chunks",
        "Last2 14D tactile probability": OLD_ART / "product_tactile_profiles.parquet",
        "fashionclip_last2.pt": ROOT.parent / "12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt",
        "validation results": OLD_ART / "backbone_validation_results.csv",
        "candidate results": OLD_ART / "validation_candidate_chunks",
        "alpha search": OLD_ART / "alpha_search.csv",
        "per-user test rankings": OLD_ART / "sasrec_test_per_user.parquet",
    }
    classes = {
        "processed Amazon Fashion split": "REUSE_DIRECTLY", "user history cache/source": "REUSE_AFTER_FILTERING", "user mapping": "REUSE_DIRECTLY",
        "item mapping/catalog": "REUSE_DIRECTLY", "ASIN to parent_ASIN mapping": "REUSE_DIRECTLY",
        "validation event/targets": "REUSE_AFTER_FILTERING", "test event/targets": "REUSE_AFTER_FILTERING",
        "popularity ranking/cache": "REUSE_FOR_REEVALUATION", "BPR checkpoints": "REUSE_FOR_REEVALUATION",
        "SASRec checkpoints": "REUSE_FOR_REEVALUATION", "eSASRec checkpoints": "REUSE_FOR_REEVALUATION",
        "SMORE checkpoint/features": "REUSE_FOR_REEVALUATION", "FashionCLIP feature cache": "REUSE_DIRECTLY",
        "image cache": "REUSE_DIRECTLY", "Last2 14D tactile probability": "REUSE_DIRECTLY",
        "fashionclip_last2.pt": "REUSE_DIRECTLY", "validation results": "REUSE_AFTER_FILTERING",
        "candidate results": "REUSE_AFTER_FILTERING", "alpha search": "MUST_RECOMPUTE",
        "per-user test rankings": "REUSE_AFTER_FILTERING",
    }
    reasons = {
        "user history cache/source": "rebuild validation/test histories from immutable events and filter evaluation rows only",
        "alpha search": "evaluation cohort changed; rerun the frozen grid",
        "candidate results": "rankings are cohort-independent; retain only history>=3 rows",
        "validation results": "select checkpoints with history>=3 columns, never the all-user winner",
        "per-user test rankings": "rankings are unchanged; recompute metrics after history>=3 filtering",
    }
    rows = []
    for name, p in sources.items():
        exists = p.exists()
        digest = sha(p) if exists and p.is_file() else None
        rows.append({"artifact": name, "source": str(p.resolve()), "exists": exists,
                     "classification": classes[name], "reason": reasons.get(name, "cohort-independent immutable input"),
                     "sha256": digest, "size_bytes": p.stat().st_size if exists and p.is_file() else None})
    frame = pd.DataFrame(rows)
    atomic_csv(MAN / "reuse_manifest.csv", frame)
    atomic_json(ART / "audit_summary.json", {"experiment16": str(EXP16), "items": rows,
                                              "bert4rec": "MUST_RECOMPUTE",
                                              "gru4rec": "MUST_RECOMPUTE"})
    set_state("audit", "complete"); event("audit", "complete", entries=len(rows))


def build_cohorts() -> None:
    set_state("cohort_build", "running"); event("cohort_build", "started")
    rows = []
    for split in ("validation", "test"):
        x = pd.read_parquet(DATA / f"{split}_targets.parquet")
        cohort = x[x.history_length >= CFG["history_min"]].copy().reset_index().rename(columns={"index": "source_row_index"})
        if cohort.uid.duplicated().any(): raise RuntimeError(f"duplicate users in {split} cohort")
        atomic_parquet(CACHE / f"{split}_cohort_history3.parquet", cohort)
        h = cohort.history_length
        for label, mask in (("3-4", h.between(3, 4)), ("5-9", h.between(5, 9)), ("10+", h >= 10)):
            rows.append({"split": split, "history_group": label, "users": int(mask.sum())})
        rows.append({"split": split, "history_group": "all_history3", "users": len(cohort)})
    atomic_csv(TABLE / "table_history_cohort.csv", pd.DataFrame(rows))
    summary = {s: int(pd.read_parquet(CACHE / f"{s}_cohort_history3.parquet", columns=["uid"]).shape[0]) for s in ("validation", "test")}
    if summary != {"validation": 14731, "test": 29991}:
        event("cohort_build", "count_differs_from_expected", **summary)
    atomic_json(ART / "cohort_summary.json", summary)
    set_state("cohort_build", "complete"); event("cohort_build", "complete", **summary)


def old_completed(model: str) -> list[dict]:
    if model == "popularity":
        return [{"name": model, "lr": None, "best_epoch": 0,
                 "validation": json.loads((OLD_ART / "popularity_validation.json").read_text())}]
    return [json.loads(p.read_text()) for p in sorted((OLD_ART / "checkpoints").glob(f"{model}_lr*.complete.json"))]


def existing_validation() -> None:
    set_state("existing_backbones_validation", "running"); event("existing_backbones_validation", "started")
    selected = {}; audit_rows = []
    for name in ("popularity", "bpr", "sasrec", "esasrec", "smore"):
        runs = old_completed(name)
        for r in runs:
            m = r["validation"]["train_history_ge_3"]
            audit_rows.append({"model": name, "learning_rate": r.get("lr"), "epoch": r.get("best_epoch"),
                               "checkpoint": r.get("checkpoint"), **m})
        chosen = max(runs, key=lambda r: (r["validation"]["train_history_ge_3"]["ndcg_at_10"],
                                          r["validation"]["train_history_ge_3"]["hr_at_10"],
                                          r["validation"]["train_history_ge_3"]["mrr_at_10"],
                                          -(r.get("lr") or 0)))
        selected[name] = chosen
    atomic_csv(ART / "existing_checkpoint_revalidation_history3.csv", pd.DataFrame(audit_rows))
    atomic_json(ART / "existing_selected_runs.json", selected)
    set_state("existing_backbones_validation", "complete"); event("existing_backbones_validation", "complete")


class Data:
    def __init__(self):
        self.catalog = pd.read_parquet(DATA / "catalog.parquet")
        self.nitems = len(self.catalog)
        e = pd.read_parquet(DATA / "events.parquet", columns=["uid", "iid", "rating", "split", "timestamp"])
        self.train = e[e.split == "train"].copy()
        self.validation = e[e.split == "validation"].copy()
        self.hist_train = {int(u): g.sort_values("timestamp").iid.to_numpy(dtype=np.int32)
                           for u, g in self.train.groupby("uid", sort=False)}
        self.hist_test = {u: h.copy() for u, h in self.hist_train.items()}
        for row in self.validation.sort_values("timestamp").itertuples():
            self.hist_test[int(row.uid)] = np.append(self.hist_test.get(int(row.uid), np.empty(0, np.int32)), row.iid)
        self.cold = self.catalog.train_count.to_numpy() == 0

    def histories(self, split: str) -> dict[int, np.ndarray]:
        return self.hist_train if split == "validation" else self.hist_test


def device_setup() -> str:
    torch.manual_seed(SEED); np.random.seed(SEED); torch.set_num_threads(8)
    torch.backends.cuda.matmul.allow_tf32 = False
    return "cuda" if torch.cuda.is_available() else "cpu"


def build_train_batch(name: str, uids: np.ndarray, hist: dict, rng: np.random.Generator,
                      nitems: int, maxlen: int, nneg: int):
    seq = np.zeros((len(uids), maxlen), np.int64)
    truth = np.zeros_like(seq); valid = np.zeros_like(seq, bool)
    mask_id = nitems + 1
    for j, u in enumerate(uids):
        h = np.asarray(hist[int(u)][-maxlen:], dtype=np.int64) + 1
        if name == "gru4rec":
            n = len(h) - 1; seq[j, -n:] = h[:-1]; truth[j, -n:] = h[1:]; valid[j, -n:] = True
        else:
            seq[j, -len(h):] = h
            m = rng.random(len(h)) < CFG["mask_probability"]
            if not m.any(): m[rng.integers(len(h))] = True
            pos = np.flatnonzero(m) + maxlen - len(h)
            truth[j, pos] = seq[j, pos]; valid[j, pos] = True; seq[j, pos] = mask_id
    owners = np.repeat(np.arange(len(uids)), valid.sum(1))
    neg = rng.integers(1, nitems + 1, size=(int(valid.sum()), nneg), dtype=np.int64)
    for q, owner in enumerate(owners):
        positive = hist[int(uids[owner])] + 1
        bad = np.isin(neg[q], positive)
        while bad.any():
            neg[q, bad] = rng.integers(1, nitems + 1, size=int(bad.sum()))
            bad = np.isin(neg[q], positive)
    return seq, truth, valid, neg


@torch.no_grad()
def evaluate_new(model, name: str, data: Data, split: str, dev: str, save: Path | None = None,
                 candidates: Path | None = None) -> tuple[dict, pd.DataFrame]:
    targets = pd.read_parquet(CACHE / f"{split}_cohort_history3.parquet")
    hist = data.histories(split); maxlen = CFG["maxlen"]
    ranks = np.empty(len(targets), np.int32); item_ids = torch.arange(data.nitems, device=dev)
    cold_index = torch.as_tensor(data.cold, device=dev)
    # Items without positive train evidence are neutral both as history input and
    # output candidates. Restore parameters after evaluation so validation does
    # not alter subsequent optimization.
    cold_backup = model.item.weight[1:data.nitems + 1][cold_index].detach().clone()
    model.item.weight[1:data.nitems + 1][cold_index] = 0
    items = model.catalog_items().detach().clone()
    model.eval(); candidate_parts = []
    for start in range(0, len(targets), CFG["evaluation_batch_size"]):
        b = targets.iloc[start:start + CFG["evaluation_batch_size"]]
        seq = np.zeros((len(b), maxlen), np.int64)
        for j, u in enumerate(b.uid.to_numpy()):
            h = np.asarray(hist[int(u)], np.int64)
            if name == "bert4rec":
                h = h[-(maxlen - 1):] + 1; seq[j, -len(h)-1:-1] = h; seq[j, -1] = model.mask_id
            else:
                h = h[-maxlen:] + 1; seq[j, -len(h):] = h
        q = model.query(torch.as_tensor(seq, device=dev))
        scores = q @ items.T
        for j, u in enumerate(b.uid.to_numpy()):
            seen = torch.as_tensor(hist[int(u)], device=dev)
            scores[j, seen] = -torch.inf
        truth = torch.as_tensor(b.iid.to_numpy(), device=dev)
        ts = scores[torch.arange(len(b), device=dev), truth]
        if not torch.isfinite(ts).all(): raise FloatingPointError(f"{name} nonfinite targets")
        rr = 1 + (scores > ts[:, None]).sum(1) + ((scores == ts[:, None]) & (item_ids[None] < truth[:, None])).sum(1)
        ranks[start:start + len(b)] = rr.cpu().numpy().astype(np.int32)
        if candidates is not None:
            k = json.loads((ART / "selected_backbone.json").read_text())["candidate_k"]
            vals, ids = torch.topk(scores, k, dim=1, sorted=False)
            # Exact boundary tie correction, consistent with iid tie-break.
            thresholds = vals.min(1).values
            for j in range(len(b)):
                greater = torch.nonzero(scores[j] > thresholds[j]).squeeze(1)
                remain = k - len(greater)
                tied = torch.nonzero(scores[j] == thresholds[j]).squeeze(1)[:remain]
                chosen = torch.cat([greater, tied])
                candidate_parts.append((int(b.source_row_index.iloc[j]), int(b.uid.iloc[j]), int(b.iid.iloc[j]),
                                        int(rr[j]), chosen.cpu().numpy().astype(np.int32),
                                        scores[j, chosen].float().cpu().numpy()))
        event(f"{name}_{split}_evaluation", "progress", done=min(start + len(b), len(targets)), total=len(targets))
    per = per_user_frame(targets, ranks, name)
    model.item.weight[1:data.nitems + 1][cold_index] = cold_backup
    if save is not None: atomic_parquet(save, per)
    if candidates is not None:
        candidates.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(candidate_parts), 128):
            part = candidate_parts[start:start + 128]; dest = candidates / f"{start:09d}_{start+len(part)-1:09d}.npz"
            tmp = dest.with_suffix(".tmp")
            with tmp.open("wb") as f:
                np.savez_compressed(f, row_index=np.array([x[0] for x in part], np.int32),
                                    uid=np.array([x[1] for x in part], np.int32),
                                    target=np.array([x[2] for x in part], np.int32),
                                    base_rank=np.array([x[3] for x in part], np.int32),
                                    candidate=np.stack([x[4] for x in part]), base_score=np.stack([x[5] for x in part]))
            os.replace(tmp, dest)
    return metric_dict(ranks), per


def train_new(name: str) -> None:
    if state()[name] == "complete": return
    set_state(name, "running"); event(name, "started")
    dev = device_setup(); data = Data(); uids = np.array([u for u, h in data.hist_train.items() if len(h) >= 2], np.int32)
    results = []
    for lr in CFG["learning_rates"]:
        tag = f"{name}_lr{lr:g}"; done = CKPT / f"{tag}.complete.json"
        if done.exists(): results.append(json.loads(done.read_text())); continue
        torch.manual_seed(SEED); rng = np.random.default_rng(SEED)
        cls = BERT4Rec if name == "bert4rec" else GRU4Rec
        model = cls(data.nitems, dim=CFG["dim"], layers=CFG["layers"], heads=CFG["heads"],
                    maxlen=CFG["maxlen"], dropout=CFG["dropout"]).to(dev)
        opt = torch.optim.Adam(model.parameters(), lr=lr)
        best = -1.; bad = 0; first_epoch = 1; resume = CKPT / f"{tag}.resume.pt"
        if resume.exists():
            x = torch.load(resume, map_location=dev, weights_only=False); model.load_state_dict(x["model"])
            opt.load_state_dict(x["optimizer"]); best=x["best"]; bad=x["bad"]; first_epoch=x["epoch"]+1
            rng.bit_generator.state=x["rng"]
        for epoch in range(first_epoch, CFG["maximum_epochs"] + 1):
            model.train(); losses=[]
            for start in range(0, len(uids), CFG["batch_size"]):
                bu = uids[rng.permutation(len(uids))[start:start + CFG["batch_size"]]] if start == 0 else None
                # One permutation per epoch, retained outside the hot loop.
                if start == 0: order = rng.permutation(uids)
                bu = order[start:start + CFG["batch_size"]]
                seq, truth, valid, neg = build_train_batch(name, bu, data.hist_train, rng, data.nitems,
                                                            CFG["maxlen"], CFG["negative_samples"])
                st=torch.as_tensor(seq,device=dev); tt=torch.as_tensor(truth,device=dev); vt=torch.as_tensor(valid,device=dev)
                nt=torch.as_tensor(neg,device=dev); z=model(st)[vt]; pos=model.item(tt[vt])
                logits=torch.cat([(z*pos).sum(-1,keepdim=True), torch.einsum("bd,bnd->bn",z,model.item(nt))],1)
                loss=F.cross_entropy(logits,torch.zeros(len(logits),dtype=torch.long,device=dev))
                opt.zero_grad(set_to_none=True); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),5); opt.step()
                losses.append(float(loss.detach()))
            event(name, "epoch", learning_rate=lr, epoch=epoch, loss=float(np.mean(losses)))
            if epoch % CFG["validation_every_epochs"] == 0:
                metrics, _ = evaluate_new(model, name, data, "validation", dev)
                value=metrics["ndcg_at_10"]; event(name,"validation",learning_rate=lr,epoch=epoch,**metrics)
                if value > best:
                    best=value; bad=0
                    tmp=CKPT/f"{tag}.pt.tmp"; torch.save({"model":name,"state_dict":model.state_dict(),"epoch":epoch,
                        "learning_rate":lr,"validation_history3":metrics,"config":CFG},tmp); os.replace(tmp,CKPT/f"{tag}.pt")
                else: bad += 1
            tmp=CKPT/f"{tag}.resume.pt.tmp"; torch.save({"model":model.state_dict(),"optimizer":opt.state_dict(),
                "epoch":epoch,"best":best,"bad":bad,"rng":rng.bit_generator.state},tmp); os.replace(tmp,resume)
            if bad >= CFG["patience"]: break
        best_obj=torch.load(CKPT/f"{tag}.pt",map_location="cpu",weights_only=False)
        record={"model":name,"learning_rate":lr,"best_epoch":best_obj["epoch"],"checkpoint":str((CKPT/f"{tag}.pt").resolve()),
                "checkpoint_sha256":sha(CKPT/f"{tag}.pt"),"validation_history3":best_obj["validation_history3"]}
        atomic_json(done,record); results.append(record); del model,opt; torch.cuda.empty_cache()
    chosen=max(results,key=lambda r:(r["validation_history3"]["ndcg_at_10"],r["validation_history3"]["hr_at_10"],
                                     r["validation_history3"]["mrr_at_10"],-r["learning_rate"]))
    atomic_json(ART/f"{name}_selected_validation.json",chosen)
    set_state(name,"complete"); event(name,"complete",learning_rate=chosen["learning_rate"],**chosen["validation_history3"])


def select_backbone() -> None:
    set_state("backbone_selection","running"); event("backbone_selection","started")
    old=json.loads((ART/"existing_selected_runs.json").read_text()); rows=[]; records={}
    for name in MODELS:
        if name in ("bert4rec","gru4rec"):
            r=json.loads((ART/f"{name}_selected_validation.json").read_text()); m=r["validation_history3"]
            records[name]=r
        else:
            r=old[name]; m=r["validation"]["train_history_ge_3"]; records[name]=r
        rows.append({"model":DISPLAY[name],"model_key":name,"NDCG@10":m["ndcg_at_10"],"HR@10":m["hr_at_10"],
                     "MRR@10":m["mrr_at_10"],**{f"Recall@{k}":m[f"recall_at_{k}"] for k in CFG["candidate_k_grid"]}})
    frame=pd.DataFrame(rows); atomic_csv(ART/"backbone_validation_history3.csv",frame); atomic_csv(TABLE/"table_backbone_validation.csv",frame)
    order={m:i for i,m in enumerate(MODELS)}
    winner=max(MODELS,key=lambda n:(frame.loc[frame.model_key==n,"NDCG@10"].iloc[0],frame.loc[frame.model_key==n,"HR@10"].iloc[0],
                                    frame.loc[frame.model_key==n,"MRR@10"].iloc[0],-order[n]))
    wm=frame[frame.model_key==winner].iloc[0]; k=3000
    for q in CFG["candidate_k_grid"]:
        if wm[f"Recall@{q}"]>=CFG["candidate_recall_threshold"]: k=q; break
    rec=records[winner]; checkpoint=rec.get("checkpoint")
    selected={"model":winner,"display_name":DISPLAY[winner],"selection_metric":"NDCG@10","validation_cohort":"history>=3",
              "candidate_k":k,"candidate_rule_satisfied":bool(wm[f"Recall@{k}"]>=CFG["candidate_recall_threshold"]),
              "validation_metrics":{x:float(wm[x]) for x in ["NDCG@10","HR@10","MRR@10",f"Recall@{k}"]},
              "checkpoint":checkpoint,"checkpoint_sha256":sha(Path(checkpoint)) if checkpoint else None,"record":rec}
    atomic_json(ART/"selected_backbone.json",selected)
    lock={"status":"validation_locked_test_not_used_for_selection","selected_backbone_sha256":sha(ART/"selected_backbone.json"),
          "backbone_validation_sha256":sha(ART/"backbone_validation_history3.csv"),"protocol_sha256":sha(ROOT/"PROTOCOL.md"),
          "test_tuning_forbidden":True}
    atomic_json(ART/"validation_lock.json",lock)
    recall=frame[["model","model_key"]+[f"Recall@{x}" for x in CFG["candidate_k_grid"]]].melt(
        id_vars=["model","model_key"],var_name="K",value_name="Recall")
    recall["K"]=recall.K.str.replace("Recall@","",regex=False).astype(int)
    atomic_csv(TABLE/"table_candidate_recall.csv",recall)
    set_state("backbone_selection","complete"); event("backbone_selection","complete",model=winner,candidate_k=k)


def verify_lock() -> dict:
    lock=json.loads((ART/"validation_lock.json").read_text())
    if lock["status"]!="all_validation_locked_test_not_used_for_selection": raise RuntimeError("all validation choices are not locked")
    for p,key in ((ART/"selected_backbone.json","selected_backbone_sha256"),(ART/"backbone_validation_history3.csv","backbone_validation_sha256"),(ROOT/"PROTOCOL.md","protocol_sha256")):
        if sha(p)!=lock[key]: raise RuntimeError(f"validation input changed: {p}")
    if sha(ART/"selected_tactile.json")!=lock.get("selected_tactile_sha256"): raise RuntimeError("tactile validation selection changed")
    return lock


def load_new_selected(name: str, dev: str, nitems: int):
    r=json.loads((ART/f"{name}_selected_validation.json").read_text()); x=torch.load(r["checkpoint"],map_location=dev,weights_only=False)
    cls=BERT4Rec if name=="bert4rec" else GRU4Rec
    m=cls(nitems,dim=CFG["dim"],layers=CFG["layers"],heads=CFG["heads"],maxlen=CFG["maxlen"],dropout=CFG["dropout"]).to(dev)
    m.load_state_dict(x["state_dict"]); return m


@torch.no_grad()
def evaluate_bpr_selected(data: Data, dev: str) -> pd.DataFrame:
    selected=json.loads((ART/"existing_selected_runs.json").read_text())["bpr"]
    x=torch.load(selected["checkpoint"],map_location=dev,weights_only=False)["state_dict"]
    train_uids=np.sort(data.train.uid.unique()); loc={int(u):j for j,u in enumerate(train_uids)}
    users=x["user.weight"].to(dev); items=x["item.weight"].to(dev).clone(); items[torch.as_tensor(data.cold,device=dev)]=0
    targets=pd.read_parquet(CACHE/"test_cohort_history3.parquet"); ranks=np.empty(len(targets),np.int32)
    ids=torch.arange(data.nitems,device=dev)
    for start in range(0,len(targets),CFG["evaluation_batch_size"]):
        b=targets.iloc[start:start+CFG["evaluation_batch_size"]]; q=users[torch.as_tensor([loc[int(u)] for u in b.uid],device=dev)]
        scores=q@items.T
        for j,u in enumerate(b.uid): scores[j,torch.as_tensor(data.hist_test[int(u)],device=dev)]=-torch.inf
        t=torch.as_tensor(b.iid.to_numpy(),device=dev); ts=scores[torch.arange(len(b),device=dev),t]
        ranks[start:start+len(b)]=(1+(scores>ts[:,None]).sum(1)+((scores==ts[:,None])&(ids[None]<t[:,None])).sum(1)).cpu().numpy()
    return per_user_frame(targets,ranks,"bpr")


def final_test() -> None:
    verify_lock(); set_state("final_test","running"); event("final_test","started")
    data=Data(); dev=device_setup(); target=pd.read_parquet(CACHE/"test_cohort_history3.parquet"); parts=[]; rows=[]
    existing=json.loads((ART/"existing_selected_runs.json").read_text())
    reusable={"popularity":OLD_ART/"popularity_test_per_user.parquet","sasrec":OLD_ART/"sasrec_test_per_user.parquet",
              "esasrec":OLD_ART/"esasrec_test_per_user.parquet","smore":OLD_ART/"multimodal_per_user_results.parquet"}
    for name in MODELS:
        dest=ART/f"{name}_test_per_user_history3.parquet"
        if dest.exists(): per=pd.read_parquet(dest)
        elif name in reusable:
            old=pd.read_parquet(reusable[name]); key="rank"
            if name=="smore":
                # The multimodal artifact stores the base SMORE rank explicitly.
                key="generic_multimodal_rank"
                old=old.set_index("row_index").loc[target.source_row_index].reset_index()
            else:
                old=old[old.history_length>=3].copy()
                old=old.set_index("uid").loc[target.uid].reset_index()
            per=per_user_frame(target,old[key].to_numpy(),name); atomic_parquet(dest,per)
        elif name=="bpr":
            per=evaluate_bpr_selected(data,dev); atomic_parquet(dest,per)
        else:
            m=load_new_selected(name,dev,data.nitems); _,per=evaluate_new(m,name,data,"test",dev,save=dest); del m; torch.cuda.empty_cache()
        if len(per)!=len(target) or not per.uid.equals(target.uid): raise RuntimeError(f"{name} test cohort mismatch")
        md=metric_dict(per["rank"].to_numpy()); rows.append({"Model":DISPLAY[name],"model_key":name,"NDCG@10":md["ndcg_at_10"],
            "HR@10":md["hr_at_10"],"MRR@10":md["mrr_at_10"],"candidate Recall@selected_K":md[f"recall_at_{json.loads((ART/'selected_backbone.json').read_text())['candidate_k']}"]})
        parts.append(per); event("final_test","model_complete",model=name,**md)
    frame=pd.DataFrame(rows); atomic_csv(ART/"backbone_test_history3.csv",frame); atomic_csv(TABLE/"table_backbone_test.csv",frame)
    atomic_parquet(ART/"per_user_test_metrics_history3.parquet",pd.concat(parts,ignore_index=True))
    lock=verify_lock(); lock["status"]="test_evaluated_no_retuning"; lock["test_results_sha256"]=sha(ART/"backbone_test_history3.csv"); atomic_json(ART/"validation_lock.json",lock)
    set_state("final_test","complete"); event("final_test","complete")


def source_candidate_parts(split: str, selected: dict):
    name=selected["model"]
    if name=="sasrec" and Path(selected["checkpoint"]).resolve()==(OLD_ART/"checkpoints/sasrec_lr0.0003.pt").resolve():
        folder=OLD_ART/f"{split}_candidate_chunks"
        cohort=pd.read_parquet(CACHE/f"{split}_cohort_history3.parquet",columns=["source_row_index"])
        wanted=set(cohort.source_row_index.to_numpy().tolist())
        for p in sorted(folder.glob("*.npz")):
            x=np.load(p); keep=np.array([int(v) in wanted for v in x["row_index"]])
            if keep.any(): yield {k:x[k][keep] for k in x.files}
        return
    folder=CACHE/f"{split}_{name}_candidate_chunks"
    if not folder.exists():
        data=Data(); dev=device_setup(); m=load_new_selected(name,dev,data.nitems)
        evaluate_new(m,name,data,split,dev,candidates=folder); del m; torch.cuda.empty_cache()
    for p in sorted(folder.glob("*.npz")):
        x=np.load(p); yield {k:x[k] for k in x.files}


def dense_tactile():
    meta=pd.read_parquet(DATA/"item_metadata.parquet",columns=["iid","category"])
    cats=np.sort(meta.category.unique()); cmap={x:i for i,x in enumerate(cats)}; catid=meta.category.map(cmap).to_numpy(np.int16)
    p=pd.read_parquet(OLD_ART/"product_tactile_profiles.parquet"); values=np.zeros((len(meta),14),np.float32); available=np.zeros(len(meta),bool)
    values[p.iid]=p[CLASSES].to_numpy(np.float32); available[p.iid]=True
    return values,available,catid,cats


def tactile_histories(split: str):
    e=pd.read_parquet(DATA/"events.parquet",columns=["uid","iid","rating","split","timestamp"])
    e=e[e.split.isin(["train"] if split=="validation" else ["train","validation"])]
    return {int(u):(g.sort_values("timestamp").iid.to_numpy(),g.sort_values("timestamp").rating.to_numpy()) for u,g in e.groupby("uid",sort=False)}


def profiles_for(uids, hist, values, available, catid, ncat, positive, cols):
    prof=np.zeros((len(uids),ncat,len(cols)),np.float32); count=np.zeros((len(uids),ncat),np.int16); tactile=np.zeros(len(uids),np.int16)
    for j,u in enumerate(uids):
        ids,rating=hist[int(u)]; keep=available[ids]&((rating>=4) if positive else True); ids=ids[keep]; tactile[j]=len(ids)
        for c in np.unique(catid[ids]):
            g=ids[catid[ids]==c]; prof[j,c]=values[g][:,cols].mean(0); count[j,c]=len(g)
    return prof,count,tactile


def average_tie_percentile(scores: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
    masked=scores.masked_fill(~valid,-torch.inf); order=torch.argsort(masked,dim=1,descending=True,stable=True); ss=masked.gather(1,order); w=masked.shape[1]
    pos=torch.arange(w,device=scores.device)[None].expand_as(order); starts=torch.ones_like(order,dtype=torch.bool); starts[:,1:]=ss[:,1:]!=ss[:,:-1]
    first=torch.cummax(torch.where(starts,pos,torch.zeros_like(pos)),1).values; ends=torch.ones_like(order,dtype=torch.bool); ends[:,:-1]=ss[:,:-1]!=ss[:,1:]
    marker=torch.where(ends,pos,torch.full_like(pos,w)); last=torch.flip(torch.cummin(torch.flip(marker,[1]),1).values,[1]); avg=(first+last).to(scores.dtype)/2
    count=valid.sum(1); den=(count-1).clamp_min(1).to(scores.dtype); sp=(count[:,None].to(scores.dtype)-1-avg)/den[:,None]
    sp=torch.where(count[:,None]>1,sp,torch.full_like(sp,.5)); out=torch.empty_like(sp); out.scatter_(1,order,sp); return out.masked_fill(~valid,.5)


def base_percentile(raw: np.ndarray) -> np.ndarray:
    # Average-tie ascending percentile: larger base score is better.
    x=torch.as_tensor(raw,device=device_setup()); valid=torch.ones_like(x,dtype=torch.bool)
    return average_tie_percentile(x,valid).cpu().numpy()


def tactile_config(split: str, selected: dict, positive: bool, cols: list[int], alphas: list[float]):
    cohort=pd.read_parquet(CACHE/f"{split}_cohort_history3.parquet"); bysource={int(v):i for i,v in enumerate(cohort.source_row_index)}
    base=np.zeros(len(cohort),np.int32); ranks={a:np.zeros(len(cohort),np.int32) for a in alphas}; support=np.zeros(len(cohort),np.int16)
    values,available,catid,cats=dense_tactile(); hist=tactile_histories(split); dev=device_setup()
    for x in source_candidate_parts(split,selected):
        take=np.array([i for i,v in enumerate(x["row_index"]) if int(v) in bysource],np.int64)
        if not len(take): continue
        rows=np.array([bysource[int(v)] for v in x["row_index"][take]],np.int64); uid=x["uid"][take]; cand=x["candidate"][take]; target=x["target"][take]; raw=x["base_score"][take]
        up,uc,sup=profiles_for(uid,hist,values,available,catid,len(cats),positive,cols); support[rows]=sup; base[rows]=x["base_rank"][take]
        bp=torch.as_tensor(base_percentile(raw),device=dev); ci=torch.as_tensor(cand,device=dev); cc=torch.as_tensor(catid[cand],dtype=torch.long,device=dev)
        iv=torch.as_tensor(values[cand][:,:,cols],device=dev); uv=torch.as_tensor(up,device=dev); sel=uv[torch.arange(len(ci),device=dev)[:,None],cc]
        valid=torch.as_tensor(available[cand],device=dev)&(torch.as_tensor(uc,device=dev)[torch.arange(len(ci),device=dev)[:,None],cc]>0)
        tp=average_tie_percentile(F.cosine_similarity(sel,iv,dim=-1),valid); truth=torch.as_tensor(target,device=dev); where=ci==truth[:,None]; inside=where.any(1)
        for a in alphas:
            final=torch.where(valid,bp+a*(tp-bp),bp); ts=final.masked_fill(~where,-torch.inf).max(1).values
            rr=1+(final>ts[:,None]).sum(1)+((final==ts[:,None])&(ci<truth[:,None])).sum(1); out=ranks[a]
            out[rows]=x["base_rank"][take]; changed=inside.nonzero().squeeze(1); out[rows[changed.cpu().numpy()]]=rr[changed].cpu().numpy()
    if (base==0).any() or any((x==0).any() for x in ranks.values()): raise RuntimeError(f"incomplete {split} tactile ranks")
    return base,ranks,support


def tactile_reranking() -> None:
    lock=json.loads((ART/"validation_lock.json").read_text())
    if lock["status"]!="validation_locked_test_not_used_for_selection": raise RuntimeError("backbone validation lock is not closed")
    set_state("tactile_reranking","running"); event("tactile_reranking","started")
    selected=json.loads((ART/"selected_backbone.json").read_text()); rows=[]; stored={}
    for positive in (False,True):
        for names in (CLASSES,CFG["reliable_classes"]):
            cols=[CLASSES.index(x) for x in names]; base,ranks,support=tactile_config("validation",selected,positive,cols,CFG["alpha_grid"])
            profile="rating_ge_4" if positive else "all_history"
            for a in CFG["alpha_grid"]:
                m=metric_dict(ranks[a]); rows.append({"profile":profile,"classes":len(cols),"alpha":a,"NDCG@10":m["ndcg_at_10"],"HR@10":m["hr_at_10"],"MRR@10":m["mrr_at_10"]})
            stored[(profile,len(cols))]=(base,ranks,support); event("tactile_reranking","validation_config_complete",profile=profile,classes=len(cols))
    table=pd.DataFrame(rows); atomic_csv(ART/"alpha_search_history3.csv",table); atomic_csv(TABLE/"table_tactile_alpha.csv",table)
    best=max(rows,key=lambda r:(r["NDCG@10"],-r["alpha"],r["classes"]==14,r["profile"]=="all_history"))
    setting={"profile":best["profile"],"classes":best["classes"],"alpha":best["alpha"],"validation_NDCG@10":best["NDCG@10"],
             "alpha_search_sha256":sha(ART/"alpha_search_history3.csv")}; atomic_json(ART/"selected_tactile.json",setting)
    lock["status"]="all_validation_locked_test_not_used_for_selection"; lock["selected_tactile_sha256"]=sha(ART/"selected_tactile.json")
    lock["alpha_search_sha256"]=sha(ART/"alpha_search_history3.csv"); atomic_json(ART/"validation_lock.json",lock)
    set_state("tactile_reranking","complete"); event("tactile_reranking","complete",**setting)


def tactile_test() -> None:
    lock=json.loads((ART/"validation_lock.json").read_text())
    if lock["status"]!="test_evaluated_no_retuning": raise RuntimeError("final backbone test must follow the complete validation lock")
    set_state("tactile_test","running"); event("tactile_test","started")
    selected=json.loads((ART/"selected_backbone.json").read_text()); setting=json.loads((ART/"selected_tactile.json").read_text())
    positive=setting["profile"]=="rating_ge_4"; names=CLASSES if setting["classes"]==14 else CFG["reliable_classes"]; cols=[CLASSES.index(x) for x in names]
    base,ranks,support=tactile_config("test",selected,positive,cols,[setting["alpha"]]); proposed=ranks[setting["alpha"]]
    target=pd.read_parquet(CACHE/"test_cohort_history3.parquet"); bper=per_user_frame(target,base,selected["model"]); pper=per_user_frame(target,proposed,selected["model"]+"+tactile")
    values,available,catid,_=dense_tactile(); hist=tactile_histories("test"); category_support=np.zeros(len(target),np.int16)
    tactile_available_support=np.zeros(len(target),np.int16)
    for j,row in enumerate(target.itertuples()):
        ids,ratings=hist[int(row.uid)]; keep=available[ids]&((ratings>=4) if positive else True); kept=ids[keep]
        tactile_available_support[j]=len(kept); category_support[j]=int((catid[kept]==catid[int(row.iid)]).sum())
    per=target[["uid","user_id","iid","parent_asin","history_length"]].copy(); per["base_rank"]=base; per["tactile_rank"]=proposed; per["tactile_history_support"]=support
    per["tactile_available_history_count"]=tactile_available_support; per["category_local_profile_support"]=category_support
    for metric in ("ndcg_at_10","hr_at_10","mrr_at_10"): per[f"base_{metric}"]=bper[metric]; per[f"tactile_{metric}"]=pper[metric]; per[f"delta_{metric}"]=pper[metric]-bper[metric]
    atomic_parquet(ART/"per_user_tactile_test_history3.parquet",per)
    bm=metric_dict(base); pm=metric_dict(proposed); out=pd.DataFrame([
        {"Model":selected["display_name"],"NDCG@10":bm["ndcg_at_10"],"HR@10":bm["hr_at_10"],"MRR@10":bm["mrr_at_10"]},
        {"Model":selected["display_name"]+" + Tactile","NDCG@10":pm["ndcg_at_10"],"HR@10":pm["hr_at_10"],"MRR@10":pm["mrr_at_10"]},
    ]); atomic_csv(TABLE/"table_tactile_test.csv",out)
    coverage={"test_users":len(target),"mean_history_length":float(target.history_length.mean()),"tactile_profile_users":int((support>0).sum()),
              "tactile_profile_fraction":float((support>0).mean()),"mean_tactile_history_support":float(support.mean()),
              "category_local_target_profile_users":int((category_support>0).sum()),
              "category_local_target_profile_fraction":float((category_support>0).mean()),
              "mean_category_local_target_support":float(category_support.mean())}
    atomic_json(ART/"tactile_profile_coverage_history3.json",coverage)
    set_state("tactile_test","complete"); event("tactile_test","complete",**setting)


def bootstrap(delta: np.ndarray, rng: np.random.Generator) -> dict:
    n=len(delta); vals=np.empty(CFG["bootstrap_replicates"])
    for i in range(len(vals)): vals[i]=delta[rng.integers(0,n,n)].mean()
    return {"mean":float(delta.mean()),"ci95_low":float(np.quantile(vals,.025)),"ci95_high":float(np.quantile(vals,.975)),
            "replicates":len(vals),"seed":SEED,"unit":"paired user"}


def statistics() -> None:
    set_state("statistics","running"); event("statistics","started"); rng=np.random.default_rng(SEED)
    selected=json.loads((ART/"selected_backbone.json").read_text())["model"]
    allper=pd.read_parquet(ART/"per_user_test_metrics_history3.parquet")
    def vals(name): return allper[allper.model==name].set_index("uid").sort_index()
    sel=vals(selected); comparisons={}
    for other in ("popularity","sasrec"):
        o=vals(other); comparisons[f"{selected}_minus_{other}"]=bootstrap(sel.ndcg_at_10.to_numpy()-o.ndcg_at_10.to_numpy(),rng)
    atomic_json(ART/"bootstrap_backbone_history3.json",comparisons)
    per=pd.read_parquet(ART/"per_user_tactile_test_history3.parquet"); tactile={}
    for m in ("ndcg_at_10","hr_at_10","mrr_at_10"): tactile[m]=bootstrap(per[f"delta_{m}"].to_numpy(),rng)
    tactile["movement"]={"improved_users":int((per.tactile_rank<per.base_rank).sum()),"unchanged_users":int((per.tactile_rank==per.base_rank).sum()),
                         "worsened_users":int((per.tactile_rank>per.base_rank).sum()),"entered_top10":int(((per.base_rank>10)&(per.tactile_rank<=10)).sum()),
                         "left_top10":int(((per.base_rank<=10)&(per.tactile_rank>10)).sum())}
    atomic_json(ART/"bootstrap_tactile_history3.json",tactile)
    diag=[]
    for label,mask in (("3-4",per.history_length.between(3,4)),("5-9",per.history_length.between(5,9)),("10+",per.history_length>=10)):
        diag.append({"history_group":label,"users":int(mask.sum()),"base_NDCG@10":float(per.loc[mask,"base_ndcg_at_10"].mean()),
                     "tactile_NDCG@10":float(per.loc[mask,"tactile_ndcg_at_10"].mean()),"delta":float(per.loc[mask,"delta_ndcg_at_10"].mean())})
    atomic_csv(ART/"history_length_diagnostic.csv",pd.DataFrame(diag))
    set_state("statistics","complete"); event("statistics","complete")


def fmt(x): return f"{x:.8f}" if isinstance(x,(float,np.floating)) else str(x)


def md_table(frame: pd.DataFrame) -> str:
    cols=list(frame.columns); lines=["| "+" | ".join(cols)+" |","| "+" | ".join(["---"]*len(cols))+" |"]
    for row in frame.itertuples(index=False,name=None): lines.append("| "+" | ".join(fmt(x) for x in row)+" |")
    return "\n".join(lines)


def reporting() -> None:
    set_state("reporting","running"); val=pd.read_csv(ART/"backbone_validation_history3.csv"); test=pd.read_csv(ART/"backbone_test_history3.csv")
    cand=pd.read_csv(TABLE/"table_candidate_recall.csv"); alpha=pd.read_csv(ART/"alpha_search_history3.csv"); tact=pd.read_csv(TABLE/"table_tactile_test.csv")
    cohort=pd.read_csv(TABLE/"table_history_cohort.csv"); diag=pd.read_csv(ART/"history_length_diagnostic.csv"); selected=json.loads((ART/"selected_backbone.json").read_text())
    setting=json.loads((ART/"selected_tactile.json").read_text()); boot=json.loads((ART/"bootstrap_tactile_history3.json").read_text()); cover=json.loads((ART/"tactile_profile_coverage_history3.json").read_text())
    auditf=pd.read_csv(MAN/"reuse_manifest.csv")[["artifact","source","classification","reason","sha256"]]
    auditf=auditf.rename(columns={"artifact":"Artifact","source":"Source","classification":"Reused?","reason":"Reason","sha256":"Hash"})
    paper=("# 논문용 표\n\n## Backbone validation\n\n"+md_table(val.drop(columns=["model_key"]))+"\n\n## Backbone test\n\n"+md_table(test.drop(columns=["model_key"]))+
           "\n\n## Candidate recall\n\n"+md_table(cand)+"\n\n## Tactile alpha search\n\n"+md_table(alpha)+"\n\n## Tactile test\n\n"+md_table(tact)+"\n\n## History cohort\n\n"+md_table(cohort)+"\n")
    atomic_text(TABLE/"PAPER_TABLES.md",paper)
    descriptions={"Popularity":"학습 데이터에서 자주 등장한 상품을 먼저 추천합니다.","BPR-MF":"사용자와 상품의 잠재 벡터를 쌍별 순위 손실로 학습합니다.",
      "SASRec":"과거 순서를 한 방향 Transformer로 요약해 다음 상품을 예측합니다.","eSASRec":"SASRec에 LiGR 계열 구조와 다중 음성 표본 학습을 적용합니다.",
      "BERT4Rec":"과거 sequence 일부를 가리는 양방향 Transformer 학습으로 다음 상품을 예측합니다.","GRU4Rec":"GRU가 과거 순서를 순차적으로 요약해 다음 상품을 예측합니다.",
      "SMORE-derived":"FashionCLIP 이미지·텍스트 graph를 결합한 기존 SMORE 파생 기준선입니다."}
    ci=boot["ndcg_at_10"]
    report=f"""# History>=3 추천 실험 결과

## 1. 연구 질문

과거 상호작용이 없는 사용자가 다수인 전체 평균에서는 개인화 차이가 희석될 수 있다. 따라서 평가 시점 이전 interaction이 3개 이상인 사용자만 평가해 순차 추천과 촉각 개인화 효과를 직접 비교했다. 학습 데이터는 줄이지 않았다.

## 2. 데이터

- Amazon Fashion: 2,035,490 users, 825,869 parent items, 2,474,375 interactions.
- Validation history>=3: 14,731 users.
- Test history>=3: 29,991 users.

{md_table(cohort)}

## 3. 재사용한 기존 artifact

{md_table(auditf.fillna(''))}

## 4. 추천 Backbone

"""+"\n".join(f"- {k}: {v}" for k,v in descriptions.items())+f"""

## 5. Validation Backbone 결과

{md_table(val.drop(columns=['model_key']))}

## 6. 선택 Backbone

Validation NDCG@10 우선 규칙으로 **{selected['display_name']}**을 선택했다. 후보 K는 {selected['candidate_k']}이며, Recall 0.80 기준 충족 여부는 {selected['candidate_rule_satisfied']}이다.

## 7. Final Test Backbone 결과

아래 test는 모델 선택에 사용하지 않은 최종 평가용 데이터이며 모든 모델이 같은 29,991명이다.

{md_table(test.drop(columns=['model_key']))}

## 8. Candidate Recall

{md_table(cand)}

실제 다음 상품이 초기 추천 후보 안에 충분히 포함되지 않는 문제가 남아 있으며, K는 validation 규칙으로만 고정했다.

## 9. Tactile Profile

평가 이전 history의 category-local Last2 14차원 평균을 사용했다. Test에서 tactile inference가 가능한 history로 profile이 생성된 사용자는 {cover['tactile_profile_users']:,}/{cover['test_users']:,}명({cover['tactile_profile_fraction']:.2%})이다. 실제 test target category와 같은 category의 과거 tactile support가 있는 사용자는 {cover['category_local_target_profile_users']:,}명({cover['category_local_target_profile_fraction']:.2%})이고 평균 support는 {cover['mean_category_local_target_support']:.3f}개다. 과거 interaction은 선호의 직접 증거가 아니라 noisy proxy이다.

## 10. Alpha Search

선택값: profile={setting['profile']}, classes={setting['classes']}, alpha={setting['alpha']}.

{md_table(alpha)}

## 11. Final Strong vs Strong + Tactile

{md_table(tact)}

- paired NDCG@10 delta: {ci['mean']:.8f}
- paired bootstrap 95% CI: [{ci['ci95_low']:.8f}, {ci['ci95_high']:.8f}]
- improved / unchanged / worsened: {boot['movement']['improved_users']} / {boot['movement']['unchanged_users']} / {boot['movement']['worsened_users']}
- entered / left Top10: {boot['movement']['entered_top10']} / {boot['movement']['left_top10']}

## 12. History 길이별 진단

{md_table(diag)}

이 구간 결과는 사후 진단이며 모델이나 alpha 선택에 사용하지 않았다.

## 13. 기존 실험과 달라진 점

기존 Experiment 16은 all-user가 주 평가 집단이었다. 이번 실험은 validation 시 train history, test 시 train+선행 validation history가 3개 이상인 사용자만 평가했다. 서로 다른 평가 population의 수치를 직접적인 성능 향상으로 해석하지 않는다.

실행 중 제공된 번호 순서(Step 10 backbone test, Step 12 tactile validation)를 먼저 따른 예비 backbone test pass가 있었다. 더 엄격한 “모든 validation 선택 후 test” 원칙을 적용하기 위해 이 pass의 산출물을 삭제하지 않고 `artifacts/quarantined_pre_alpha_test/`에 격리했다. 예비 test 값은 선택 코드의 입력으로 사용되지 않았으며, alpha=0을 포함한 모든 validation 결정을 hash로 고정한 뒤 최종 backbone/tactile test를 다시 실행했다. 따라서 최종 표는 두 번째 pass만 사용하지만, 완전히 미열람된 confirmatory test였다고 주장하지 않는다.

## 14. 결과 해석

이 결과는 충분한 과거 interaction이 있는 Amazon Fashion 사용자에서 모델 간 다음-item 순위 차이와 Last2 후처리 효과를 보여준다. 직접적인 촉감 만족도, 구매 의도, 다른 category나 플랫폼으로의 일반화를 증명하지 않는다.

## 15. 논문에 사용할 수 있는 핵심 수치

- Validation users: 14,731; Test users: 29,991.
- Selected backbone: {selected['display_name']}.
- Candidate K: {selected['candidate_k']}.
- Tactile alpha: {setting['alpha']} ({setting['profile']}, {setting['classes']} classes).
- Tactile NDCG@10 delta: {ci['mean']:.8f}, 95% CI [{ci['ci95_low']:.8f}, {ci['ci95_high']:.8f}].

## 16. Limitations

- 0-core split은 대부분 사용자의 학습 history가 매우 짧으며 history>=3 집단은 전체 사용자를 대표하지 않는다.
- 전체 catalog에서 train evidence가 없는 상품이 많아 추천 후보 recall이 낮다.
- 리뷰 interaction은 click이나 purchase와 동일하지 않으며 촉각 선호의 직접 label이 아니다.
- SMORE-derived는 기존 FashionCLIP 이미지·텍스트 graph adapter이며 원 논문의 완전한 재현이라고 주장하지 않는다.
- BERT4Rec/GRU4Rec은 현재 저장소 안의 투명한 최소 구현이고 동일 탐색 예산을 썼지만 모든 공개 구현의 세부 최적화를 포함하지 않는다.
"""
    atomic_text(ROOT/"RESULTS.md",report); set_state("reporting","complete"); event("reporting","complete")


def sanity_checks() -> None:
    set_state("sanity_checks","running"); checks={}
    checks["experiment16_unchanged"] = json.loads((MAN/"experiment16_stat_snapshot.json").read_text()) == exp16_snapshot()
    val=pd.read_csv(ART/"backbone_validation_history3.csv"); test=pd.read_csv(ART/"backbone_test_history3.csv"); per=pd.read_parquet(ART/"per_user_test_metrics_history3.parquet")
    checks["lightgcn_excluded"]="lightgcn" not in set(val.model_key)|set(test.model_key)
    checks["bert4rec_executed"]="bert4rec" in set(test.model_key); checks["gru4rec_executed"]="gru4rec" in set(test.model_key)
    counts=per.groupby("model").size().to_dict(); checks["same_test_cohort_all_models"]=all(counts.get(m)==29991 for m in MODELS)
    checks["popularity_same_cohort"]=counts.get("popularity")==29991; checks["test_not_used_for_selection"]=json.loads((ART/"validation_lock.json").read_text())["test_tuning_forbidden"]
    checks["last2_not_retrained"]=not any(CKPT.glob("*last2*")); checks["last2_cache_reused"]=sha(OLD_ART/"product_tactile_profiles.parquet")=="a56b834afa985b6bb3a44e5e4cb9dc553693d2b66202c284283b20c945190133"
    checks["seen_filter_documented"]= "이전에 본 상품" in (ROOT/"PROTOCOL.md").read_text(); checks["candidate_k_validation_fixed"]=(ART/"selected_backbone.json").exists()
    checks["alpha_validation_fixed"]=(ART/"selected_tactile.json").exists(); tper=pd.read_parquet(ART/"per_user_tactile_test_history3.parquet")
    checks["per_user_count_matches"]=len(tper)==29991; numeric=per.select_dtypes(include=[np.number])
    checks["no_nan_inf"]=np.isfinite(numeric.to_numpy()).all(); checks["metric_ranges_valid"]=all(((per[c]>=0)&(per[c]<=1)).all() for c in ["ndcg_at_10","hr_at_10","mrr_at_10"])
    required=[ART/"backbone_validation_history3.csv",ART/"backbone_test_history3.csv",ART/"selected_backbone.json",ART/"alpha_search_history3.csv",
              ART/"bootstrap_backbone_history3.json",ART/"bootstrap_tactile_history3.json",ROOT/"RESULTS.md",TABLE/"PAPER_TABLES.md"]
    checks["outputs_exist"]=all(p.exists() for p in required)
    checks["pre_alpha_test_outputs_quarantined"]=(ART/"quarantined_pre_alpha_test/backbone_test_history3.csv").exists()
    checks["final_test_after_complete_validation_lock"]=json.loads((ART/"validation_lock.json").read_text()).get("selected_tactile_sha256")==sha(ART/"selected_tactile.json")
    checks={k:bool(v) for k,v in checks.items()}; checks["all_pass"]=all(checks.values())
    atomic_json(ART/"sanity_checks.json",checks)
    if not checks["all_pass"]: raise RuntimeError(f"sanity checks failed: {[k for k,v in checks.items() if not v]}")
    set_state("sanity_checks","complete"); event("sanity_checks","complete")


def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--resume",action="store_true"); args=p.parse_args()
    for d in (ART,CKPT,CACHE,LOG,MAN,TABLE): d.mkdir(parents=True,exist_ok=True)
    stages=[("audit",audit),("cohort_build",build_cohorts),("existing_backbones_validation",existing_validation),
            ("bert4rec",lambda:train_new("bert4rec")),("gru4rec",lambda:train_new("gru4rec")),
            ("backbone_selection",select_backbone),("tactile_reranking",tactile_reranking),("final_test",final_test),("tactile_test",tactile_test),
            ("statistics",statistics),("reporting",reporting),("sanity_checks",sanity_checks)]
    for name,fn in stages:
        if state().get(name)=="complete": continue
        try: fn()
        except Exception as e:
            set_state(name,"failed"); event(name,"failed",error=repr(e)); raise


if __name__=="__main__": main()
