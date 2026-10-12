import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded, UserError
from pydantic_ai.usage import UsageLimits
from sqlalchemy import update
from sqlmodel import Session, select

from auth import get_current_user
from chats import owned_chat
from database import get_session
from models import Chat, User, utc_now
from review_agent import review_agent, review_prompt, source_urls

router = APIRouter(tags=["Revues de presse"])
ChatId = Annotated[int, Path(gt=0, le=2**63 - 1)]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    topic: str = Field(min_length=2, max_length=200)


@router.get("/reviews")
def list_reviews(
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.exec(
        select(Chat.id, Chat.title, Chat.reviews).where(Chat.user_id == user.id)
    ).all()
    reviews = [
        {**review, "chat_id": chat_id, "chat_title": title}
        for chat_id, title, items in rows for review in items
    ]
    response.headers["Cache-Control"] = "no-store"
    return sorted(reviews, key=lambda review: (review["created_at"], review["id"]), reverse=True)


@router.post("/chats/{chat_id}/reviews", status_code=201)
async def generate_review(
    chat_id: ChatId,
    body: ReviewRequest,
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    chat = owned_chat(chat_id, user.id, session)
    owner_id, revision = user.id, chat.revision
    history, previous = chat.messages, chat.reviews
    title = chat.title
    if not any(part.get("part_kind") == "user-prompt" for message in history for part in message.get("parts", [])):
        raise HTTPException(422, "Échangez d’abord sur un sujet dans cette discussion.")
    session.rollback()
    try:
        result = await asyncio.wait_for(review_agent.run(
            review_prompt(body.topic, history), deps=source_urls(history),
            usage_limits=UsageLimits(request_limit=3),
        ), timeout=50)
    except TimeoutError:
        raise HTTPException(504, "La génération de la revue prend trop de temps. Réessayez.") from None
    except ModelHTTPError as error:
        if error.status_code == 429:
            raise HTTPException(429, "La génération est très sollicitée. Réessayez dans quelques instants.") from None
        status = 503 if error.status_code in (401, 403) else 502
        raise HTTPException(status, "La revue n’a pas pu être générée. Réessayez.") from None
    except UserError:
        raise HTTPException(503, "La génération est temporairement indisponible.") from None
    except (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded):
        raise HTTPException(502, "La revue n’a pas pu être générée. Réessayez.") from None

    created_at = utc_now()
    review = {
        **result.output.model_dump(mode="json"),
        "id": str(uuid4()), "topic": body.topic,
        "created_at": created_at.isoformat(), "chat_revision": revision,
    }
    # Ne pas écraser une revue concurrente ni sauvegarder une synthèse d'un chat modifié.
    changed = session.execute(
        update(Chat)
        .where(Chat.id == chat_id, Chat.user_id == owner_id, Chat.revision == revision)
        .values(reviews=[*previous, review], updated_at=created_at, revision=revision + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "La discussion a changé. Rechargez-la avant de générer la revue.")
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return {**review, "chat_id": chat_id, "chat_title": title}
