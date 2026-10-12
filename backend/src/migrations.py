"""Migrations additives des champs JSON, sans supprimer les anciennes discussions."""

from sqlalchemy import inspect, text


def ensure_chat_columns(engine):
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("chat")}
        # PostgreSQL permet aussi deux démarrages simultanés sans ajouter deux fois la colonne.
        condition = "IF NOT EXISTS " if engine.dialect.name == "postgresql" else ""
        for name in ("reviews", "loaded_articles", "article_documents"):
            if name not in columns:
                connection.execute(text(
                    f"ALTER TABLE chat ADD COLUMN {condition}{name} JSON NOT NULL DEFAULT '[]'"
                ))
