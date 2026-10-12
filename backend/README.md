# NewsFoundry Backend

1. Copier le fichier `.env.example` dans `.env`


2. Installer les dépendances:
```bash
uv sync
```

2. Démarrer la base de données:
```bash
docker run \
  --name newsfoundry_db \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=newsfoundry \
  -p 127.0.0.1:5434:5432 \
  postgres:17
```

PostgreSQL est accessible sur `localhost:5434`. Le port interne du conteneur reste `5432`.

3. Lancer le backend:
```bash
uv run --env-file .env src/main.py
```

## Connexion

L'utilisateur de test est `test@test.com`, avec le mot de passe `test`.

Ajouter dans `.env` :

```text
JWT_SECRET_KEY=<clé aléatoire>
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

Générer la clé avec `python3 -c "import secrets; print(secrets.token_hex(32))"`. Elle doit rester stable entre les redémarrages et ne doit pas être commitée. Une clé locale a déjà été générée pour ce poste.

`POST /login` reçoit un JSON avec `email` et `password` et retourne `access_token` et `token_type`. Le JWT est signé en HS256 et expire après une heure. `GET /me` vérifie le token transmis dans `Authorization: Bearer <token>` et retourne uniquement l'identifiant et l'email.

| Statut | Signification |
| --- | --- |
| `401` | Identifiants incorrects ou session invalide/expirée |
| `422` | Champs de connexion invalides |
| `503` | Base indisponible ou clé JWT non configurée |

Les hashes bcrypt sont conservés dans la base, sans journalisation SQL des paramètres. Les anciennes valeurs binaires du compte de test sont normalisées en texte au démarrage, sans changer son mot de passe.

## Tests

```bash
uv sync --frozen
uv run --no-sync pytest -q
```

Les tests utilisent SQLite en mémoire et couvrent l'authentification, les discussions et leurs autorisations. `TestModel` et `FunctionModel` remplacent Mistral, sans appels facturés. La GitHub Action `.github/workflows/ci.yml` exécute les tests, le lint et la compilation frontend.

Sur Railway, ajouter `JWT_SECRET_KEY` avec une clé propre à la production et `CORS_ORIGINS` avec l'origine exacte du frontend Vercel. La variable `DATABASE_URL` reste configurée comme auparavant.

## Chat Mistral

Configurer `MISTRAL_API_KEY` dans `.env`, puis redémarrer le backend. Le modèle par défaut est `ministral-8b-latest`, configurable via `MISTRAL_MODEL`. La table `Chat` est créée au démarrage sans supprimer les données existantes.

Les routes `/chats` et `/chats/{id}/messages` vérifient le JWT et le propriétaire de la discussion. Voir le [guide du chat](../docs/chat.md) pour le prompt, les routes, les erreurs et les tests.

## Actualités World News API

Configurer `WORLD_NEWS_API_KEY` dans `.env` et dans Railway, puis redémarrer le backend. À la création d'une discussion, `/top-news` charge les actualités françaises du jour (date en Europe/Paris). Le prompt contient jusqu'à dix titres et résumés, et reste enregistré dans le champ JSON `Chat.messages` pour toute la discussion. Aucune migration n'est nécessaire.

Une ancienne discussion conserve son contexte d'origine ; créer une nouvelle discussion pour charger le contexte du jour ou demander à l'agent de rechercher de nouveaux articles. En cas de clé absente, quota dépassé ou actualités indisponibles, l'application affiche une erreur sans créer une discussion incomplète. Les tests simulent World News API avec `httpx.MockTransport`, sans consommer son quota.

## Outil de recherche d'articles

L'agent Mistral peut appeler `search_news(query, days=7)` pour approfondir un sujet avec `/search-news`. Il reçoit jusqu'à cinq articles récents en français, avec résumé, extrait, lien et date disponibles, puis répond en citant les sources. Les arguments sont validés et chaque message est limité à trois recherches. L'outil utilise la même `WORLD_NEWS_API_KEY` que les actualités initiales.

Les appels d'outil et les résultats sont conservés dans l'historique JSON, sans modifier le prompt initial. Ils restent disponibles lors d'une reprise, y compris dans une ancienne discussion. Les tests `FunctionModel` vérifient l'exécution de la recherche, l'utilisation des articles, leur persistance et les autorisations. Voir le [guide du chat](../docs/chat.md).

## Revues de presse

`POST /chats/{id}/reviews` génère une revue sur un sujet à partir de l'historique sauvegardé. Un agent Mistral spécialisé, sans outil de recherche, fournit une sortie PydanticAI structurée : titre, synthèse générale et synthèses d'articles. Les revues sont conservées dans `Chat.reviews` et `GET /reviews` retourne uniquement celles de l'utilisateur connecté.

Redémarrer le backend applique une migration additive pour ajouter le champ aux anciennes bases. Voir le [guide des revues de presse](../docs/reviews.md) pour les routes, le stockage, le prompt, les erreurs et les tests.

## RAG sur les articles complets

Les recherches conservent leurs URLs dans `Chat.loaded_articles` et leurs textes complets dans `Chat.article_documents`. Avant une revue, LlamaIndex crée un index temporaire et sélectionne les passages proches du sujet avec les embeddings Mistral. L'agent synthétise les sources retenues et ses liens sont validés. La clé Mistral existante suffit ; `MISTRAL_EMBEDDING_MODEL` vaut `mistral-embed` par défaut.

Les anciennes discussions restent utilisables et signalent une revue fondée sur l'historique tant qu'aucune nouvelle recherche n'a chargé de texte complet. Le redémarrage du backend ajoute les champs nécessaires sans supprimer les données. Voir le [guide RAG](../docs/rag.md).
