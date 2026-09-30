#!/usr/bin/env python3
"""SASRec copied verbatim from experiments/24_adaptive_tactile_recommendation/scripts/models24.py
(itself verbatim from exp16b), plus a sampled-softmax loss used only by the ``ce`` runs."""
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


def sampled_softmax_loss(model: SASRec, seq, pos, negatives):
    """Cross-entropy of the positive against a shared pool of sampled negatives.

    ``negatives`` are shifted ids (1-based) shared by every position in the batch; a
    negative that equals the position's positive is masked out.
    """
    z = model(seq)
    valid = pos > 0
    z = z[valid]
    target = pos[valid]
    positive = (z * model.item_embedding(target)).sum(-1, keepdim=True)
    negative = z @ model.item_embedding(negatives).T
    negative = negative.masked_fill(target.unsqueeze(1) == negatives.unsqueeze(0), float("-inf"))
    logits = torch.cat([positive, negative], dim=1)
    return F.cross_entropy(logits, torch.zeros(len(logits), dtype=torch.long, device=logits.device))
