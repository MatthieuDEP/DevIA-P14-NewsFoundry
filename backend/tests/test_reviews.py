import json
from unittest.mock import patch

import pytest
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UserError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine

import database
import reviews
from migrations import ensure_chat_columns
from models import Chat
from review_agent import review_agent


def started_chat(client, headers):
    chat_id = client.post("/chats", headers=headers).json()["id"]
    assert client.post(f"/chats/{chat_id}/messages", headers=headers, json={"content": "Parlons de l'énergie."}).status_code == 200
    return chat_id


def generate(client, headers, chat_id, topic="Énergie"):
    return client.post(f"/chats/{chat_id}/reviews", headers=headers, json={"topic": topic})


def test_multiple_reviews_are_saved_across_chats_and_reloaded(client, owner_headers):
    first = started_chat(client, owner_headers)
    second = started_chat(client, owner_headers)
    responses = [generate(client, owner_headers, first), generate(client, owner_headers, first, "Batteries"), generate(client, owner_headers, second)]
    assert all(response.status_code == 201 for response in responses)
    reviews = client.get("/reviews", headers=owner_headers)
    assert reviews.status_code == 200
    assert reviews.headers["cache-control"] == "no-store"
    assert len(reviews.json()) == 3
    assert len({review["id"] for review in reviews.json()}) == 3
    assert [review["id"] for review in reviews.json()] == [response.json()["id"] for response in reversed(responses)]
    assert {review["chat_id"] for review in reviews.json()} == {first, second}
    with Session(database.engine) as session:
        assert len(session.get(Chat, first).reviews) == 2
        assert session.get(Chat, first).reviews[0]["title"] == "Revue de presse de test"
        assert len(session.get(Chat, first).messages) > 0


def test_other_user_cannot_generate_or_list_reviews(client, owner_headers, other_headers):
    chat_id = started_chat(client, owner_headers)
    assert generate(client, owner_headers, chat_id).status_code == 201
    with Session(database.engine) as session:
        chat = session.get(Chat, chat_id)
        chat.article_documents = [{
            "url": "https://example.com/energy", "title": "Énergie",
            "text": "Les batteries stockent la production solaire.",
        }]
        chat.loaded_articles = ["https://example.com/energy"]
        session.add(chat)
        session.commit()
        original_messages, original_reviews = chat.messages, chat.reviews
    with (
        patch.object(reviews, "retrieve_articles", side_effect=AssertionError("No indexing allowed")) as retrieve,
        patch.object(review_agent, "run", side_effect=AssertionError("No model call allowed")) as run,
    ):
        assert generate(client, other_headers, chat_id).status_code == 404
    retrieve.assert_not_awaited()
    run.assert_not_awaited()
    assert client.get("/reviews", headers=other_headers).json() == []
    assert len(client.get("/reviews", headers=owner_headers).json()) == 1
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).messages == original_messages
        assert session.get(Chat, chat_id).reviews == original_reviews


@pytest.mark.parametrize("method,path,body", [
    ("get", "/reviews", None),
    ("post", "/chats/1/reviews", {"topic": "Énergie"}),
])
def test_reviews_require_login(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("body", [
    {}, {"topic": ""}, {"topic": "  "}, {"topic": "x"}, {"topic": "x" * 201},
    {"topic": "Énergie", "messages": [{"content": "Injected"}]},
])
def test_invalid_topic_is_not_sent_to_model(client, owner_headers, body):
    chat_id = started_chat(client, owner_headers)
    with patch.object(review_agent, "run", side_effect=AssertionError("No model call allowed")):
        response = client.post(f"/chats/{chat_id}/reviews", headers=owner_headers, json=body)
    assert response.status_code == 422


def test_empty_chat_cannot_generate_review(client, owner_headers):
    chat_id = client.post("/chats", headers=owner_headers).json()["id"]
    with patch.object(review_agent, "run", side_effect=AssertionError("No model call allowed")):
        assert generate(client, owner_headers, chat_id).status_code == 422


def test_review_agent_receives_full_saved_history_without_search_tools(client, owner_headers):
    chat_id = started_chat(client, owner_headers)
    with Session(database.engine) as session:
        chat = session.get(Chat, chat_id)
        history = ModelMessagesTypeAdapter.validate_python(chat.messages)
        history += [
            ModelResponse(parts=[ToolCallPart("search_news", {"query": "énergie"}, tool_call_id="old-search")]),
            ModelRequest(parts=[ToolReturnPart("search_news", {"articles": [{
                "title": "Nouvelle batterie", "summary": "Un prototype prometteur.",
                "url": "https://example.com/batterie", "published_at": "2026-10-11",
            }]}, tool_call_id="old-search")]),
            ModelResponse(parts=[TextPart("Voici une source sur les batteries.")]),
        ]
        original = ModelMessagesTypeAdapter.dump_python(history, mode="json")
        chat.messages = original
        session.add(chat)
        session.commit()

    def respond(messages, info):
        assert info.function_tools == []
        prompt = next(part.content for part in messages[-1].parts if isinstance(part, UserPromptPart))
        context = json.loads(prompt)
        assert context["topic"] == "Batteries"
        assert context["chat_history"] == original
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "title": "Batteries : une innovation", "summary": "Le prototype présente des perspectives.",
            "articles": [{"title": "Nouvelle batterie", "summary": "Un prototype prometteur.", "url": "https://example.com/batterie", "published_at": "2026-10-11"}],
        }, tool_call_id="review-output")])

    with review_agent.override(model=FunctionModel(respond)):
        response = generate(client, owner_headers, chat_id, "  Batteries  ")
    assert response.status_code == 201
    assert response.json()["topic"] == "Batteries"
    assert response.json()["articles"][0]["url"] == "https://example.com/batterie"
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).messages == original


@pytest.mark.parametrize("error,expected", [
    (TimeoutError(), 504), (ModelHTTPError(429, "test", "private detail"), 429),
    (ModelHTTPError(500, "test", "private detail"), 502),
    (ModelHTTPError(401, "test", "private detail"), 503),
    (UserError("private configuration"), 503), (UnexpectedModelBehavior("private output"), 502),
])
def test_generation_error_keeps_chat_and_reviews(client, owner_headers, error, expected):
    chat_id = started_chat(client, owner_headers)
    assert generate(client, owner_headers, chat_id).status_code == 201
    with Session(database.engine) as session:
        original_messages = session.get(Chat, chat_id).messages
        original_reviews = session.get(Chat, chat_id).reviews

    def fail(messages, info):
        raise error

    with review_agent.override(model=FunctionModel(fail)):
        response = generate(client, owner_headers, chat_id)
    assert response.status_code == expected
    assert "private" not in response.text
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).messages == original_messages
        assert session.get(Chat, chat_id).reviews == original_reviews


@pytest.mark.parametrize("content", [
    {"title": " ", "summary": "Synthèse", "articles": []},
    {"title": "Revue", "summary": "Synthèse", "articles": [{"title": "Article", "summary": "Résumé", "url": "https://invented.example/article"}]},
    {"title": "Revue", "summary": "Voir https://invented.example/article", "articles": []},
])
def test_invalid_or_invented_output_is_not_saved(client, owner_headers, content):
    chat_id = started_chat(client, owner_headers)

    def invalid(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, content, tool_call_id="invalid-review")])

    with review_agent.override(model=FunctionModel(invalid)):
        assert generate(client, owner_headers, chat_id).status_code == 502
    assert client.get("/reviews", headers=owner_headers).json() == []


def test_concurrent_change_prevents_overwrite(client, owner_headers):
    chat_id = started_chat(client, owner_headers)

    def change(messages, info):
        with Session(database.engine) as session:
            chat = session.get(Chat, chat_id)
            chat.revision += 1
            chat.title = "Discussion modifiée"
            session.add(chat)
            session.commit()
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "title": "Revue", "summary": "Synthèse", "articles": [],
        }, tool_call_id="conflict")])

    with review_agent.override(model=FunctionModel(change)):
        assert generate(client, owner_headers, chat_id).status_code == 409
    with Session(database.engine) as session:
        assert session.get(Chat, chat_id).reviews == []
        assert session.get(Chat, chat_id).title == "Discussion modifiée"


def test_additive_migration_preserves_old_chat_and_is_repeatable():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE chat (id INTEGER PRIMARY KEY, messages JSON NOT NULL)"))
        connection.execute(text("INSERT INTO chat (id, messages) VALUES (1, :messages)"), {"messages": '[{"saved":true}]'})
    ensure_chat_columns(engine)
    ensure_chat_columns(engine)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT messages, reviews, loaded_articles, article_documents FROM chat WHERE id=1")).one()
        assert json.loads(row.messages) == [{"saved": True}]
        assert json.loads(row.reviews) == []
        assert json.loads(row.loaded_articles) == []
        assert json.loads(row.article_documents) == []
        assert sum(column["name"] == "reviews" for column in inspect(connection).get_columns("chat")) == 1
    engine.dispose()
