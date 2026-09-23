from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch
import torch.nn as nn
import torch.nn.functional as F

from common import DATA, EXP16, ROOT, SEED, metric_dict


def setup(seed: int = SEED) -> str:
    torch.set_num_threads(8)
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.backends.cuda.matmul.allow_tf32 = False
    return "cuda" if torch.cuda.is_available() else "cpu"


def sparse_mx_to_torch(sparse_mx: sp.spmatrix) -> torch.Tensor:
    sparse_mx = sparse_mx.tocoo().astype(np.float32)
    indices = torch.from_numpy(np.vstack((sparse_mx.row, sparse_mx.col)).astype(np.int64))
    values = torch.from_numpy(sparse_mx.data)
    return torch.sparse_coo_tensor(indices, values, torch.Size(sparse_mx.shape)).coalesce()


class RecData20:
    def __init__(self):
        self.catalog = pd.read_parquet(EXP16 / "data/catalog.parquet")
        self.nitems = len(self.catalog)
        self.train = pd.read_parquet(DATA / "train_events.parquet").copy()
        self.validation_events = pd.read_parquet(DATA / "validation_events.parquet").copy()
        self.train_uids = np.sort(self.train.uid.unique())
        self.uid_to_train = {int(u): j for j, u in enumerate(self.train_uids)}
        self.train["local_uid"] = self.train.uid.map(self.uid_to_train).astype("int64")
        self.hist = {int(u): g.iid.to_numpy(dtype=np.int64) for u, g in self.train.groupby("uid", sort=False)}
        self.pop_order = np.lexsort((self.catalog.iid.to_numpy(), -self.catalog.train_count.to_numpy()))
        self.pop_rank = np.empty(self.nitems, dtype=np.int64)
        self.pop_rank[self.pop_order] = np.arange(1, self.nitems + 1)
        self.cold = self.catalog.train_count.to_numpy() == 0

    def histories(self, split: str) -> dict[int, np.ndarray]:
        if split == "validation":
            return self.hist
        if split != "test":
            raise ValueError(split)
        h = {u: seq.copy() for u, seq in self.hist.items()}
        for row in self.validation_events.itertuples():
            h[int(row.uid)] = np.append(h.get(int(row.uid), np.array([], dtype=np.int64)), int(row.iid))
        return h

    def normalized_graphs(self) -> tuple[torch.Tensor, torch.Tensor]:
        nusers = len(self.train_uids)
        user = self.train.local_uid.to_numpy(dtype=np.int64)
        item = self.train.iid.to_numpy(dtype=np.int64)
        src = np.concatenate([user, nusers + item])
        dst = np.concatenate([nusers + item, user])
        deg = np.bincount(src, minlength=nusers + self.nitems).astype(np.float32)
        norm_value = 1.0 / np.sqrt(np.maximum(deg[src], 1e-12) * np.maximum(deg[dst], 1e-12))
        norm = sp.coo_matrix((norm_value.astype(np.float32), (src, dst)), shape=(nusers + self.nitems, nusers + self.nitems))
        r_value = 1.0 / np.sqrt(np.maximum(deg[user], 1e-12) * np.maximum(deg[nusers + item], 1e-12))
        r_norm = sp.coo_matrix((r_value.astype(np.float32), (user, item)), shape=(nusers, self.nitems))
        return sparse_mx_to_torch(norm), sparse_mx_to_torch(r_norm)


def max_pool_sparse(a: torch.Tensor, b: torch.Tensor, device: str) -> torch.Tensor:
    a = a.coalesce().to(device)
    b = b.coalesce().to(device)
    ai, av = a.indices(), a.values()
    bi, bv = b.indices(), b.values()
    combined = torch.cat([ai, bi], dim=1)
    unique, inverse = torch.unique(combined, dim=1, return_inverse=True)
    values_a = torch.full((unique.size(1),), float("-inf"), device=device)
    values_b = torch.full((unique.size(1),), float("-inf"), device=device)
    values_a[inverse[: ai.size(1)]] = av
    values_b[inverse[ai.size(1) :]] = bv
    values = torch.max(torch.stack([values_a, values_b]), dim=0).values
    return torch.sparse_coo_tensor(unique, values, a.size(), device=device).coalesce()


class Exp20Model(nn.Module):
    def __init__(self, variant: str, d: RecData20, cfg: dict, device: str):
        super().__init__()
        self.variant = variant
        self.n_users = len(d.train_uids)
        self.n_items = d.nitems
        self.dim = int(cfg["shared_training"]["embedding_dimension"])
        self.n_ui_layers = int(cfg["shared_training"]["user_item_graph_layers"])
        self.n_layers = int(cfg["shared_training"]["modality_graph_layers"])
        self.dropout = nn.Dropout(float(cfg["shared_training"]["dropout"]))
        self.cl_loss = float(cfg["shared_training"]["contrastive_loss_weight"])
        self.temperature = float(cfg["shared_training"]["contrastive_temperature"])
        self.batch_size = int(cfg.get("batch_size_for_regularizer", 512))
        self.use_generic = variant in {"I_VX", "I_VX_T", "I_VX_T_SHUFFLE"}
        self.use_tactile = variant in {"I_T", "I_VX_T", "I_VX_T_SHUFFLE"}
        self.tactile_scale = 1.0 / 3.0 if variant in {"I_VX_T", "I_VX_T_SHUFFLE"} else 1.0
        self.user_embedding = nn.Embedding(self.n_users, self.dim)
        self.item_id_embedding = nn.Embedding(self.n_items, self.dim)
        nn.init.xavier_uniform_(self.user_embedding.weight)
        nn.init.xavier_uniform_(self.item_id_embedding.weight)
        self.norm_adj, self.r_norm = d.normalized_graphs()
        self.norm_adj = self.norm_adj.float().to(device)
        self.r_norm = self.r_norm.float().to(device)
        if self.use_generic:
            image = torch.from_numpy(np.asarray(np.load(EXP16 / "data/smore/image_feat.npy", mmap_mode="r"), dtype=np.float32))
            text = torch.from_numpy(np.asarray(np.load(EXP16 / "data/smore/text_feat.npy", mmap_mode="r"), dtype=np.float32))
            self.image_embedding = nn.Embedding.from_pretrained(image, freeze=False)
            self.text_embedding = nn.Embedding.from_pretrained(text, freeze=False)
            self.image_graph = torch.load(EXP16 / "data/smore/image_adj_40_True.pt", map_location=device).coalesce().float().to(device)
            self.text_graph = torch.load(EXP16 / "data/smore/text_adj_10_True.pt", map_location=device).coalesce().float().to(device)
            self.fusion_graph = max_pool_sparse(self.image_graph, self.text_graph, device)
            self.image_trs = nn.Linear(image.shape[1], self.dim)
            self.text_trs = nn.Linear(text.shape[1], self.dim)
            self.query_image = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Tanh(), nn.Linear(self.dim, self.dim, bias=False))
            self.query_text = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Tanh(), nn.Linear(self.dim, self.dim, bias=False))
            self.gate_image = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
            self.gate_text = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
            self.gate_fusion = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
            self.prefer_image = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
            self.prefer_text = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
            self.prefer_fusion = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
            self.image_complex_weight = nn.Parameter(torch.randn(1, self.dim // 2 + 1, 2, dtype=torch.float32))
            self.text_complex_weight = nn.Parameter(torch.randn(1, self.dim // 2 + 1, 2, dtype=torch.float32))
            self.fusion_complex_weight = nn.Parameter(torch.randn(1, self.dim // 2 + 1, 2, dtype=torch.float32))
        if self.use_tactile:
            feat_name = "tactile_feat_14_shuffled.npy" if variant == "I_VX_T_SHUFFLE" else "tactile_feat_14.npy"
            tactile = torch.from_numpy(np.load(DATA / feat_name).astype("float32"))
            available = torch.from_numpy(np.load(DATA / "tactile_available.npy").astype(bool))
            self.tactile_embedding = nn.Embedding.from_pretrained(tactile, freeze=True)
            self.register_buffer("tactile_available", available)
            self.tactile_graph = torch.load(DATA / "tactile_adj_40_True.pt", map_location=device).coalesce().float().to(device)
            self.tactile_trs = nn.Linear(tactile.shape[1], self.dim, bias=False)
            self.gate_tactile = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
            self.prefer_tactile = nn.Sequential(nn.Linear(self.dim, self.dim), nn.Sigmoid())
        self.softmax = nn.Softmax(dim=-1)

    def spectrum(self, image: torch.Tensor, text: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        image_fft = torch.fft.rfft(image, dim=1, norm="ortho")
        text_fft = torch.fft.rfft(text, dim=1, norm="ortho")
        iw = torch.view_as_complex(self.image_complex_weight)
        tw = torch.view_as_complex(self.text_complex_weight)
        fw = torch.view_as_complex(self.fusion_complex_weight)
        image_conv = torch.fft.irfft(image_fft * iw, n=image.shape[1], dim=1, norm="ortho")
        text_conv = torch.fft.irfft(text_fft * tw, n=text.shape[1], dim=1, norm="ortho")
        fusion_conv = torch.fft.irfft(text_fft * image_fft * fw, n=text.shape[1], dim=1, norm="ortho")
        return image_conv, text_conv, fusion_conv

    def content_view(self) -> torch.Tensor:
        item = self.item_id_embedding.weight
        user = self.user_embedding.weight
        ego = torch.cat([user, item], dim=0)
        all_embeddings = [ego]
        for _ in range(self.n_ui_layers):
            ego = torch.sparse.mm(self.norm_adj, ego)
            all_embeddings.append(ego)
        return torch.stack(all_embeddings, dim=1).mean(dim=1)

    def generic_side(self, content: torch.Tensor) -> torch.Tensor:
        image, text = self.image_trs(self.image_embedding.weight), self.text_trs(self.text_embedding.weight)
        image_conv, text_conv, fusion_conv = self.spectrum(image, text)
        image_item = self.item_id_embedding.weight * self.gate_image(image_conv)
        text_item = self.item_id_embedding.weight * self.gate_text(text_conv)
        fusion_item = self.item_id_embedding.weight * self.gate_fusion(fusion_conv)
        for _ in range(self.n_layers):
            image_item = torch.sparse.mm(self.image_graph, image_item)
            text_item = torch.sparse.mm(self.text_graph, text_item)
            fusion_item = torch.sparse.mm(self.fusion_graph, fusion_item)
        image_embeds = torch.cat([torch.sparse.mm(self.r_norm, image_item), image_item], dim=0)
        text_embeds = torch.cat([torch.sparse.mm(self.r_norm, text_item), text_item], dim=0)
        fusion_embeds = torch.cat([torch.sparse.mm(self.r_norm, fusion_item), fusion_item], dim=0)
        image_att = self.softmax(self.query_image(fusion_embeds)) * image_embeds
        text_att = self.softmax(self.query_text(fusion_embeds)) * text_embeds
        image_att = self.dropout(self.prefer_image(content)) * image_att
        text_att = self.dropout(self.prefer_text(content)) * text_att
        fusion_embeds = self.dropout(self.prefer_fusion(content)) * fusion_embeds
        return torch.mean(torch.stack([image_att, text_att, fusion_embeds]), dim=0)

    def tactile_side(self, content: torch.Tensor) -> torch.Tensor:
        tactile_item = self.tactile_trs(self.tactile_embedding.weight)
        tactile_item = self.item_id_embedding.weight * self.gate_tactile(tactile_item)
        tactile_item = tactile_item * self.tactile_available.to(tactile_item.device)[:, None]
        for _ in range(self.n_layers):
            tactile_item = torch.sparse.mm(self.tactile_graph, tactile_item)
        tactile_embeds = torch.cat([torch.sparse.mm(self.r_norm, tactile_item), tactile_item], dim=0)
        return self.dropout(self.prefer_tactile(content)) * tactile_embeds

    def forward(self, train: bool = False):
        content = self.content_view()
        side_terms = []
        if self.use_generic:
            side_terms.append(self.generic_side(content))
        if self.use_tactile:
            side_terms.append(self.tactile_scale * self.tactile_side(content))
        side = torch.zeros_like(content) if not side_terms else torch.stack(side_terms).sum(dim=0)
        all_embeds = content + side
        users, items = torch.split(all_embeds, [self.n_users, self.n_items], dim=0)
        if train:
            return users, items, side, content
        return users, items

    def bpr_loss(self, users: torch.Tensor, pos_items: torch.Tensor, neg_items: torch.Tensor) -> torch.Tensor:
        pos = torch.sum(users * pos_items, dim=1)
        neg = torch.sum(users * neg_items, dim=1)
        reg = 0.5 * (users.square().sum() + pos_items.square().sum() + neg_items.square().sum()) / max(1, len(users))
        return -F.logsigmoid(pos - neg).mean(), reg

    def info_nce(self, view1: torch.Tensor, view2: torch.Tensor) -> torch.Tensor:
        view1 = F.normalize(view1, dim=1)
        view2 = F.normalize(view2, dim=1)
        pos = torch.exp((view1 * view2).sum(dim=-1) / self.temperature)
        total = torch.exp((view1 @ view2.T) / self.temperature).sum(dim=1)
        return -torch.log(pos / total).mean()

    def calculate_loss(self, users: torch.Tensor, pos: torch.Tensor, neg: torch.Tensor, reg_weight: float, cl_cap: int) -> torch.Tensor:
        ue, ie, side, content = self.forward(train=True)
        mf, reg = self.bpr_loss(ue[users], ie[pos], ie[neg])
        loss = mf + reg_weight * reg
        if self.use_generic or self.use_tactile:
            cap = min(int(cl_cap), len(users))
            su, si = torch.split(side, [self.n_users, self.n_items], dim=0)
            cu, ci = torch.split(content, [self.n_users, self.n_items], dim=0)
            loss = loss + self.cl_loss * (self.info_nce(si[pos[:cap]], ci[pos[:cap]]) + self.info_nce(su[users[:cap]], cu[users[:cap]]))
        return loss


def make_model(variant: str, d: RecData20, cfg: dict, device: str) -> Exp20Model:
    valid = {v["id"] for v in cfg["variants"]}
    if variant not in valid:
        raise ValueError(f"unknown variant {variant}")
    return Exp20Model(variant, d, cfg, device)


def pop_rank(d: RecData20, hist: dict[int, np.ndarray], uid: int, target: int) -> int:
    seen = hist.get(int(uid), np.array([], dtype=np.int64))
    if len(seen) and target in set(map(int, seen)):
        raise RuntimeError("target leaked into history")
    return int(d.pop_rank[target] - np.sum(d.pop_rank[seen] < d.pop_rank[target]))


@torch.no_grad()
def evaluate_exact(model: Exp20Model, d: RecData20, split: str, device: str, batch_size: int = 256, save_to=None):
    if split == "validation":
        targets = pd.read_parquet(DATA / "validation_targets.parquet")
    elif split == "test":
        from common import require_state

        require_state("exploratory_test_opened_no_retuning", "complete_locked_posthoc_exploratory")
        targets = pd.read_parquet(EXP16 / "data/test_targets.parquet")
    else:
        raise ValueError(split)
    hist = d.histories(split)
    ranks = np.empty(len(targets), dtype=np.int32)
    usable = []
    for j, row in enumerate(targets.itertuples()):
        if int(row.uid) in d.uid_to_train:
            usable.append(j)
        else:
            ranks[j] = pop_rank(d, hist, int(row.uid), int(row.iid))
    users_all, items = model.forward(train=False)
    ids = torch.arange(d.nitems, device=device)
    for start in range(0, len(usable), batch_size):
        idx = usable[start : start + batch_size]
        batch = targets.iloc[idx]
        loc = torch.tensor([d.uid_to_train[int(u)] for u in batch.uid.to_numpy()], dtype=torch.long, device=device)
        scores = users_all[loc] @ items.T
        rows = []
        cols = []
        for j, u in enumerate(batch.uid.to_numpy()):
            seq = hist.get(int(u), [])
            rows.extend([j] * len(seq))
            cols.extend(seq)
        if rows:
            scores[torch.tensor(rows, device=device), torch.tensor(cols, device=device)] = -torch.inf
        truth = torch.tensor(batch.iid.to_numpy(), dtype=torch.long, device=device)
        ts = scores[torch.arange(len(idx), device=device), truth]
        if not torch.isfinite(ts).all():
            raise FloatingPointError("non-finite target score")
        rr = 1 + (scores > ts[:, None]).sum(-1) + ((scores == ts[:, None]) & (ids[None, :] < truth[:, None])).sum(-1)
        ranks[idx] = rr.cpu().numpy().astype(np.int32)
    out = targets.copy()
    out["rank"] = ranks
    out["variant"] = model.variant
    if save_to is not None:
        tmp = save_to.with_suffix(save_to.suffix + ".tmp")
        out.to_parquet(tmp, index=False)
        tmp.replace(save_to)
    result = {"all_official_targets": metric_dict(ranks), "personalized_users": int(len(usable))}
    if "train_history_length" in targets:
        for k in (1, 3, 5):
            mask = targets.train_history_length.to_numpy() >= k
            result[f"train_history_ge_{k}"] = metric_dict(ranks[mask])
    return result, out


def sample_negatives(rng: np.random.Generator, uids: np.ndarray, d: RecData20) -> np.ndarray:
    neg = rng.integers(0, d.nitems, size=len(uids), dtype=np.int64)
    for j, u in enumerate(uids):
        seen = set(map(int, d.hist[int(u)]))
        while int(neg[j]) in seen:
            neg[j] = rng.integers(0, d.nitems)
    return neg
