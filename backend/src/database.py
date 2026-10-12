import os
from models import User
from sqlmodel import SQLModel, Session, create_engine, select
import bcrypt
from migrations import ensure_reviews_column

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def get_session():
    with Session(engine) as session:
        yield session


def normalize_password_hash(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    # Compatibilité avec les hashes binaires insérés par l'ancien seed PostgreSQL.
    if value.startswith("\\x"):
        return bytes.fromhex(value[2:]).decode("utf-8")
    return value


def init_db():
    SQLModel.metadata.create_all(engine)
    ensure_reviews_column(engine)
    print("Database initialized successfully")

    # Creating a default user
    default_email = "test@test.com"
    default_password = "test"

    with Session(engine) as session:
        statement = select(User).where(User.email == default_email)
        user = session.exec(statement).first()

        if not user:
            session.add(
                User(
                    email=default_email,
                    hashed_password=bcrypt.hashpw(
                        default_password.encode("utf-8"), bcrypt.gensalt()
                    ).decode("utf-8"),
                )
            )
            session.commit()
        else:
            normalized_hash = normalize_password_hash(user.hashed_password)
            if normalized_hash != user.hashed_password:
                user.hashed_password = normalized_hash
                session.add(user)
                session.commit()
