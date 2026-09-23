#!/usr/bin/env python3
"""Recommendation backbones for Exp24.

``SASRec`` is copied verbatim from experiments/16_strong_recommender_tactile/models.py
so that the exp16b checkpoint loads without architectural drift and R0 reproduces
exp17b exactly.  Everything else is new and builds on that same block.
"""
from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F


class SASBlock(nn.Module):
    """Verbatim from exp16b models.py."""

    def __init__(self, dim, heads, dropout):
        super().__init__()
        self.attn = nn.MultiheadAttention(dim, heads, dropout=dropout, batch_first=True)
        self.ln1 = nn.LayerNorm(dim)
        self.ln2 = nn.LayerNorm(dim)
        self.ff = nn.Sequential(nn.Linear(dim, dim), nn.ReLU(), nn.Dropout(dropout),
                                nn.Linear(dim, dim), nn.Dropout(dropout))

    def forward(self, x, padding):
        q = self.ln1(x)
        causal = torch.triu(torch.ones(x.shape[1], x.shape[1], device=x.device,
                                       dtype=torch.bool), 1)
        x = q + self.attn(q, x, x, attn_mask=causal, need_weights=False)[0]
        x = self.ln2(x)
        x = x + self.ff(x)
        return x.masked_fill(padding.unsqueeze(-1), 0)


class SASRec(nn.Module):
    """Verbatim from exp16b models.py; 0 is padding, catalog ids shifted by one."""

    def __init__(self, nitems, dim=64, layers=2, heads=2, maxlen=50, dropout=.2, **kwargs):
        super().__init__()
        self.dim = dim
        self.maxlen = maxlen
        self.item = nn.Embedding(nitems + 1, dim, padding_idx=0)
        self.pos = nn.Embedding(maxlen, dim)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList([SASBlock(dim, heads, dropout) for _ in range(layers)])
        self.norm = nn.LayerNorm(dim)
        nn.init.normal_(self.item.weight, std=.02)
        with torch.no_grad():
            self.item.weight[0].zero_()

    # --- hook that the tactile variants override -----------------------------
    def item_embedding(self, ids):
        return self.item(ids)

    def forward(self, seq):
        pad = seq == 0
        x = self.drop(self.item_embedding(seq) * math.sqrt(self.dim)
                      + self.pos(torch.arange(seq.shape[1], device=seq.device)))
        x = x.masked_fill(pad.unsqueeze(-1), 0)
        for block in self.blocks:
            x = block(x, pad)
        return self.norm(x)

    def loss(self, seq, pos, neg):
        z = self(seq)
        valid = pos > 0
        a = (z * self.item_embedding(pos)).sum(-1)[valid]
        b = (z * self.item_embedding(neg)).sum(-1)[valid]
        return F.softplus(-a).mean() + F.softplus(b).mean()

    def query(self, seq):
        return self(seq)[:, -1]

    def catalog_matrix(self, chunk=None):
        """Scoring matrix for the whole catalog, excluding the padding row."""
        return self.item.weight[1:]


# ---------------------------------------------------------------- R3 variants
class TactileSASRec(SASRec):
    """R3: tactile enters at the item-embedding layer, before the Transformer.

    fusion:
      residual_gate : e' = LayerNorm(e + g * t),  g = sigmoid(MLP([e; t]))
      concat_proj   : e' = LayerNorm(W [e; t])
      film          : e' = LayerNorm(gamma(t) * e + beta(t))
      shuffle       : identical capacity to residual_gate, but the tactile table
                      is permuted deterministically -- the exp20-style control
                      that separates "tactile information" from "extra parameters"
    """

    def __init__(self, nitems, tactile, fusion="residual_gate", tactile_dim=14,
                 dim=64, **kwargs):
        super().__init__(nitems, dim=dim, **kwargs)
        self.fusion = fusion
        # row 0 is padding, so prepend a zero row to align with the shifted ids
        table = torch.cat([torch.zeros(1, tactile_dim), tactile], dim=0)
        self.register_buffer("tactile_table", table)
        self.project = nn.Sequential(nn.Linear(tactile_dim, dim), nn.GELU(),
                                     nn.Linear(dim, dim))
        self.fuse_norm = nn.LayerNorm(dim)
        # Scale fix.  nn.Embedding here is initialised with std 0.02, but a
        # LayerNorm output has unit variance -- 50x larger.  Left alone, R3 would
        # feed the Transformer activations 50x bigger than R0 does and would be
        # scored on a different magnitude, so any R3-vs-R0 difference would
        # confound "tactile information" with "different effective learning rate
        # and logit scale".  Initialising the LayerNorm gain to the embedding std
        # makes R3 start numerically where R0 starts; the gain stays learnable so
        # the model can still move away from it.
        with torch.no_grad():
            self.fuse_norm.weight.fill_(0.02)
        if fusion in ("residual_gate", "shuffle"):
            self.gate = nn.Sequential(nn.Linear(2 * dim, dim), nn.GELU(), nn.Linear(dim, 1))
        elif fusion == "concat_proj":
            self.combine = nn.Linear(2 * dim, dim)
        elif fusion == "film":
            self.film = nn.Linear(dim, 2 * dim)
        else:
            raise ValueError(fusion)

    def tactile_of(self, ids):
        return self.tactile_table[ids]

    def item_embedding(self, ids):
        e = self.item(ids)
        t = self.project(self.tactile_of(ids))
        if self.fusion in ("residual_gate", "shuffle"):
            g = torch.sigmoid(self.gate(torch.cat([e, t], dim=-1)))
            fused = self.fuse_norm(e + g * t)
        elif self.fusion == "concat_proj":
            fused = self.fuse_norm(self.combine(torch.cat([e, t], dim=-1)))
        else:
            gamma, beta = self.film(t).chunk(2, dim=-1)
            fused = self.fuse_norm((1.0 + gamma) * e + beta)
        return fused.masked_fill((ids == 0).unsqueeze(-1), 0)

    @torch.no_grad()
    def catalog_matrix(self, chunk=100_000):
        ids = torch.arange(1, self.item.num_embeddings, device=self.item.weight.device)
        return torch.cat([self.item_embedding(ids[i:i + chunk])
                          for i in range(0, ids.numel(), chunk)])

    @torch.no_grad()
    def gate_values(self, ids):
        if self.fusion not in ("residual_gate", "shuffle"):
            return None
        e = self.item(ids)
        t = self.project(self.tactile_of(ids))
        return torch.sigmoid(self.gate(torch.cat([e, t], dim=-1))).squeeze(-1)


# ------------------------------------------------------------- R4 multi-task
class MultiTaskSASRec(SASRec):
    """R4: the sequence encoder also predicts the next item's tactile vector.

    The auxiliary target is the *image-derived* Last2 vector of the next item, so
    no review-period information enters the loss.
    """

    def __init__(self, nitems, tactile, tactile_dim=14, dim=64, lambda_tactile=0.1, **kwargs):
        super().__init__(nitems, dim=dim, **kwargs)
        table = torch.cat([torch.zeros(1, tactile_dim), tactile], dim=0)
        self.register_buffer("tactile_table", table)
        self.tactile_head = nn.Sequential(nn.Linear(dim, dim), nn.GELU(),
                                          nn.Linear(dim, tactile_dim))
        self.lambda_tactile = lambda_tactile

    def loss(self, seq, pos, neg):
        z = self(seq)
        valid = pos > 0
        a = (z * self.item_embedding(pos)).sum(-1)[valid]
        b = (z * self.item_embedding(neg)).sum(-1)[valid]
        recommendation = F.softplus(-a).mean() + F.softplus(b).mean()
        target = self.tactile_table[pos][valid]
        predicted = torch.sigmoid(self.tactile_head(z[valid]))
        auxiliary = F.binary_cross_entropy(predicted, target)
        return recommendation + self.lambda_tactile * auxiliary


# ----------------------------------------------------------------- R6 experts
class MixtureSASRec(SASRec):
    """R6: a general expert and a tactile-sequence expert, combined by a router.

    The router sees the user's own context, so how much tactile is used is decided
    per user rather than globally.
    """

    def __init__(self, nitems, tactile, tactile_dim=14, dim=64, experts=2, **kwargs):
        super().__init__(nitems, dim=dim, **kwargs)
        table = torch.cat([torch.zeros(1, tactile_dim), tactile], dim=0)
        self.register_buffer("tactile_table", table)
        self.n_experts = experts
        self.tactile_encoder = nn.GRU(tactile_dim, dim, batch_first=True)
        self.tactile_norm = nn.LayerNorm(dim)
        self.router = nn.Sequential(nn.Linear(2 * dim, dim), nn.GELU(),
                                    nn.Linear(dim, experts))
        self.blend = nn.Linear(dim, dim)

    def expert_outputs(self, seq):
        general = self(seq)[:, -1]
        tactile_sequence = self.tactile_table[seq]
        encoded, _ = self.tactile_encoder(tactile_sequence)
        tactile = self.tactile_norm(encoded[:, -1])
        return general, tactile

    def query(self, seq):
        general, tactile = self.expert_outputs(seq)
        weights = torch.softmax(self.router(torch.cat([general, tactile], dim=-1)), dim=-1)
        stacked = torch.stack([general, self.blend(tactile)], dim=1)[:, :self.n_experts]
        return (weights.unsqueeze(-1) * stacked).sum(1)

    def loss(self, seq, pos, neg):
        z = self.query(seq)
        last = pos[:, -1] if pos.ndim > 1 else pos
        last_neg = neg[:, -1] if neg.ndim > 1 else neg
        valid = last > 0
        a = (z * self.item_embedding(last)).sum(-1)[valid]
        b = (z * self.item_embedding(last_neg)).sum(-1)[valid]
        return F.softplus(-a).mean() + F.softplus(b).mean()

    @torch.no_grad()
    def router_weights(self, seq):
        general, tactile = self.expert_outputs(seq)
        return torch.softmax(self.router(torch.cat([general, tactile], dim=-1)), dim=-1)


# ------------------------------------------------------- R2 / R7 small heads
class TactileGate(nn.Module):
    """R2: per (user, item) weight on the tactile term, replacing the global alpha.

    Initialised so that g ~ 0 at step 0, which makes the whole method reduce
    *exactly* to the R0 ordering before any training happens.  That matters: R0 is
    inside this model's hypothesis space, so if the trained gate cannot beat R0 on
    validation we have learned something about tactile signal rather than about a
    badly initialised head.
    """

    def __init__(self, n_features, hidden=32, init_bias=-6.0):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_features, hidden), nn.GELU(),
                                 nn.Linear(hidden, hidden), nn.GELU(),
                                 nn.Linear(hidden, 1))
        with torch.no_grad():
            self.net[-1].weight.zero_()
            self.net[-1].bias.fill_(init_bias)

    def forward(self, features):
        return torch.sigmoid(self.net(features)).squeeze(-1)


class Reranker(nn.Module):
    """R7: learning-to-rank head over the union of SASRec and tactile candidates.

    Scores as ``base_percentile * scale + residual(features)`` with the residual
    head zero-initialised, so at step 0 the reranker reproduces the backbone
    ordering restricted to the union.  Any departure from the baseline is then
    something the model actually learned.
    """

    def __init__(self, n_features, hidden=64, base_index=0, scale=20.0):
        super().__init__()
        self.base_index = base_index
        self.scale = scale
        self.net = nn.Sequential(nn.Linear(n_features, hidden), nn.GELU(),
                                 nn.Linear(hidden, hidden), nn.GELU(),
                                 nn.Linear(hidden, 1))
        with torch.no_grad():
            self.net[-1].weight.zero_()
            self.net[-1].bias.zero_()

    def forward(self, features):
        base = features[..., self.base_index] * self.scale
        return base + self.net(features).squeeze(-1)
