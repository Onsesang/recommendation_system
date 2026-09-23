"""Small, reproducible BERT4Rec and GRU4Rec implementations for Experiment 17."""
from __future__ import annotations

import math
import torch
from torch import nn
from torch.nn import functional as F


class BERT4Rec(nn.Module):
    """Bidirectional masked-item Transformer; item IDs are shifted by one.

    0 is padding, 1..nitems are catalog items, and nitems+1 is [MASK].
    """

    def __init__(self, nitems: int, dim: int = 64, layers: int = 2,
                 heads: int = 2, maxlen: int = 50, dropout: float = 0.2):
        super().__init__()
        self.nitems, self.dim, self.maxlen = nitems, dim, maxlen
        self.mask_id = nitems + 1
        self.item = nn.Embedding(nitems + 2, dim, padding_idx=0)
        self.pos = nn.Embedding(maxlen, dim)
        layer = nn.TransformerEncoderLayer(
            dim, heads, dim_feedforward=dim * 4, dropout=dropout,
            activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, layers)
        self.norm = nn.LayerNorm(dim)
        nn.init.normal_(self.item.weight, std=0.02)
        with torch.no_grad():
            self.item.weight[0].zero_()

    def forward(self, seq: torch.Tensor) -> torch.Tensor:
        pad = seq.eq(0)
        pos = torch.arange(seq.shape[1], device=seq.device)
        x = self.item(seq) * math.sqrt(self.dim) + self.pos(pos)
        x = self.encoder(x, src_key_padding_mask=pad)
        return self.norm(x).masked_fill(pad.unsqueeze(-1), 0)

    def sampled_loss(self, seq: torch.Tensor, positions: torch.Tensor,
                     truth: torch.Tensor, negatives: torch.Tensor) -> torch.Tensor:
        z = self(seq)[torch.arange(len(seq), device=seq.device), positions]
        pos = (z * self.item(truth)).sum(-1, keepdim=True)
        neg = torch.einsum("bd,bnd->bn", z, self.item(negatives))
        logits = torch.cat([pos, neg], dim=1)
        return F.cross_entropy(logits, torch.zeros(len(seq), dtype=torch.long, device=seq.device))

    def query(self, history: torch.Tensor) -> torch.Tensor:
        # Caller left-pads and reserves the final position for [MASK].
        return self(history)[:, -1]

    def catalog_items(self) -> torch.Tensor:
        return self.item.weight[1:self.nitems + 1]


class GRU4Rec(nn.Module):
    """One-layer GRU next-item model with shared input/output item embeddings."""

    def __init__(self, nitems: int, dim: int = 64, maxlen: int = 50,
                 dropout: float = 0.2, **_: object):
        super().__init__()
        self.nitems, self.dim, self.maxlen = nitems, dim, maxlen
        self.item = nn.Embedding(nitems + 1, dim, padding_idx=0)
        self.gru = nn.GRU(dim, dim, batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.norm = nn.LayerNorm(dim)
        nn.init.normal_(self.item.weight, std=0.02)
        with torch.no_grad():
            self.item.weight[0].zero_()

    def forward(self, seq: torch.Tensor) -> torch.Tensor:
        x, _ = self.gru(self.drop(self.item(seq)))
        return self.norm(x).masked_fill(seq.eq(0).unsqueeze(-1), 0)

    def sampled_loss(self, seq: torch.Tensor, positions: torch.Tensor,
                     truth: torch.Tensor, negatives: torch.Tensor) -> torch.Tensor:
        z = self(seq)[torch.arange(len(seq), device=seq.device), positions]
        pos = (z * self.item(truth)).sum(-1, keepdim=True)
        neg = torch.einsum("bd,bnd->bn", z, self.item(negatives))
        logits = torch.cat([pos, neg], dim=1)
        return F.cross_entropy(logits, torch.zeros(len(seq), dtype=torch.long, device=seq.device))

    def query(self, history: torch.Tensor) -> torch.Tensor:
        return self(history)[:, -1]

    def catalog_items(self) -> torch.Tensor:
        return self.item.weight[1:]
