import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import httpx2
import pytest
from fastapi import HTTPException
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import NodeWithScore, TextNode
from mistralai.client.errors import SDKError
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from sqlmodel import Session

import database
import rag
import reviews
from embeddings import vectors
from models import Chat
from review_agent import review_agent


class TopicEmbedding(BaseEmbedding):
    """Vecteurs déterministes pour tester le vrai index LlamaIndex sans API."""

    def _get_text_embedding(self, text):
        text = text.casefold()
        if "cobalt" in text:
            return [1.0, 0.0, 0.0, 0.0]
        if any(word in text for word in ("énergie", "batterie", "solaire")):
            return [0.0, 1.0, 0.0, 0.0]
        if "football" in text:
            return [0.0, 0.0, 1.0, 0.0]
        return [0.0, 0.0, 0.0, 1.0]

    def _get_query_embedding(self, query):
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query):
        return self._get_query_embedding(query)


@pytest.fixture
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(rag, "get_embedding_model", lambda: TopicEmbedding(embed_batch_size=32))


def documents():
    return [
        {"url": "https://example.com/energy", "title": "Batteries et énergie", "text": "Le stockage solaire utilise des batteries. Un prototype réduit les pertes.", "published_at": "2026-10-12"},
        {"url": "https://example.com/football", "title": "Football", "text": "Le championnat de football reprend. Deux équipes jouent une finale.", "published_at": "2026-10-11"},
    ]


def seed_chat(client, headers, articles):
    chat_id = client.post("/chats", headers=headers).json()["id"]
    assert client.post(f"/chats/{chat_id}/messages", headers=headers, json={"content": "Parlons des sujets chargés."}).status_code == 200
    with Session(database.engine) as session:
        chat = session.get(Chat, chat_id)
        chat.article_documents = articles
        chat.loaded_articles = [article["url"] for article in articles]
        session.add(chat)
        session.commit()
    return chat_id


def test_real_index_retrieves_only_relevant_article(fake_embeddings):
    selected = asyncio.run(rag.retrieve_articles("stockage solaire et batteries", documents()))
    assert [article["url"] for article in selected] == ["https://example.com/energy"]
    assert "prototype" in " ".join(selected[0]["passages"])
    assert selected[0]["published_at"] == "2026-10-12"


def test_unrelated_topic_returns_no_articles(fake_embeddings):
    assert asyncio.run(rag.retrieve_articles("recettes de pâtisserie", documents())) == []


def test_missing_full_text_does_not_call_embeddings(monkeypatch):
    with patch.object(rag, "get_embedding_model", side_effect=AssertionError("No embeddings allowed")):
        assert asyncio.run(rag.retrieve_articles("énergie", [{"url": "https://example.com/a", "text": ""}])) == []


def test_score_threshold_and_relative_gap_are_applied():
    source = {"https://example.com/a": {"title": "A"}, "https://example.com/b": {"title": "B"}}
    matches = [
        NodeWithScore(node=TextNode(text="A", metadata={"url": "https://example.com/a"}), score=0.91),
        NodeWithScore(node=TextNode(text="B", metadata={"url": "https://example.com/b"}), score=0.77),
    ]
    assert [item["title"] for item in rag.select_articles(matches, source)] == ["A"]
    matches[0].score = 0.70
    matches[1].score = 0.60
    assert rag.select_articles(matches, source) == []


def test_rag_review_uses_full_content_beyond_chat_excerpt(client, owner_headers, fake_embeddings):
    article = {
        "url": "https://example.com/recycling", "title": "Un procédé de recyclage",
        "text": "Les équipes étudient un procédé industriel. " * 100 + "Le procédé récupère 97 % du cobalt pour fabriquer de nouvelles batteries.",
        "published_at": "2026-10-12",
    }
    chat_id = seed_chat(client, owner_headers, [article, documents()[1]])

    def respond(messages, info):
        context = json.loads(next(part.content for part in messages[-1].parts if isinstance(part, UserPromptPart)))
        selected = context["selected_articles"]
        assert [item["url"] for item in selected] == [article["url"]]
        assert "97 % du cobalt" in " ".join(selected[0]["passages"])
        assert "97 % du cobalt" not in json.dumps(context["chat_history"])
        assert info.function_tools == []
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "title": "Le recyclage du cobalt", "summary": "Le procédé récupère 97 % du cobalt.",
            "articles": [{"title": "Titre reformulé", "summary": "Une récupération de 97 % du cobalt est annoncée.", "url": article["url"], "published_at": "date inventée"}],
        }, tool_call_id="rag-output")])

    with review_agent.override(model=FunctionModel(respond)):
        response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json={"topic": "Recyclage du cobalt"})
    assert response.status_code == 201
    assert response.json()["source_mode"] == "full_text"
    assert response.json()["articles"][0]["title"] == article["title"]
    assert response.json()["articles"][0]["published_at"] == article["published_at"]
    assert "97 %" in response.json()["articles"][0]["summary"]
    assert "Les équipes étudient" not in response.text


def test_no_match_creates_explicit_empty_review_without_llm(client, owner_headers, fake_embeddings):
    chat_id = seed_chat(client, owner_headers, documents())
    with patch.object(review_agent, "run", side_effect=AssertionError("No LLM call allowed")):
        response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json={"topic": "Recettes de pâtisserie"})
    assert response.status_code == 201
    assert response.json()["source_mode"] == "no_match"
    assert response.json()["articles"] == []
    assert "Aucun article" in response.json()["summary"]


def test_old_chat_remains_usable_without_embeddings(client, owner_headers):
    chat_id = seed_chat(client, owner_headers, [])
    with patch.object(reviews, "retrieve_articles", side_effect=AssertionError("No indexing allowed")):
        response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json={"topic": "Énergie"})
    assert response.status_code == 201
    assert response.json()["source_mode"] == "history"


def test_unselected_history_source_cannot_be_cited(client, owner_headers, fake_embeddings):
    chat_id = seed_chat(client, owner_headers, documents())

    def wrong_source(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "title": "Revue", "summary": "Synthèse",
            "articles": [{"title": "Football", "summary": "Hors sujet", "url": "https://example.com/football"}],
        }, tool_call_id="unselected")])

    with review_agent.override(model=FunctionModel(wrong_source)):
        response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json={"topic": "Batteries et énergie"})
    assert response.status_code == 502
    assert client.get("/reviews", headers=owner_headers).json() == []


def test_other_owner_cannot_index_chat(client, owner_headers, other_headers):
    chat_id = seed_chat(client, owner_headers, documents())
    with patch.object(reviews, "retrieve_articles", side_effect=AssertionError("No indexing allowed")):
        response = client.post(f"/chats/{chat_id}/reviews", headers=other_headers, json={"topic": "Énergie"})
    assert response.status_code == 404


def test_same_url_isolated_between_users(client, owner_headers, other_headers, fake_embeddings):
    first = seed_chat(client, owner_headers, [{"url": "https://example.com/shared", "title": "Batteries", "text": "Les batteries stockent de l'énergie solaire."}])
    second = seed_chat(client, other_headers, [{"url": "https://example.com/shared", "title": "Football", "text": "Un article sur le football."}])
    with patch.object(review_agent, "run", side_effect=AssertionError("No LLM call allowed")):
        response = client.post(f"/chats/{second}/reviews", headers=other_headers, json={"topic": "Batteries et énergie"})
    assert response.status_code == 201
    assert response.json()["source_mode"] == "no_match"
    with Session(database.engine) as session:
        assert "solaire" in session.get(Chat, first).article_documents[0]["text"]
        assert "football" in session.get(Chat, second).article_documents[0]["text"]


@pytest.mark.parametrize("error", [HTTPException(429, "Quota temporairement atteint."), HTTPException(502, "Analyse indisponible.")])
def test_embedding_failure_keeps_previous_reviews(client, owner_headers, monkeypatch, error):
    chat_id = seed_chat(client, owner_headers, documents())
    with Session(database.engine) as session:
        original = session.get(Chat, chat_id).messages
    monkeypatch.setattr(reviews, "retrieve_articles", AsyncMock(side_effect=error))
    response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json={"topic": "Énergie"})
    assert response.status_code == error.status_code
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).messages == original
        assert session.get(Chat, chat_id).reviews == []


@pytest.mark.parametrize("values", [[[]], [[0.0, 0.0]], [[float("nan"), 1.0]], [[1.0], [1.0, 2.0]]])
def test_bad_embedding_vectors_are_rejected(values):
    response = SimpleNamespace(data=[SimpleNamespace(index=i, embedding=value) for i, value in enumerate(values)])
    with pytest.raises(ValueError):
        vectors(response, len(values))


def test_embedding_vectors_follow_provider_indices():
    response = SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[0.0, 1.0]), SimpleNamespace(index=0, embedding=[1.0, 0.0])])
    assert vectors(response, 2) == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.parametrize("error,status", [
    (SDKError("private quota", httpx2.Response(429)), 429),
    (SDKError("private key", httpx2.Response(401)), 503),
    (httpx2.ReadTimeout("private timeout"), 504),
    (httpx2.ConnectError("private network"), 502),
    (ValueError("private bad vectors"), 502),
])
def test_provider_errors_are_sanitized(monkeypatch, error, status):
    embedding = SimpleNamespace(embed_batch_size=32, aget_text_embedding_batch=AsyncMock(side_effect=error))
    monkeypatch.setattr(rag, "get_embedding_model", lambda: embedding)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(rag.retrieve_articles("énergie", documents()))
    assert failure.value.status_code == status
    assert "private" not in failure.value.detail


@pytest.mark.parametrize("urls", [[None], ["https://example.com/energy", "https://example.com/energy"]])
def test_rag_articles_require_unique_selected_links(client, owner_headers, fake_embeddings, urls):
    chat_id = seed_chat(client, owner_headers, documents())

    def invalid(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "title": "Énergie", "summary": "Une synthèse",
            "articles": [{"title": "Article", "summary": "Résumé", "url": url} for url in urls],
        }, tool_call_id="bad-links")])

    with review_agent.override(model=FunctionModel(invalid)):
        response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json={"topic": "Batteries et énergie"})
    assert response.status_code == 502
    assert client.get("/reviews", headers=owner_headers).json() == []


def test_agent_can_reject_all_retrieved_candidates(client, owner_headers, fake_embeddings):
    chat_id = seed_chat(client, owner_headers, documents())

    def empty(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "title": "Sans correspondance", "summary": "Texte non sourcé à remplacer.", "articles": [],
        }, tool_call_id="empty-review")])

    with review_agent.override(model=FunctionModel(empty)):
        response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json={"topic": "Batteries et énergie"})
    assert response.status_code == 201
    assert response.json()["source_mode"] == "no_match"
    assert "Aucun article" in response.json()["summary"]
    assert "Texte non sourcé" not in response.text
