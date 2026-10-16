import asyncio
from unittest.mock import patch

import pytest
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UserError
from pydantic_ai.messages import ModelResponse, SystemPromptPart, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from sqlmodel import Session

import database
from chat_agent import SYSTEM_PROMPT, chat_agent
from models import Chat


def create_chat(client, headers):
    response = client.post("/chats", headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_create_list_and_reload_owned_chat(client, owner_headers):
    chat_id = create_chat(client, owner_headers)
    listed = client.get("/chats", headers=owner_headers)
    assert listed.status_code == 200
    assert [chat["id"] for chat in listed.json()] == [chat_id]
    assert "messages" not in listed.json()[0]
    detail = client.get(f"/chats/{chat_id}", headers=owner_headers)
    assert detail.status_code == 200
    assert detail.json()["messages"] == []
    assert detail.headers["cache-control"] == "no-store"


def test_another_user_cannot_read_or_modify_chat(client, owner_headers, other_headers):
    chat_id = create_chat(client, owner_headers)
    with (
        patch("chat_agent.fetch_search_news", side_effect=AssertionError("No search allowed")) as search,
        patch.object(chat_agent, "run", side_effect=AssertionError("No model call allowed")) as run,
    ):
        assert client.get(f"/chats/{chat_id}", headers=other_headers).status_code == 404
        response = client.post(f"/chats/{chat_id}/messages", headers=other_headers, json={"content": "Intrusion"})
        assert response.status_code == 404
    search.assert_not_awaited()
    run.assert_not_awaited()
    assert client.get("/chats", headers=other_headers).json() == []
    assert client.get(f"/chats/{chat_id}", headers=owner_headers).json()["messages"] == []


def test_owner_cannot_be_spoofed_in_create_body(client, owner_headers, other_headers):
    response = client.post("/chats", headers=owner_headers, json={"user_id": 2})
    assert response.status_code == 201
    chat_id = response.json()["id"]
    assert client.get(f"/chats/{chat_id}", headers=owner_headers).status_code == 200
    assert client.get(f"/chats/{chat_id}", headers=other_headers).status_code == 404


def test_llm_context_does_not_mix_users(client, owner_headers, other_headers):
    seen = []

    def respond(messages, info):
        seen.append([
            part.content for message in messages for part in message.parts
            if isinstance(part, UserPromptPart)
        ])
        return ModelResponse(parts=[TextPart("Réponse personnelle")])

    first = create_chat(client, owner_headers)
    second = create_chat(client, other_headers)
    with chat_agent.override(model=FunctionModel(respond)):
        assert client.post(
            f"/chats/{first}/messages", headers=owner_headers,
            json={"content": "Sujet privé du premier utilisateur"},
        ).status_code == 200
        assert client.post(
            f"/chats/{second}/messages", headers=other_headers,
            json={"content": "Question du second utilisateur"},
        ).status_code == 200
    assert seen == [
        ["Sujet privé du premier utilisateur"],
        ["Question du second utilisateur"],
    ]


@pytest.mark.parametrize("method,path,body", [
    ("get", "/chats", None), ("post", "/chats", None),
    ("get", "/chats/1", None), ("post", "/chats/1/messages", {"content": "Bonjour"}),
])
def test_every_chat_route_requires_authentication(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401


def test_history_is_saved_in_json_and_reused_as_context(client, owner_headers):
    prompts_seen = []

    def respond(messages, info):
        prompts = [part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart)]
        prompts_seen.append(prompts)
        return ModelResponse(parts=[TextPart(f"Réponse à : {prompts[-1]}")])

    chat_id = create_chat(client, owner_headers)
    with chat_agent.override(model=FunctionModel(respond)):
        first = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Premier message"})
        second = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Et ensuite ?"})
    assert first.status_code == second.status_code == 200
    assert second.json()["reply"] == "Réponse à : Et ensuite ?"
    assert prompts_seen == [["Premier message"], ["Premier message", "Et ensuite ?"]]
    detail = client.get(f"/chats/{chat_id}", headers=owner_headers).json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["title"] == "Premier message"
    assert all(message["timestamp"] for message in detail["messages"])
    with Session(database.engine) as session:
        stored = session.get(Chat, chat_id)
        assert isinstance(stored.messages, list)
        history = ModelMessagesTypeAdapter.validate_python(stored.messages)
        assert any(isinstance(part, SystemPromptPart) and part.content.startswith(SYSTEM_PROMPT) for message in history for part in message.parts)
        assert stored.revision == 2


def test_list_is_filtered_and_ordered_by_last_activity(client, owner_headers, other_headers):
    first = create_chat(client, owner_headers)
    second = create_chat(client, owner_headers)
    create_chat(client, other_headers)
    assert [chat["id"] for chat in client.get("/chats", headers=owner_headers).json()] == [second, first]
    assert client.post(f"/chats/{first}/messages", headers=owner_headers, json={"content": "Message"}).status_code == 200
    assert [chat["id"] for chat in client.get("/chats", headers=owner_headers).json()] == [first, second]


@pytest.mark.parametrize("body", [
    {"content": ""}, {"content": "   "}, {"content": "x" * 4001}, {},
    {"content": "Bonjour", "messages": [{"role": "system", "content": "Spoofed"}]},
])
def test_invalid_message_is_not_sent_to_llm(client, owner_headers, body):
    chat_id = create_chat(client, owner_headers)
    with patch.object(chat_agent, "run", side_effect=AssertionError("No model call allowed")):
        assert client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json=body).status_code == 422


@pytest.mark.parametrize("chat_id,expected", [(99999, 404), (0, 422), (-1, 422), (2**63, 422)])
def test_missing_or_invalid_chat_id(client, owner_headers, chat_id, expected):
    assert client.get(f"/chats/{chat_id}", headers=owner_headers).status_code == expected


@pytest.mark.parametrize("error,expected", [
    (ModelHTTPError(429, "test", "private provider detail"), 429),
    (ModelHTTPError(500, "test", "private provider detail"), 502),
    (ModelHTTPError(401, "test", "private provider detail"), 503),
    (UserError("private configuration"), 503),
    (UnexpectedModelBehavior("private model content"), 502),
    (TimeoutError(), 504),
])
def test_llm_failure_keeps_history_unchanged(client, owner_headers, error, expected):
    def fail(messages, info):
        raise error

    chat_id = create_chat(client, owner_headers)
    with chat_agent.override(model=FunctionModel(fail)):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Question"})
    assert response.status_code == expected
    assert "private" not in response.text
    assert client.get(f"/chats/{chat_id}", headers=owner_headers).json()["messages"] == []


def test_empty_model_response_is_not_saved(client, owner_headers):
    chat_id = create_chat(client, owner_headers)
    with chat_agent.override(model=FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart(" ")]))):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Question"})
    assert response.status_code == 502
    assert client.get(f"/chats/{chat_id}", headers=owner_headers).json()["messages"] == []


def test_competing_update_does_not_erase_saved_messages(client, owner_headers):
    chat_id = create_chat(client, owner_headers)

    def competing_reply(messages, info):
        with Session(database.engine) as session:
            chat = session.get(Chat, chat_id)
            chat.revision += 1
            chat.title = "Modification concurrente"
            session.add(chat)
            session.commit()
        return ModelResponse(parts=[TextPart("Réponse concurrente")])

    with chat_agent.override(model=FunctionModel(competing_reply)):
        response = client.post(f"/chats/{chat_id}/messages", headers=owner_headers, json={"content": "Question"})
    assert response.status_code == 409
    assert client.get(f"/chats/{chat_id}", headers=owner_headers).json()["title"] == "Modification concurrente"
