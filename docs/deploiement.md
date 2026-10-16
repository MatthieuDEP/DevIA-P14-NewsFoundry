# Déploiement de NewsFoundry

Le même dépôt GitHub alimente deux déploiements : le frontend sur Vercel et le backend sur Railway. PostgreSQL est hébergé dans le même projet Railway que le backend.

## Adresses de production

- Frontend Vercel : [NewsFoundry](https://dev-ia-p14-news-foundry.vercel.app/).
- API Railway : à renseigner ultérieurement.

L'adresse publique de l'API sera complétée ultérieurement. Le [guide d'architecture](architecture.md) décrit les échanges entre ces services.

## Préparer le dépôt

1. Pousser les fichiers du projet sur la branche `main` du dépôt GitHub.
2. Autoriser les intégrations GitHub de Vercel et Railway à accéder au dépôt.

Les fichiers `.env` locaux ne sont pas publiés. Les variables de production sont configurées dans les plateformes.

## Railway : PostgreSQL et backend

### Créer les services

1. Créer un projet Railway.
2. Ajouter un service PostgreSQL et attendre qu'il soit disponible.
3. Ajouter un service vide nommé `backend` pour configurer la racine et les variables avant le premier démarrage.

### Configurer le backend

| Réglage | Valeur |
| --- | --- |
| Root Directory | `/backend` |
| Branche de déploiement | `main` |
| Autodeploy | Activé |
| Construction | Dockerfile détecté dans `/backend` |
| Start Command | Conserver la commande du Dockerfile |
| Healthcheck Path | `/` |
| Watch Paths | Aucun filtre, pour déployer à chaque push sur `main` |

Dans l'onglet **Variables** du backend, ajouter :

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
JWT_SECRET_KEY=<clé aléatoire propre à la production>
CORS_ORIGINS=https://<domaine-du-frontend-vercel>
MISTRAL_API_KEY=<clé privée Mistral>
MISTRAL_MODEL=ministral-8b-latest
MISTRAL_EMBEDDING_MODEL=mistral-embed
WORLD_NEWS_API_KEY=<clé privée World News API>
```

Remplacer `Postgres` par le nom exact du service PostgreSQL. Utiliser la référence proposée par Railway : elle connecte le backend à PostgreSQL via le réseau privé du projet. L'adresse `localhost:5434` de la configuration locale ne s'applique pas sur Railway.

Le backend écoute sur `0.0.0.0` et utilise la variable `PORT` fournie par Railway. En local, sans cette variable, il utilise le port `8000`.

Après avoir configuré la racine et les variables, connecter le service au dépôt GitHub, sélectionner `main` et appliquer les réglages pour lancer le déploiement. La commande du Dockerfile exécute `src/main.py`, qui initialise la base avant de démarrer l'API.

### Rendre l'API accessible

Dans les réglages du service **backend**, ouvrir **Networking → Public Networking**, puis sélectionner **Generate Domain**. Vérifier que le port cible correspond au port d'écoute indiqué dans les logs.

Ouvrir l'URL HTTPS générée. La route `/` doit renvoyer :

```json
{"message":"👋"}
```

La documentation FastAPI est également accessible sur `/docs`. Le service PostgreSQL reste accessible au backend par le réseau privé ; seul le backend a besoin d'un domaine HTTP public.

## Vercel : frontend

1. Importer le même dépôt GitHub dans un nouveau projet Vercel.
2. Configurer les réglages suivants avant le déploiement :

| Réglage | Valeur |
| --- | --- |
| Framework Preset | Next.js |
| Root Directory | `frontend` |
| Install Command | `npm ci` |
| Build Command | `npm run build` |
| Output Directory | Valeur automatique de Next.js |
| Production Branch / Branch Tracking | `main` |
| Skip deployment pour les projets non modifiés | Désactivé |
| Ignored Build Step | Aucun script de filtrage |

3. Lancer le déploiement et ouvrir l'URL HTTPS Vercel.

Configurer `NEXT_PUBLIC_API_URL` dans les variables Vercel avec l'URL HTTPS publique du backend Railway, puis redéployer le frontend. Les appels de connexion partent du navigateur vers Railway. Dans Railway, `CORS_ORIGINS` doit contenir l'origine exacte de Vercel, sans slash final. Plusieurs origines peuvent être séparées par des virgules.

Générer une clé JWT de production avec `python3 -c "import secrets; print(secrets.token_hex(32))"` et renseigner `JWT_SECRET_KEY` dans Railway. Ne pas utiliser les textes de remplacement ci-dessus comme valeurs réelles. Le compte de test est `test@test.com`, avec le mot de passe `test`.

Configurer aussi `MISTRAL_API_KEY` et `WORLD_NEWS_API_KEY` dans Railway pour les réponses du chat et les actualités. `MISTRAL_MODEL` sélectionne le modèle ; `ministral-8b-latest` est la valeur par défaut. Voir le [guide du chat](chat.md).

## Vérifier les déploiements automatiques

Un commit local ne suffit pas : il doit être poussé sur `main` dans GitHub.

1. Pousser une modification de documentation sur `main`.
2. Vérifier qu'un déploiement Vercel et un déploiement du backend Railway sont déclenchés.
3. Vérifier que les deux déploiements utilisent le commit attendu et aboutissent.
4. Ouvrir le frontend et la route `/` de l'API.
5. Conserver les deux adresses de production pour compléter ce document.

Les intégrations Git des plateformes suffisent pour ces déploiements automatiques. PostgreSQL conserve ses données entre les déploiements du backend ; son service n'est pas reconstruit à chaque commit applicatif.

## Vérifier le Dockerfile en local

Depuis la racine du dépôt, construire l'image avec **`backend/` comme contexte** :

```bash
docker build -t newsfoundry-backend ./backend
```

Le fichier `.dockerignore` exclut notamment les variables locales et l'environnement virtuel du contexte de construction. Les dépendances sont installées depuis `uv.lock` avec `--frozen --no-dev`, puis réutilisées au démarrage sans nouvelle synchronisation.
