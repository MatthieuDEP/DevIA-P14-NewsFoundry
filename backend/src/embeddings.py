"""Adapter le SDK Mistral existant à l'interface d'embeddings de LlamaIndex."""

import math
import os

from fastapi import HTTPException
from llama_index.core.base.embeddings.base import BaseEmbedding
from mistralai.client import Mistral


def vectors(response, count):
    data = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in data] != list(range(count)):
        raise ValueError("Nombre d'embeddings incorrect.")
    result = [item.embedding for item in data]
    if not result or any(
        not isinstance(vector, list) or not vector
        or len(vector) != len(result[0])
        or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector)
        or not any(vector)
        for vector in result
    ):
        raise ValueError("Embeddings invalides.")
    return result


class MistralEmbedding(BaseEmbedding):
    model_name: str = "mistral-embed"

    def client(self):
        key = os.getenv("MISTRAL_API_KEY", "").strip()
        if not key:
            raise HTTPException(503, "La recherche dans les articles n’est pas configurée.")
        return Mistral(api_key=key)

    def _get_text_embeddings(self, texts):
        with self.client() as client:
            response = client.embeddings.create(
                model=self.model_name, inputs=texts, timeout_ms=15000, retries=None,
            )
        return vectors(response, len(texts))

    def _get_text_embedding(self, text):
        return self._get_text_embeddings([text])[0]

    def _get_query_embedding(self, query):
        return self._get_text_embedding(query)

    async def _aget_text_embeddings(self, texts):
        async with self.client() as client:
            response = await client.embeddings.create_async(
                model=self.model_name, inputs=texts, timeout_ms=15000, retries=None,
            )
        return vectors(response, len(texts))

    async def _aget_query_embedding(self, query):
        return (await self._aget_text_embeddings([query]))[0]
