import asyncio
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import (
    ModelResponse, RetryPromptPart, SystemPromptPart, TextPart, ToolCallPart, ToolReturnPart,
)
from pydantic_ai.models.function import FunctionModel
from sqlmodel import Session

import chat_agent as agent_module
import database
import news
from chat_agent import chat_agent
from models import Chat


@pytest.fixture
def search_http(monkeypatch):
    monkeypatch.setenv("WORLD_NEWS_API_KEY", "private-search-test-key")
    monkeypatch.setattr(news, "today", lambda: date(2026, 10, 11))
    original_client = httpx.AsyncClient
    requests = []

    def install(handler):
        def respond(request):
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(news.httpx, "AsyncClient", lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs,
        ))
        return requests

    return install


def article():
    return {
        "title": "Une avancée sur le stockage de l'énergie",
        "summary": "Une batterie expérimentale stocke davantage d'énergie.",
        "text": "Le prototype utilise un nouveau matériau. " * 100,
        "url": "https://example.com/batterie",
        "publish_date": "2026-10-11 08:00:00",
    }


def test_search_request_and_bounded_results(search_http):
    def respond(request):
        assert request.url.path == "/search-news"
        assert dict(request.url.params) == {
            "text": "batteries", "language": "fr", "earliest-publish-date": "2026-10-04",
            "sort": "publish-time", "sort-direction": "DESC", "number": "5",
        }
        assert request.headers["x-api-key"] == "private-search-test-key"
        assert "private-search-test-key" not in str(request.url)
        articles = [article(), article()]
        articles += [{"title": f"Sujet {i}", "text": "x" * 3000, "summary": "y" * 1200} for i in range(8)]
        return httpx.Response(200, json={"news": articles})

    requests = search_http(respond)
    result = asyncio.run(news.fetch_search_news("batteries"))
    assert len(requests) == 1
    assert result["status"] == "ok"
    assert result["from_date"] == "2026-10-04"
    assert len(result["articles"]) == 5
    assert all(len(item["excerpt"]) <= 2000 and len(item["summary"]) <= 800 for item in result["articles"])
    assert result["articles"][0]["url"] == "https://example.com/batterie"
    assert result["articles"][0]["published_at"] == "2026-10-11 08:00:00"


def test_empty_search_is_valid(search_http):
    search_http(lambda request: httpx.Response(200, json={"news": []}))
    result = asyncio.run(news.fetch_search_news("sujet inconnu"))
    assert result["status"] == "ok"
    assert result["articles"] == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,test", "https://", "https://[", None])
def test_search_omits_unsafe_or_missing_links(search_http, url):
    search_http(lambda request: httpx.Response(200, json={"news": [{"title": "Titre", "url": url}]}))
    result = asyncio.run(news.fetch_search_news("sujet"))
    assert result["articles"][0]["url"] is None
    assert result["articles"][0]["summary"] == "Résumé non fourni."


@pytest.mark.parametrize("payload", [{}, {"news": "invalid"}, {"news": [{"summary": 42}]}])
def test_invalid_search_response_is_rejected(search_http, payload):
    search_http(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(HTTPException) as error:
        asyncio.run(news.fetch_search_news("sujet"))
    assert error.value.status_code == 502


def request_search(messages, info):
    if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
        result = next(part.content for part in messages[-1].parts if isinstance(part, ToolReturnPart))
        if result["status"] == "error":
            return ModelResponse(parts=[TextPart("La recherche a échoué : " + result["message"])])
        first = result["articles"][0]
        return ModelResponse(parts=[TextPart(f"{first['summary']} [Source]({first['url']})")])
    assert [tool.name for tool in info.function_tools] == ["search_news"]
    return ModelResponse(parts=[ToolCallPart("search_news", {"query": "  batteries  "}, tool_call_id="search-1")])


def test_agent_calls_api_uses_results_and_saves_tool_history(client, owner_headers, search_http):
    requests = search_http(lambda request: httpx.Response(200, json={"news": [article()]}))
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]
    with chat_agent.override(model=FunctionModel(request_search)):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Approfondis les batteries."})
    assert response.status_code == 200
    assert len(requests) == 1
    assert requests[0].url.params["text"] == "batteries"
    assert response.json()["reply"] == "Une batterie expérimentale stocke davantage d'énergie. [Source](https://example.com/batterie)"
    assert [item["role"] for item in response.json()["messages"]] == ["user", "assistant"]
    assert "retrieved_at" not in response.text
    with Session(database.engine) as session:
        stored = session.get(Chat, chat_id)
        history = ModelMessagesTypeAdapter.validate_python(stored.messages)
        assert stored.loaded_articles == [article()["url"]]
        assert stored.article_documents[0]["text"] == article()["text"].strip()
        assert len(stored.article_documents[0]["text"]) > 2000
    returns = [part for message in history for part in message.parts if isinstance(part, ToolReturnPart)]
    assert returns[0].content["articles"][0]["title"] == article()["title"]
    assert "text" not in returns[0].content["articles"][0]
    prompt = [part.content for message in history for part in message.parts if isinstance(part, SystemPromptPart)]

    def reuse(messages, info):
        saved = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        assert saved[0].content["articles"][0]["url"] == article()["url"]
        assert [part.content for message in messages for part in message.parts if isinstance(part, SystemPromptPart)] == prompt
        return ModelResponse(parts=[TextPart("Le prototype utilise un nouveau matériau.")])

    with chat_agent.override(model=FunctionModel(reuse)):
        assert client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Et le matériau ?"}).status_code == 200
    assert len(requests) == 1
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).loaded_articles == [article()["url"]]
        assert len(session.get(Chat, chat_id).article_documents) == 1


@pytest.mark.parametrize("args", [
    {"query": "x"}, {"query": "  "}, {"query": "x" * 201},
    {"query": "batteries", "days": 0}, {"query": "batteries", "days": 31},
    {"query": "batteries", "api_key": "spoofed"},
])
def test_invalid_tool_arguments_never_call_api(client, owner_headers, search_http, args):
    def fail(request):
        raise AssertionError("No HTTP call allowed")

    requests = search_http(fail)
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]

    def respond(messages, info):
        if any(isinstance(part, RetryPromptPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Précisez le sujet de recherche.")])
        return ModelResponse(parts=[ToolCallPart("search_news", args, tool_call_id="invalid")])

    with chat_agent.override(model=FunctionModel(respond)):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Recherche"})
    assert response.status_code == 200
    assert requests == []


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_tool_api_error_is_given_to_model_without_private_details(client, owner_headers, search_http, status):
    search_http(lambda request: httpx.Response(status, json={"message": "private provider detail"}))
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]
    with chat_agent.override(model=FunctionModel(request_search)):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Approfondis"})
    assert response.status_code == 200
    assert "La recherche a échoué" in response.json()["reply"]
    assert "private" not in response.text
    with Session(database.engine) as session:
        history = ModelMessagesTypeAdapter.validate_python(session.get(Chat, chat_id).messages)
    assert any(isinstance(part, ToolReturnPart) and part.content["status"] == "error" for message in history for part in message.parts)


def test_search_limit_stops_loop_and_keeps_history(client, owner_headers, search_http):
    requests = search_http(lambda request: httpx.Response(200, json={"news": [article()]}))
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]
    with Session(database.engine) as session:
        initial = session.get(Chat, chat_id).messages
    calls = 0

    def loop(messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[ToolCallPart("search_news", {"query": "batteries"}, tool_call_id=str(calls))])

    with chat_agent.override(model=FunctionModel(loop)):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Recherche"})
    assert response.status_code == 502
    assert len(requests) == 3
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).messages == initial


def test_another_owner_cannot_trigger_search(client, owner_headers, other_headers, monkeypatch):
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]
    fetch = AsyncMock(side_effect=AssertionError("No search allowed"))
    monkeypatch.setattr(agent_module, "fetch_search_news", fetch)
    with chat_agent.override(model=FunctionModel(request_search)):
        response = client.post(f"/chats/{chat_id}/messages", headers=other_headers, json={"content": "Recherche"})
    assert response.status_code == 404
    fetch.assert_not_awaited()


def test_same_article_is_updated_without_duplicate_url(client, owner_headers, search_http):
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        item = article()
        item["text"] = f"Contenu complet, version {count}."
        return httpx.Response(200, json={"news": [item]})

    search_http(respond)
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]
    with chat_agent.override(model=FunctionModel(request_search)):
        for question in ("Recherche des batteries", "Recherche à nouveau"):
            assert client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": question}).status_code == 200
    with Session(database.engine) as session:
        stored = session.get(Chat, chat_id)
        assert stored.loaded_articles == [article()["url"]]
        assert len(stored.article_documents) == 1
        assert stored.article_documents[0]["text"] == "Contenu complet, version 2."


def test_failed_exchange_does_not_save_partial_articles(client, owner_headers, search_http):
    search_http(lambda request: httpx.Response(200, json={"news": [article()]}))
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]

    def fail_after_search(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            raise TimeoutError()
        return ModelResponse(parts=[ToolCallPart("search_news", {"query": "batteries"}, tool_call_id="failed")])

    with chat_agent.override(model=FunctionModel(fail_after_search)):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Recherche"})
    assert response.status_code == 504
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).loaded_articles == []
        assert session.get(Chat, chat_id).article_documents == []
