# NewsFoundry

NewsFoundry permet d'explorer les actualités dans un chat puis de générer des revues de presse sur les sujets abordés. L'application utilise Mistral pour les échanges et la rédaction, World News API pour les sources et LlamaIndex pour sélectionner les passages pertinents des articles complets.

## Fonctionnalités

- Connexion avec un JWT et conservation de la session dans le navigateur.
- Création, consultation et reprise des discussions personnelles.
- Chargement des actualités du jour et recherche de nouveaux articles pendant le chat.
- Génération de revues structurées : titre, synthèse générale et synthèses d'articles.
- Consultation des revues de toutes les discussions, liens vers les sources et copie du contenu.
- Sélection des passages d'articles avec un RAG avant la rédaction de la revue.

## Prérequis

| Outil | Version utilisée par le projet |
| --- | --- |
| Python | 3.13, indiqué dans `backend/.python-version` |
| Node.js | 24, comme dans la CI |
| uv | Gestion des dépendances Python ; la CI utilise 0.9.18 |
| npm | Fourni avec Node.js |
| Docker | Pour PostgreSQL 17 en local et l'image du backend |

Les dépendances Python sont décrites dans `backend/pyproject.toml` et verrouillées dans `backend/uv.lock`. Les dépendances JavaScript sont décrites dans `frontend/package.json` et verrouillées dans `frontend/package-lock.json`.

## Démarrage local

Après avoir cloné le dépôt, suivre la configuration initiale du [backend](backend/README.md#configuration) et démarrer PostgreSQL selon le [guide de la base](backend/README.md#base-de-données-locale). Renseigner les clés Mistral et World News API dans `backend/.env`.

Dans un premier terminal, depuis la racine :

```bash
cd backend
uv sync --frozen
uv run --env-file .env src/main.py
```

Dans un second terminal, depuis la racine :

```bash
cd frontend
npm ci
# À la première installation, créer le fichier de configuration locale :
cp .env.example .env.local
npm run dev
```

`frontend/.env.local` contient `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` pour le développement local. Les paramètres de chaque service sont détaillés dans les [instructions backend](backend/README.md) et [frontend](frontend/README.md).

| Service | Adresse locale |
| --- | --- |
| Frontend | <http://localhost:3000> |
| API | <http://localhost:8000> |
| Documentation interactive FastAPI | <http://localhost:8000/docs> |
| PostgreSQL | `localhost:5434`, port interne Docker `5432` |

Se connecter sur `/connexion` avec **`test@test.com`** et le mot de passe **`test`**. Ce compte est créé au démarrage du backend. Pour essayer le RAG, demander une nouvelle recherche d'articles dans le chat, puis générer une revue sur le sujet exploré.

## Vérifications

### Backend

Depuis la racine du dépôt :

```bash
cd backend
uv sync --frozen
uv run --no-sync pytest -q
```

Les tests utilisent une base SQLite en mémoire et des API simulées. Ils vérifient les autorisations, la persistance des discussions et revues, les appels d'outils, le RAG et les erreurs. Ils ne nécessitent ni clé API ni PostgreSQL démarré.

### Frontend

Depuis la racine du dépôt :

```bash
cd frontend
npm ci
npm run lint
npm run build
```

La [GitHub Action](.github/workflows/ci.yml) exécute ces vérifications sur les pushes et les pull requests visant `main`.

## Documentation

| Guide | Contenu |
| --- | --- |
| [Architecture et choix techniques](docs/architecture.md) | Structure des dossiers, composants, données, parcours et raisons des choix |
| [Backend](backend/README.md) | Configuration, PostgreSQL, lancement, authentification et tests |
| [Frontend](frontend/README.md) | Configuration, composants, lancement et vérifications |
| [Chat et recherche d'articles](docs/chat.md) | Contexte d'actualités, outil World News API, historique et routes |
| [Revues de presse](docs/reviews.md) | Agent spécialisé, sortie structurée, sauvegarde et consultation |
| [RAG](docs/rag.md) | Documents complets, embeddings Mistral, index LlamaIndex et sélection |
| [Regard critique et améliorations](docs/ameliorations.md) | Mesures de performance, qualité des résultats et pistes de réalisation |
| [Déploiement](docs/deploiement.md) | Vercel, Railway, variables et déploiements automatiques |

## Hébergement

Le frontend est accessible sur [NewsFoundry](https://dev-ia-p14-news-foundry.vercel.app/), hébergé sur Vercel. Le backend et PostgreSQL sont hébergés sur Railway. Les services suivent la branche `main` du même dépôt avec `frontend` et `backend` comme répertoires racines respectifs. Le [guide de déploiement](docs/deploiement.md#adresses-de-production) regroupe les adresses de production ; celle de l'API reste à renseigner.
