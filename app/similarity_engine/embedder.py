from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

from .config import SimilarityConfig


class Embedder(ABC):
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Deterministic local embedder for development and API verification.

    It is not a semantic model. Production should use SentenceTransformerEmbedder.
    """

    def __init__(self, dim: int = 384):
        self.dim = int(dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = re.findall(r"[A-Za-z0-9가-힣_./-]+", str(text or "").lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8", errors="ignore"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_path: str, dim: int | None = None):
        from sentence_transformers import SentenceTransformer

        if not model_path:
            raise ValueError("SIM_EMBEDDING_MODEL_PATH is required for sentence_transformer backend")
        self.model = SentenceTransformer(model_path)
        self.dim = int(dim or self.model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [v.astype("float32").tolist() for v in vectors]


class HuggingFaceTransformerEmbedder(Embedder):
    def __init__(self, model_path: str, max_length: int = 512):
        if not model_path:
            raise ValueError("SIM_EMBEDDING_MODEL_PATH is required for hf_transformer backend")
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=False)
        self.model = AutoModel.from_pretrained(model_path)
        self.model.eval()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.max_length = int(max_length)
        self.dim = int(getattr(self.model.config, "hidden_size", 1024))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = []
        batch_size = 8
        for start in range(0, len(texts), batch_size):
            batch_texts = [str(text or "") for text in texts[start : start + batch_size]]
            batch = self.tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            batch = {key: value.to(self.device) for key, value in batch.items()}
            with self.torch.no_grad():
                output = self.model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1).float()
                pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
                normalized = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(normalized.detach().cpu().float().tolist())
        return vectors


def build_embedder(config: SimilarityConfig) -> Embedder:
    if config.embedder_backend in {"sentence_transformer", "sentence-transformer", "st"}:
        return SentenceTransformerEmbedder(config.embedding_model_path, dim=None)
    if config.embedder_backend in {"hf_transformer", "huggingface_transformer", "transformers"}:
        return HuggingFaceTransformerEmbedder(config.embedding_model_path)
    return HashEmbedder(dim=config.embedding_dim)
