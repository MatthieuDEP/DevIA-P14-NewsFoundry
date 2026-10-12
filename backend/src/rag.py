"""Index temporaire des textes chargés dans une seule discussion."""

import os

import httpx
import httpx2
from fastapi import HTTPException
from llama_index.core import Document, VectorStoreIndex
from llama_index.core.node_parser import TokenTextSplitter
from llama_index.core.schema import MetadataMode
from mistralai.client.errors import MistralError, NoResponseError, SDKError
from pydantic import HttpUrl

from embeddings import MistralEmbedding

MIN_SCORE = 0.72
MAX_SCORE_GAP = 0.08
MAX_ARTICLES = 5
MAX_NODES = 600


def get_embedding_model():
    return MistralEmbedding(
        model_name=os.getenv("MISTRAL_EMBEDDING_MODEL") or "mistral-embed",
        embed_batch_size=32,
    )


def select_articles(matches, documents):
    if not matches:
        return []
    cutoff = max(MIN_SCORE, (matches[0].score or 0) - MAX_SCORE_GAP)
    selected = {}
    for match in matches:
        if (match.score or 0) < cutoff:
            continue
        url = match.node.metadata["url"]
        if url not in selected:
            if len(selected) == MAX_ARTICLES:
                continue
            source = documents[url]
            selected[url] = {
                "url": url, "title": source["title"],
                "published_at": source.get("published_at"), "passages": [],
            }
        if len(selected[url]["passages"]) < 3:
            selected[url]["passages"].append(match.node.get_content(metadata_mode=MetadataMode.NONE))
    return list(selected.values())


async def retrieve_articles(topic, article_documents):
    documents = {
        str(HttpUrl(article["url"])): article
        for article in article_documents if article.get("text", "").strip()
    }
    if not documents:
        return []
    sources = [Document(
        text=article["text"], id_=url,
        metadata={"url": url, "title": article["title"]},
        excluded_embed_metadata_keys=["url"], excluded_llm_metadata_keys=["url"],
    ) for url, article in documents.items()]
    nodes = TokenTextSplitter(chunk_size=512, chunk_overlap=64).get_nodes_from_documents(sources)
    if len(nodes) > MAX_NODES:
        raise HTTPException(422, "Cette discussion contient trop d’articles. Utilisez une discussion plus ciblée.")
    embedding = get_embedding_model()
    try:
        # Pré-calculer les vecteurs de façon asynchrone, un batch à la fois.
        # Le constructeur d'index n'a ensuite aucun appel réseau à effectuer.
        for start in range(0, len(nodes), embedding.embed_batch_size):
            batch = nodes[start:start + embedding.embed_batch_size]
            values = await embedding.aget_text_embedding_batch([
                node.get_content(metadata_mode=MetadataMode.EMBED) for node in batch
            ])
            for node, vector in zip(batch, values, strict=True):
                node.embedding = vector
        index = VectorStoreIndex(nodes, embed_model=embedding)
        matches = await index.as_retriever(similarity_top_k=min(25, len(nodes))).aretrieve(topic)
    except SDKError as error:
        status = 429 if error.status_code == 429 else 503
        raise HTTPException(status, "La recherche dans les articles est temporairement indisponible. Réessayez.") from None
    except (httpx.TimeoutException, httpx2.TimeoutException):
        raise HTTPException(504, "La recherche dans les articles prend trop de temps. Réessayez.") from None
    except (httpx.RequestError, httpx2.RequestError, MistralError, NoResponseError, ValueError):
        raise HTTPException(502, "Les articles n’ont pas pu être analysés. Réessayez.") from None
    return select_articles(matches, documents)
