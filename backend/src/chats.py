import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded, UserError
from pydantic_ai.usage import UsageLimits
from sqlalchemy import update
from sqlmodel import Session, select

from auth import get_current_user
from chat_agent import ChatDocuments, as_utc, chat_agent, initial_history, public_messages
from database import get_session
from models import Chat, User, utc_now

router = APIRouter(prefix="/chats", tags=["Discussions"])
logger = logging.getLogger(__name__)
ChatId = Annotated[int, Path(gt=0, le=2**63 - 1)]


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Le message ne peut pas être vide.")
        return value


def owned_chat(chat_id, user_id, session):
    # Contrôler l'appartenance dans la requête SQL pour chaque lecture et écriture.
    chat = session.exec(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    ).first()
    if chat is None:
        raise HTTPException(404, "Discussion introuvable.")
    return chat


def chat_info(chat):
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": as_utc(chat.created_at),
        "updated_at": as_utc(chat.updated_at),
    }


@router.post("", status_code=201)
async def create_chat(
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    owner_id = user.id
    session.rollback()
    history = await initial_history()
    chat = Chat(
        user_id=owner_id,
        messages=ModelMessagesTypeAdapter.dump_python(history, mode="json"),
    )
    session.add(chat)
    session.commit()
    session.refresh(chat)
    response.headers["Cache-Control"] = "no-store"
    return {**chat_info(chat), "messages": []}


@router.get("")
def list_chats(
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # La barre latérale n'a pas besoin de charger les historiques JSON complets.
    rows = session.exec(
        select(Chat.id, Chat.title, Chat.created_at, Chat.updated_at)
        .where(Chat.user_id == user.id)
        .order_by(Chat.updated_at.desc(), Chat.id.desc())
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return [
        {"id": id, "title": title, "created_at": as_utc(created), "updated_at": as_utc(updated)}
        for id, title, created, updated in rows
    ]


@router.get("/{chat_id}")
def get_chat(
    chat_id: ChatId,
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    chat = owned_chat(chat_id, user.id, session)
    history = ModelMessagesTypeAdapter.validate_python(chat.messages)
    response.headers["Cache-Control"] = "no-store"
    return {**chat_info(chat), "messages": public_messages(history)}


@router.post("/{chat_id}/messages")
async def add_message(
    chat_id: ChatId,
    body: MessageRequest,
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    chat = owned_chat(chat_id, user.id, session)
    owner_id, revision = user.id, chat.revision
    title, created_at = chat.title, chat.created_at
    previous_documents = chat.article_documents
    documents = ChatDocuments()
    history = ModelMessagesTypeAdapter.validate_python(chat.messages)
    # Libérer la connexion de lecture pendant l'attente réseau du modèle.
    session.rollback()
    # Une discussion vide créée avant l'ajout des actualités reçoit aussi un contexte.
    if not history:
        history = await initial_history()
    try:
        result = await asyncio.wait_for(
            chat_agent.run(
                body.content, message_history=history, deps=documents,
                usage_limits=UsageLimits(request_limit=5, tool_calls_limit=3),
            ), timeout=50,
        )
    except TimeoutError:
        raise HTTPException(504, "L’assistant met trop de temps à répondre. Réessayez.") from None
    except ModelHTTPError as exc:
        logger.warning("Erreur du fournisseur IA, statut %s", exc.status_code)
        if exc.status_code == 429:
            raise HTTPException(429, "L’assistant est très sollicité. Réessayez dans quelques instants.") from None
        status = 503 if exc.status_code in (401, 403) else 502
        raise HTTPException(status, "L’assistant est temporairement indisponible. Réessayez.") from None
    except UserError:
        raise HTTPException(503, "L’assistant est temporairement indisponible. Réessayez.") from None
    except UsageLimitExceeded:
        raise HTTPException(502, "La recherche a atteint sa limite. Essayez une question plus précise.") from None
    except (ModelAPIError, UnexpectedModelBehavior):
        raise HTTPException(502, "L’assistant n’a pas pu répondre. Réessayez.") from None

    if not result.output.strip():
        raise HTTPException(502, "L’assistant n’a pas pu répondre. Réessayez.")
    saved_history = ModelMessagesTypeAdapter.dump_python(result.all_messages(), mode="json")
    updated_at = utc_now()
    # Dédupliquer les sources et garder le dernier contenu chargé pour une même URL.
    merged_documents = {article["url"]: article for article in previous_documents}
    merged_documents.update({article["url"]: article for article in documents.articles})
    if not any(isinstance(part, UserPromptPart) for message in history for part in message.parts):
        title = body.content[:80]
    # Une seconde requête ne doit pas écraser un échange enregistré entre-temps.
    changed = session.execute(
        update(Chat)
        .where(Chat.id == chat_id, Chat.user_id == owner_id, Chat.revision == revision)
        .values(
            messages=saved_history, title=title, updated_at=updated_at, revision=revision + 1,
            loaded_articles=list(merged_documents), article_documents=list(merged_documents.values()),
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "La discussion a été mise à jour. Rechargez-la avant de réessayer.")
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return {
        "id": chat_id, "title": title,
        "created_at": as_utc(created_at), "updated_at": updated_at,
        "messages": public_messages(result.all_messages()),
        "reply": result.output,
    }
