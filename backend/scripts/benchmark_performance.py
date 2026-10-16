"""Mesures exploratoires : SQLite isolé, corpus fictif et appels Mistral réels.

Les fonctions de production sont chronométrées dans ce processus uniquement.
Aucune discussion utilisateur ni configuration de l'application n'est modifiée.
"""

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
from copy import deepcopy
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend/src"))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "benchmark-only-not-a-production-secret-123456"

from fastapi.testclient import TestClient
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

import database
import embeddings
import rag
import reviews
from chat_agent import SYSTEM_PROMPT
from main import app
from models import Chat
from review_agent import review_agent

TOPIC = "Stockage solaire et batteries électriques"


def corpus(count):
    """Deux sources pertinentes et des distracteurs clairement identifiés."""
    entries = [
        ("Batteries électriques pour le stockage solaire", "Dans ce cas fictif, une installation solaire utilise une batterie de 2 MWh. Le rendement annoncé est de 88 %. Le stockage décale la production vers les heures du soir.", True),
        ("Batteries au sodium et énergie solaire", "Dans ce cas fictif, une batterie au sodium atteint 900 cycles. Sa durée de charge est de trois heures. Elle sert au stockage de la production solaire dans un site industriel.", True),
    ]
    distractors = [
        ("Championnat de football", "Le championnat de football rassemble des équipes. Les entraîneurs préparent les joueurs. Les rencontres sont organisées sur plusieurs journées."),
        ("Apprentissage des mathématiques", "Les élèves étudient les mathématiques. Les enseignants préparent des exercices et les examens. Les classes travaillent en petits groupes."),
        ("Festival de musique", "Un festival accueille des musiciens et des visiteurs. Le programme comprend plusieurs concerts. Les organisateurs préparent les scènes et la billetterie."),
    ]
    for index in range(count - 2):
        title, text = distractors[index % len(distractors)]
        entries.append((f"{title} — dossier {index + 1}", text, False))
    result = []
    for index, (title, content, relevant) in enumerate(entries):
        paragraphs = [
            f"Dossier fictif, partie {section + 1}. {content} "
            "Ce document décrit le contexte, la méthode, les résultats annoncés et les observations de ses auteurs. "
            "La présentation distingue les données fournies et les commentaires. Les lecteurs peuvent comparer les informations entre les sections du dossier."
            for section in range(8)
        ]
        result.append({
            "url": f"https://benchmark.example/article-{index + 1}",
            "title": title, "summary": content, "text": "\n\n".join(paragraphs),
            "published_at": "2026-10-12", "benchmark_relevant": relevant,
        })
    return result


def history(message_count, articles):
    messages = [ModelRequest(parts=[SystemPromptPart(SYSTEM_PROMPT)])]
    groups = [articles[start:start + 5] for start in range(0, len(articles), 5)]
    exchanges = message_count // 2
    for index in range(exchanges):
        messages.append(ModelRequest(parts=[UserPromptPart(
            f"Échange {index + 1}. Explique les enjeux du stockage solaire et des batteries à partir des articles déjà chargés."
        )]))
        for group_index in range(index, len(groups), exchanges):
            tool_id = f"bench{group_index:04d}"
            messages.append(ModelResponse(parts=[ToolCallPart("search_news", {"query": "stockage solaire", "days": 7}, tool_call_id=tool_id)]))
            messages.append(ModelRequest(parts=[ToolReturnPart("search_news", {
                "status": "ok", "query": "stockage solaire",
                "articles": [{key: item[key] for key in ("url", "title", "summary", "published_at")} for item in groups[group_index]],
            }, tool_call_id=tool_id)]))
        messages.append(ModelResponse(parts=[TextPart(
            "La discussion porte sur les batteries et la production solaire. Les sources chargées contiennent deux dossiers sur le stockage et des documents sur d'autres sujets. "
            "La synthèse doit distinguer les faits annoncés par chaque source et citer les articles pertinents. " * 2
        )]))
    return ModelMessagesTypeAdapter.dump_python(messages, mode="json")


def summary(rows):
    result = {}
    for name in sorted({row["scenario"] for row in rows}):
        group = [row for row in rows if row["scenario"] == name]
        valid = [row for row in group if row["ok"]]
        values = [row["total_s"] for row in valid]
        result[name] = {
            "n": len(group), "successes": len(valid), "failures": len(group) - len(valid),
            "mean_s": round(statistics.mean(values), 4) if values else None,
            "median_s": round(statistics.median(values), 4) if values else None,
            "min_s": min(values) if values else None, "max_s": max(values) if values else None,
        }
        for field in ("rag_s", "agent_s", "embedding_s", "index_s", "sql_s", "input_tokens", "output_tokens", "embedding_tokens", "prompt_chars", "nodes", "articles_returned"):
            field_values = [row[field] for row in valid if row.get(field) is not None]
            result[name][f"mean_{field}"] = round(statistics.mean(field_values), 4) if field_values else None
    return result


def measure_review_list(example, repeats):
    """Mesurer le GET existant sur des archives fictives, sans aucun appel LLM."""
    results = []
    for count in (10, 100, 500):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        database.engine = engine
        database.init_db()
        with Session(engine) as session:
            for start in range(0, count, 10):
                items = []
                for index in range(start, min(start + 10, count)):
                    review = deepcopy(example)
                    review.update(id=str(uuid4()), title=f"Revue fictive {index + 1}")
                    review.pop("chat_id", None)
                    review.pop("chat_title", None)
                    items.append(review)
                session.add(Chat(user_id=1, title="Archive fictive", reviews=items))
            session.commit()
        with TestClient(app) as client:
            token = client.post("/login", json={"email": "test@test.com", "password": "test"}).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            times = []
            for _ in range(repeats):
                start = perf_counter()
                response = client.get("/reviews", headers=headers)
                times.append(perf_counter() - start)
                response.raise_for_status()
            saved = response.json()
            assert len(saved) == count
            projection = [{key: item[key] for key in ("id", "title", "topic", "created_at", "chat_id", "chat_title")} for item in saved[:20]]
            results.append({
                "reviews": count, "repeats": repeats,
                "mean_s": round(statistics.mean(times), 6),
                "min_s": round(min(times), 6), "max_s": round(max(times), 6),
                "response_bytes": len(response.content),
                "projection_metadata_20_bytes": len(json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode()),
            })
        engine.dispose()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--measure-list", action="store_true", help="Mesurer aussi GET /reviews sur des archives fictives.")
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 5:
        parser.error("Utiliser entre une et cinq répétitions.")
    if not os.getenv("MISTRAL_API_KEY"):
        parser.error("Configurer MISTRAL_API_KEY dans l'environnement du backend.")
    datasets = {count: corpus(count) for count in (5, 15, 30)}
    payload = {
        "protocol_version": 1,
        "started_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "mistral_model": os.getenv("MISTRAL_MODEL") or "ministral-8b-latest",
            "embedding_model": os.getenv("MISTRAL_EMBEDDING_MODEL") or "mistral-embed",
            "packages": {name: version(name) for name in ("pydantic-ai-slim", "mistralai", "llama-index-core")},
            "source_sha256": hashlib.sha256(b"".join(path.read_bytes() for path in sorted((REPO / "backend/src").glob("*.py")))).hexdigest(),
        },
        "corpus": datasets, "runs": [],
        "notes": "Données fictives, API Mistral réelles, endpoint FastAPI en processus local, SQLite en mémoire. Pas de mesure réseau Railway/Vercel, ni de cold start du serveur.",
    }
    if args.resume and args.output.exists():
        previous = json.loads(args.output.read_text())
        keys = ("source_sha256", "packages", "mistral_model", "embedding_model")
        if any(previous["environment"][key] != payload["environment"][key] for key in keys) or previous["corpus"] != json.loads(json.dumps(datasets)):
            parser.error("Le code, l'environnement ou le corpus a changé ; choisir un autre fichier de sortie.")
        payload = previous

    def save():
        payload["summary"] = summary(payload["runs"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    current = [None]
    original_retrieve = reviews.retrieve_articles
    original_agent = review_agent.run
    original_vectors = embeddings.vectors
    original_embed = embeddings.MistralEmbedding._aget_text_embeddings
    original_split = rag.TokenTextSplitter.get_nodes_from_documents
    original_index = rag.VectorStoreIndex

    async def timed_retrieve(*items, **kwargs):
        start = perf_counter()
        try:
            selected = await original_retrieve(*items, **kwargs)
            current[0]["selected_urls"] = [item["url"] for item in selected]
            return selected
        finally:
            current[0]["rag_s"] += perf_counter() - start

    async def timed_agent(*items, **kwargs):
        start = perf_counter()
        current[0]["prompt_chars"] = len(items[0])
        try:
            result = await original_agent(*items, **kwargs)
            usage = result.usage
            current[0].update(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, model_requests=usage.requests)
            current[0]["resolved_model"] = result.response.model_name
            return result
        finally:
            current[0]["agent_s"] += perf_counter() - start

    async def timed_embed(*items, **kwargs):
        start = perf_counter()
        current[0]["embedding_requests"] += 1
        try:
            return await original_embed(*items, **kwargs)
        finally:
            current[0]["embedding_s"] += perf_counter() - start

    def counted_vectors(response, count):
        current[0]["embedding_vectors"] += count
        current[0]["embedding_tokens"] += getattr(response.usage, "total_tokens", 0) or 0
        return original_vectors(response, count)

    def timed_split(*items, **kwargs):
        start = perf_counter()
        nodes = original_split(*items, **kwargs)
        current[0]["chunk_s"] += perf_counter() - start
        current[0]["nodes"] = len(nodes)
        return nodes

    def timed_index(*items, **kwargs):
        start = perf_counter()
        result = original_index(*items, **kwargs)
        current[0]["index_s"] += perf_counter() - start
        return result

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.engine = engine
    database.init_db()

    @event.listens_for(engine, "before_cursor_execute")
    def sql_before(connection, cursor, statement, parameters, context, executemany):
        context.benchmark_start = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def sql_after(connection, cursor, statement, parameters, context, executemany):
        if current[0] is not None:
            current[0]["sql_s"] += perf_counter() - context.benchmark_start

    scenarios = [
        ("rag-h10-a5", 10, 5, TOPIC, True),
        ("rag-h30-a5", 30, 5, TOPIC, True),
        ("rag-h60-a5", 60, 5, TOPIC, True),
        ("rag-h10-a15", 10, 15, TOPIC, True),
        ("rag-h10-a30", 10, 30, TOPIC, True),
        ("history-h10", 10, 5, TOPIC, False),
        ("no-match-h10-a5", 10, 5, "Recettes de pâtisserie", True),
    ]
    with patch.object(reviews, "retrieve_articles", timed_retrieve), patch.object(review_agent, "run", timed_agent), patch.object(embeddings.MistralEmbedding, "_aget_text_embeddings", timed_embed), patch.object(embeddings, "vectors", counted_vectors), patch.object(rag.TokenTextSplitter, "get_nodes_from_documents", timed_split), patch.object(rag, "VectorStoreIndex", timed_index), TestClient(app) as client:
        token = client.post("/login", json={"email": "test@test.com", "password": "test"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        for repetition in range(1, args.repeats + 1):
            # Inverser l'ordre au deuxième passage pour réduire l'effet de l'ordre des appels.
            ordered = scenarios if repetition % 2 else list(reversed(scenarios))
            for name, size, count, topic, with_rag in ordered:
                if any(row["scenario"] == name and row["repetition"] == repetition for row in payload["runs"]):
                    continue
                articles = datasets[count]
                saved_history = history(size, articles)
                with Session(engine) as session:
                    chat = Chat(user_id=1, title="Discussion fictive de benchmark", messages=saved_history,
                                loaded_articles=[item["url"] for item in articles], article_documents=articles if with_rag else [])
                    session.add(chat)
                    session.commit()
                    chat_id = chat.id
                row = {
                    "scenario": name, "repetition": repetition, "messages": size, "corpus_articles": count,
                    "topic": topic, "recorded_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
                    "history_chars": len(json.dumps(saved_history, ensure_ascii=False)),
                    "corpus_chars": sum(len(item["text"]) for item in articles),
                    "rag_s": 0.0, "agent_s": 0.0, "embedding_s": 0.0, "index_s": 0.0, "chunk_s": 0.0, "sql_s": 0.0,
                    "embedding_requests": 0, "embedding_vectors": 0, "embedding_tokens": 0,
                    "input_tokens": None, "output_tokens": None, "model_requests": None, "prompt_chars": None, "nodes": 0,
                }
                current[0] = row
                start = perf_counter()
                try:
                    response = client.post(f"/chats/{chat_id}/reviews", headers=headers, json={"topic": topic})
                    row["http_status"] = response.status_code
                    row["ok"] = response.status_code == 201
                    if row["ok"]:
                        output = response.json()
                        row["source_mode"] = output["source_mode"]
                        row["articles_returned"] = len(output["articles"])
                        urls = {article["url"] for article in output["articles"]}
                        expected = {article["url"] for article in articles if article["benchmark_relevant"]} if topic == TOPIC else set()
                        row["source_precision"] = len(urls & expected) / len(urls) if urls else None
                        row["source_recall"] = len(urls & expected) / len(expected) if expected else None
                        row["unknown_urls"] = len(urls - {article["url"] for article in articles})
                        row["output"] = output
                    else:
                        row["error"] = response.json().get("detail")
                except Exception as error:
                    row.update(ok=False, error_type=type(error).__name__)
                finally:
                    row["total_s"] = perf_counter() - start
                    current[0] = None
                for field in ("total_s", "rag_s", "agent_s", "embedding_s", "index_s", "chunk_s", "sql_s"):
                    row[field] = round(row[field], 6)
                payload["runs"].append(row)
                save()
                print(f"{name} #{repetition}: {row['total_s']:.3f}s, HTTP {row.get('http_status')}, mode={row.get('source_mode')}, articles={row.get('articles_returned')}", flush=True)
                if "error_type" in row:
                    raise RuntimeError(f"Mesure interrompue : erreur d'exécution {row['error_type']}. Vérifier le script avant de relancer.")
    engine.dispose()
    if args.measure_list:
        example = next(row["output"] for row in payload["runs"] if row.get("ok") and row.get("source_mode") == "full_text")
        payload["review_list"] = measure_review_list(example, args.repeats)
    payload["finished_at"] = datetime.now(ZoneInfo("Europe/Paris")).isoformat()
    save()
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
