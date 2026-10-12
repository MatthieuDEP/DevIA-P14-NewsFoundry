from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, JSON
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    id: Optional[int] = Field(primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str = Field()


def utc_now():
    return datetime.now(timezone.utc)


class Chat(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str = Field(default="Nouvelle discussion", max_length=80)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    messages: list[dict] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False),
    )
    revision: int = Field(default=0)
    reviews: list[dict] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False),
    )
