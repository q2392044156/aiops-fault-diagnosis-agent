import math
import os
import random

import numpy as np
import torch
from torch import nn
from torch.utils.data import Dataset


def seed_everything(seed):
    # Required by CUDA for deterministic matrix multiplications.  It must be set
    # before the first training operation; setdefault preserves an explicit user
    # choice.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def resolve_device(requested):
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is not available")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("device must be auto, cpu, or cuda")
    return torch.device(requested)


class SequenceDataset(Dataset):
    def __init__(self, rows, labels, scaler, max_length):
        self.rows = rows
        self.labels = labels
        self.scaler = scaler
        self.max_length = max_length

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        template_ids = row["template_ids"]
        gaps = row["gap_seconds"]
        if not template_ids or len(template_ids) != len(gaps):
            raise ValueError(f"Empty or misaligned sequence: {row['block_id']}")
        clip = self.scaler["gap_clip_log1p"]
        gap_stats = self.scaler["gap"]
        transformed_gaps = [
            (min(math.log1p(max(0.0, float(value))), clip) - gap_stats["mean"]) /
            gap_stats["std"] for value in gaps
        ]
        length_stats = self.scaler["session_length_log1p"]
        duration_stats = self.scaler["duration_log1p"]
        session_values = [
            (math.log1p(row["session_length"]) - length_stats["mean"]) / length_stats["std"],
            (math.log1p(max(0.0, row["duration_seconds"])) - duration_stats["mean"]) /
            duration_stats["std"],
            float(row["warn_ratio"]), float(row["error_ratio"]),
        ]
        return {
            "block_id": row["block_id"], "template_ids": template_ids,
            "gaps": transformed_gaps, "session_features": session_values,
            "label": float(self.labels[row["block_id"]]),
            "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"],
        }


def collate_sequences(items, max_length=128):
    if not items:
        raise ValueError("Cannot collate an empty batch")
    chunk_counts = [math.ceil(len(item["template_ids"]) / max_length) for item in items]
    if any(value < 1 for value in chunk_counts):
        raise ValueError("Empty sequences are not valid")
    batch, max_chunks = len(items), max(chunk_counts)
    ids = torch.zeros((batch, max_chunks, max_length), dtype=torch.long)
    gaps = torch.zeros((batch, max_chunks, max_length), dtype=torch.float32)
    mask = torch.zeros((batch, max_chunks, max_length), dtype=torch.bool)
    chunk_valid = torch.zeros((batch, max_chunks), dtype=torch.bool)
    for batch_index, item in enumerate(items):
        if len(item["template_ids"]) != len(item["gaps"]):
            raise ValueError("Template and gap lengths differ")
        for chunk_index in range(chunk_counts[batch_index]):
            start = chunk_index * max_length
            stop = min(start + max_length, len(item["template_ids"]))
            width = stop - start
            ids[batch_index, chunk_index, :width] = torch.tensor(
                item["template_ids"][start:stop], dtype=torch.long)
            gaps[batch_index, chunk_index, :width] = torch.tensor(
                item["gaps"][start:stop], dtype=torch.float32)
            mask[batch_index, chunk_index, :width] = True
            chunk_valid[batch_index, chunk_index] = True
    return {
        "block_ids": [item["block_id"] for item in items],
        "template_ids": ids, "gaps": gaps, "mask": mask,
        "chunk_valid": chunk_valid,
        "session_features": torch.tensor([item["session_features"] for item in items],
                                         dtype=torch.float32),
        "labels": torch.tensor([item["label"] for item in items], dtype=torch.float32),
        "first_log_ids": [item["first_log_id"] for item in items],
        "last_log_ids": [item["last_log_id"] for item in items],
    }


class LSTMClassifier(nn.Module):
    def __init__(self, vocabulary_size, embedding_dim=32, hidden_dim=64, dropout=0.2,
                 session_feature_count=4):
        super().__init__()
        self.embedding = nn.Embedding(vocabulary_size, embedding_dim, padding_idx=0)
        self.lstm = nn.LSTM(embedding_dim + 1, hidden_dim, num_layers=1,
                            batch_first=True, bidirectional=False)
        self.session_feature_count = session_feature_count
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(hidden_dim * 2 + session_feature_count, 1)

    def forward(self, template_ids, gaps, mask, chunk_valid, session_features):
        batch, chunks, length = template_ids.shape
        flat_ids = template_ids.reshape(batch * chunks, length)
        flat_gaps = gaps.reshape(batch * chunks, length, 1)
        flat_mask = mask.reshape(batch * chunks, length)
        embedded = self.embedding(flat_ids)
        hidden, _ = self.lstm(torch.cat([embedded, flat_gaps], dim=-1))
        weights = flat_mask.unsqueeze(-1).to(hidden.dtype)
        mean_pool = (hidden * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)
        max_pool = hidden.masked_fill(~flat_mask.unsqueeze(-1), -torch.inf).max(dim=1).values
        max_pool = torch.where(torch.isfinite(max_pool), max_pool, torch.zeros_like(max_pool))
        pooled = torch.cat([mean_pool, max_pool], dim=-1)
        if self.session_feature_count:
            selected_features = session_features[:, :self.session_feature_count]
            repeated_features = selected_features[:, None, :].expand(batch, chunks, -1)
            repeated_features = repeated_features.reshape(batch * chunks, -1)
            pooled = torch.cat([pooled, repeated_features], dim=-1)
        chunk_logits = self.output(self.dropout(pooled)).squeeze(-1).reshape(batch, chunks)
        chunk_logits = chunk_logits.masked_fill(~chunk_valid, -torch.inf)
        return chunk_logits.max(dim=1).values
