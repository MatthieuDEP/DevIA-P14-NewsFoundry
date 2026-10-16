import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import models as ai_models
from pydantic_ai.models.test import TestModel
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
with patch.dict(os.environ, {"DATABASE_URL": "sqlite://"}):
    import database
    from main import app
    from chat_agent import chat_agent
    from review_agent import review_agent
    from models import User

TEST_SECRET = "chat-tests-secret-not-for-production-123456"


@pytest.fixture(scope="session")
def password_hashes():
    # Les hashes sont réutilisables ; les comptes et leurs bases restent isolés.
    return {
        "owner": bcrypt.hashpw(b"test", bcrypt.gensalt()).decode(),
        "other": bcrypt.hashpw(b"other", bcrypt.gensalt()).decode(),
    }


def auth_headers(user_id):
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)},
        TEST_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def no_external_llm_requests(monkeypatch):
    monkeypatch.setattr(ai_models, "ALLOW_MODEL_REQUESTS", False)
    from embeddings import MistralEmbedding

    def forbid_embeddings(*args, **kwargs):
        raise AssertionError("Les tests doivent simuler les embeddings Mistral.")

    monkeypatch.setattr(MistralEmbedding, "_get_text_embeddings", forbid_embeddings)
    monkeypatch.setattr(MistralEmbedding, "_aget_text_embeddings", forbid_embeddings)


@pytest.fixture
def client(monkeypatch, password_hashes):
    from unittest.mock import AsyncMock
    import chat_agent as agent_module
    monkeypatch.setattr(agent_module, "fetch_top_news", AsyncMock(return_value={
        "date": "2026-10-10",
        "articles": [{"title": "Actualité de test", "summary": "Résumé de test."}],
    }))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    # Le démarrage et /login sont testés séparément dans test_auth.py.
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(email="test@test.com", hashed_password=password_hashes["owner"]))
        session.commit()
    with chat_agent.override(model=TestModel(call_tools=[], custom_output_text="Voici une réponse de test.")):
        with review_agent.override(model=TestModel(custom_output_args={
            "title": "Revue de presse de test", "summary": "Synthèse issue de la discussion.",
            "articles": [{"title": "Article de test", "summary": "Résumé de test.", "url": None}],
        })), TestClient(app) as client:
            yield client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def owner_headers(client):
    return auth_headers(1)


@pytest.fixture
def other_headers(client, password_hashes):
    with Session(database.engine) as session:
        user = User(email="other@example.com", hashed_password=password_hashes["other"])
        session.add(user)
        session.commit()
        session.refresh(user)
        return auth_headers(user.id)
