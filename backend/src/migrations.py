"""Petite migration additive pour les bases créées avant les revues de presse."""

from sqlalchemy import inspect, text


def ensure_reviews_column(engine):
    with engine.begin() as connection:
        columns = inspect(connection).get_columns("chat")
        if any(column["name"] == "reviews" for column in columns):
            return
        # PostgreSQL permet aussi deux démarrages simultanés sans ajouter deux fois la colonne.
        condition = "IF NOT EXISTS " if engine.dialect.name == "postgresql" else ""
        connection.execute(text(
            f"ALTER TABLE chat ADD COLUMN {condition}reviews JSON NOT NULL DEFAULT '[]'"
        ))
