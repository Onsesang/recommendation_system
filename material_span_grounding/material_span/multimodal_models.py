from __future__ import annotations

import torch
from torch import nn


class TactileMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 256, output_dim: int = 384) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(0.15),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return nn.functional.normalize(self.network(values), dim=-1)
