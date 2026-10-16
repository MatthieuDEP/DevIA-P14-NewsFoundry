# NewsFoundry Backend

API FastAPI en Python 3.13, avec SQLModel/PostgreSQL, agents PydanticAI Mistral et RAG LlamaIndex. Voir le [guide d'architecture](../docs/architecture.md) pour le rôle des fichiers et les raisons des choix.

## Configuration

Depuis le dossier `backend/`, à la première installation :

```bash
uv sync --frozen
cp .env.example .env
```

Compléter `backend/.env` à partir de cet exemple :

| Variable | Rôle et valeur locale |
| --- | --- |
| `DATABASE_URL` | Connexion PostgreSQL ; l'exemple utilise `postgresql://user:password@localhost:5434/newsfoundry` |
| `JWT_SECRET_KEY` | Clé de signature du JWT, d'au moins 32 octets |
| `CORS_ORIGINS` | Origines du frontend, séparées par des virgules ; valeurs locales `http://localhost:3000,http://127.0.0.1:3000` |
| `MISTRAL_API_KEY` | Clé privée utilisée pour les agents et les embeddings |
| `MISTRAL_MODEL` | Modèle du chat et de la rédaction ; défaut `ministral-8b-latest` |
| `MISTRAL_EMBEDDING_MODEL` | Modèle d'embedding ; défaut `mistral-embed` |
| `WORLD_NEWS_API_KEY` | Clé privée utilisée pour les actualités et les recherches |
| `PORT` | Port HTTP ; défaut `8000`, fourni par Railway en production |

Générer la clé JWT :

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Renseigner le résultat dans `JWT_SECRET_KEY` et conserver cette valeur entre les démarrages. Les fichiers `.env` locaux sont ignorés par Git. Les variables de production sont renseignées dans Railway.

## Base de données locale

Créer PostgreSQL une première fois :

```bash
docker run -d \
  --name newsfoundry_db \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=newsfoundry \
  -p 127.0.0.1:5434:5432 \
  postgres:17
```

Pour démarrer un conteneur existant, notamment après un redémarrage de l'ordinateur :

```bash
docker start newsfoundry_db
```

PostgreSQL est accessible sur `localhost:5434` ; son port interne reste `5432`. `DATABASE_URL` doit correspondre aux paramètres du conteneur.

## Lancement

Depuis `backend/` :

```bash
uv run --env-file .env src/main.py
```

L'API est accessible sur <http://localhost:8000> et sa documentation interactive sur <http://localhost:8000/docs>. La route `/` sert au contrôle de disponibilité du service.

Le démarrage crée les tables, applique les migrations additives de `migrations.py` et crée le compte de test si nécessaire. Les migrations ajoutent les champs JSON aux anciennes bases en conservant les discussions et revues existantes.

## Authentification

Le compte de test est **`test@test.com`**, avec le mot de passe **`test`**. Le mot de passe est vérifié avec bcrypt ; le token JWT est signé en HS256 et expire après une heure.

`POST /login` reçoit `{"email":"test@test.com","password":"test"}` et retourne `access_token` et `token_type`. Le frontend conserve le JWT et le transmet dans `Authorization: Bearer <token>`. `GET /me` vérifie la session et retourne uniquement l'identifiant et l'email.

Les routes protégées utilisent l'utilisateur issu du JWT et filtrent le propriétaire des discussions dans les requêtes SQL. Les mots de passe et les clés des services ne sont pas recopiés dans les erreurs publiques.

## Routes

| Méthode | Route | Fonction | JWT requis |
| --- | --- | --- | --- |
| `GET` | `/` | Disponibilité de l'API | Non |
| `POST` | `/login` | Connexion | Non |
| `GET` | `/me` | Vérification de session | Oui |
| `POST` | `/chats` | Création d'une discussion et de son contexte d'actualités | Oui |
| `GET` | `/chats` | Liste des discussions personnelles | Oui |
| `GET` | `/chats/{id}` | Historique visible d'une discussion | Oui |
| `POST` | `/chats/{id}/messages` | Envoi d'un message et réponse de l'agent | Oui |
| `POST` | `/chats/{id}/reviews` | Génération d'une revue sur un sujet | Oui |
| `GET` | `/reviews` | Revues des discussions de l'utilisateur | Oui |

`/top-news` et `/search-news` sont des routes externes de World News API appelées par `news.py`. L'outil `search_news` est une fonction PydanticAI exécutée dans le backend pendant un échange.

## Fonctionnement des agents

Le chat sauvegarde le contexte initial, les messages et les appels d'outils dans `Chat.messages`. Les recherches conservent aussi les URLs et les documents complets, séparément des extraits transmis au modèle.

La revue est produite par un agent spécialisé, avec une sortie PydanticAI structurée. Quand des textes complets sont disponibles, LlamaIndex sélectionne les passages proches du sujet avec les embeddings Mistral. Les liens sont validés puis la revue est enregistrée dans `Chat.reviews`.

Guides détaillés : [chat et outils](../docs/chat.md), [revues de presse](../docs/reviews.md), [RAG](../docs/rag.md).

## Tests

Depuis `backend/` :

```bash
uv sync --frozen
uv run --no-sync pytest -q
```

Les tests utilisent SQLite en mémoire. `TestModel`, `FunctionModel`, des réponses HTTP simulées et des embeddings déterministes couvrent l'authentification, les autorisations, les discussions, les outils, les revues, le RAG et les erreurs. Ils ne nécessitent ni clés API ni PostgreSQL démarré.

La [GitHub Action](../.github/workflows/ci.yml) lance ces tests ainsi que le lint et la compilation du frontend sur les pushes et pull requests visant `main`.

## Déploiement

Railway construit l'image depuis `backend/Dockerfile`, avec `backend/` comme contexte. Les dépendances de production sont installées depuis `uv.lock` avec `--frozen --no-dev`.

Depuis la racine du dépôt, vérifier la construction locale :

```bash
docker build -t newsfoundry-backend ./backend
```

Le [guide de déploiement](../docs/deploiement.md) décrit PostgreSQL, les variables Railway, le domaine public et les déploiements automatiques.
