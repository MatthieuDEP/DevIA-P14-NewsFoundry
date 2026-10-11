import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import models as ai_models
from pydantic_ai.models.test import TestModel
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
with patch.dict(os.environ, {"DATABASE_URL": "sqlite://"}):
    import database
    from main import app
    from chat_agent import chat_agent


@pytest.fixture(autouse=True)
def no_external_llm_requests(monkeypatch):
    monkeypatch.setattr(ai_models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def client(monkeypatch):
    from unittest.mock import AsyncMock
    import chat_agent as agent_module
    monkeypatch.setattr(agent_module, "fetch_top_news", AsyncMock(return_value={
        "date": "2026-10-10",
        "articles": [{"title": "Actualité de test", "summary": "Résumé de test."}],
    }))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setenv("JWT_SECRET_KEY", "chat-tests-secret-not-for-production-123456")
    database.init_db()
    with chat_agent.override(model=TestModel(call_tools=[], custom_output_text="Voici une réponse de test.")):
        with TestClient(app) as client:
            yield client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def owner_headers(client):
    token = client.post("/login", json={"email": "test@test.com", "password": "test"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_headers(client):
    import bcrypt
    from sqlmodel import Session
    from models import User

    with Session(database.engine) as session:
        session.add(User(email="other@example.com", hashed_password=bcrypt.hashpw(b"other", bcrypt.gensalt()).decode()))
        session.commit()
    token = client.post("/login", json={"email": "other@example.com", "password": "other"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
