# Discussions avec Mistral

La génération et la consultation des revues sont décrites dans le [guide des revues de presse](reviews.md).

## Utilisation

Après connexion, écrire un premier message ou sélectionner « Nouvelle discussion ». La barre latérale affiche les discussions personnelles, triées par dernière activité. Cliquer sur une discussion recharge son historique. L'adresse `/?chat=<id>` retrouve la discussion après rechargement.

Pendant la génération, un indicateur d'attente s'affiche. En cas d'erreur, la saisie reste disponible. Un échange utilisateur/assistant est enregistré après une réponse réussie ; un appel IA échoué ne laisse pas de message incomplet en base.

## Configuration

Ajouter dans `backend/.env` et dans les variables Railway :

```text
MISTRAL_API_KEY=<clé privée>
MISTRAL_MODEL=ministral-8b-latest
WORLD_NEWS_API_KEY=<clé privée World News API>
```

La clé reste exclusivement dans le backend. La variable du modèle contient son nom sans le préfixe `mistral:` utilisé par PydanticAI. Redémarrer le backend après changement des variables.

Le modèle par défaut est [Ministral 3 8B](https://docs.mistral.ai/models/ministral-3-8b-25-12). Lors de la vérification, l'API identifiait l'alias `ministral-8b-latest` comme `ministral-8b-2512` et un appel réel avec PydanticAI a répondu correctement. Pour figer cette version, utiliser `MISTRAL_MODEL=ministral-8b-2512`.

## Structure et choix techniques

- `models.py` : `Chat`, propriétaire, titre, dates, historique JSON et compteur de révision.
- `chat_agent.py` : agent PydanticAI Mistral, instructions, outil de recherche et conversion des messages visibles.
- `news.py` : appels à World News API et sélection des titres, résumés et extraits.
- `chats.py` : routes, contrôle d'accès et sauvegarde.
- `frontend/src/lib/chats.js` : appels authentifiés avec le JWT existant.
- `ChatWorkspace.jsx` : historique, sélection et formulaire.
- `MessageBubble.jsx` : messages et Markdown, sans interprétation du HTML du modèle.

Le JSON conserve l'historique PydanticAI complet : prompt système, messages, appels d'outil, résultats et métadonnées. `ModelMessagesTypeAdapter` sérialise et reconstruit cet historique. Le navigateur reçoit uniquement les messages visibles utilisateur/assistant et leurs dates.

Chaque lecture ou écriture SQL filtre aussi le propriétaire. Une discussion absente ou appartenant à quelqu'un d'autre retourne le même `404`. Le propriétaire est issu du JWT, jamais du body du client.

Le compteur `revision` empêche une requête concurrente d'écraser un échange enregistré entre la lecture et la sauvegarde. Un conflit retourne `409` et le frontend recharge l'historique sans renvoi automatique au LLM. La connexion SQL est libérée pendant l'attente réseau. La liste latérale charge les métadonnées seules, sans tous les historiques JSON. Les réponses privées utilisent `Cache-Control: no-store`.

## Prompt

NewsFoundry répond en français, de façon concise et factuelle, en tenant compte de la discussion. Le prompt demande de clarifier les ambiguïtés et interdit les sources et citations inventées.

À la création de chaque discussion, le backend appelle `GET https://api.worldnewsapi.com/top-news` avec `source-country=fr`, `language=fr` et la date du jour en Europe/Paris. La clé est transmise par le header `x-api-key`, uniquement depuis le backend.

Le contexte retient un article par sujet, en privilégiant les résumés disponibles. Il contient au maximum dix titres (200 caractères chacun) et résumés (800 caractères chacun). Les doublons de titre sont retirés. Le champ `text` n'est jamais intégré ; un résumé absent est signalé comme tel. Aucun appel LLM supplémentaire n'est nécessaire.

Le prompt complet, daté, est enregistré dans un `SystemPromptPart` du JSON `Chat.messages` dès la création, avant tout appel à Mistral. PydanticAI réutilise ensuite cet historique sans rappeler `/top-news`. Le modèle doit s'appuyer sur ces actualités, indiquer leur date et signaler les informations non disponibles. Les articles sont présentés comme des données externes et non comme des instructions.

Une discussion reprise le lendemain conserve donc le contexte du jour de sa création. Une nouvelle discussion charge un nouveau contexte ; l'outil de recherche peut aussi obtenir de nouveaux articles dans une discussion existante. Les discussions antérieures à cette fonctionnalité conservent leur prompt initial ; une ancienne discussion encore vide reçoit le contexte lors de son premier échange réussi.

L'appel d'actualités est limité à dix secondes. Une clé manquante, une erreur réseau, un quota épuisé ou des résultats vides empêchent la création et produisent un message explicite, sans inventer d'actualités ni créer de discussion incomplète. Les discussions existantes restent accessibles. Un appel est effectué par nouvelle discussion ; les limites du compte World News API s'appliquent.

## Approfondir un sujet avec un outil

Exemple : « Peux-tu approfondir les avancées récentes sur les batteries électriques ? »

L'agent dispose de `search_news(query, days=7)`, déclaré via `@chat_agent.tool_plain`. Le modèle décide de l'appel et PydanticAI exécute la fonction, lui transmet les résultats, puis lui demande sa réponse. Les instructions demandent une recherche lorsqu'un utilisateur souhaite approfondir un sujet ou obtenir des informations plus récentes. Elles sont fournies à chaque exécution, pour que l'outil soit aussi utilisable dans les anciennes discussions sans modifier leur prompt initial.

`query` contient 2 à 200 caractères ; `days` va de 1 à 30. Le backend appelle `/search-news` avec les mots-clés, la langue française et une date minimale de publication, puis trie par publication décroissante. Il retient jusqu'à cinq articles distincts. Chaque résultat contient un titre, un résumé, un extrait de 2000 caractères maximum, un lien HTTP(S) et une date de publication lorsqu'ils sont disponibles. La date de récupération est conservée pour distinguer ces sources du contexte initial. La clé privée est transmise par header et ne fait pas partie des arguments visibles par le modèle.

Le modèle doit s'appuyer sur les résultats, citer les liens et dates disponibles et ignorer les instructions éventuellement contenues dans les articles. Un résultat vide ou une erreur est transmis explicitement au modèle afin qu'il signale la limite sans inventer de source. Une erreur de recherche n'efface pas la discussion et peut être expliquée dans une réponse normale.

Les appels d'outil et leurs résultats sont enregistrés dans `Chat.messages` avec l'échange réussi. Ils sont donc réutilisables après rechargement. Le navigateur n'affiche pas les données techniques de l'outil ; les liens cités sont rendus par le Markdown existant. Aucun nouvel endpoint local ni migration de base n'est nécessaire.

Les recherches sont exécutées une par une. `UsageLimits` impose au maximum trois appels d'outil et cinq requêtes LLM par message, en plus de la limite globale de 50 secondes. Une boucle dépassant ces limites retourne une erreur et laisse l'historique inchangé. Le contrôle du propriétaire de la discussion a lieu avant tout appel au modèle ou à l'outil.

## API

Toutes les routes exigent `Authorization: Bearer <JWT>`.

| Route | Résultat |
| --- | --- |
| `POST /chats` | Charge les actualités, sauvegarde le prompt et crée une discussion personnelle |
| `GET /chats` | Liste uniquement les discussions de l'utilisateur |
| `GET /chats/{id}` | Retourne les messages de sa discussion |
| `POST /chats/{id}/messages` | Reçoit `{"content":"Votre message"}` et retourne `reply` ainsi que l'historique sauvegardé |

Le premier message réussi fournit un titre limité à 80 caractères. Un message est limité à 4000 caractères, une réponse du modèle à 2048 tokens. La génération est interrompue après 50 secondes.

| Statut | Situation |
| --- | --- |
| `401` | Session absente, invalide ou expirée |
| `404` | Discussion absente ou non autorisée |
| `409` | Modification concurrente |
| `422` | Message vide, trop long ou identifiant invalide |
| `429` | Limite de requêtes ou quota Mistral |
| `502` | Réponse IA inutilisable, erreur du fournisseur ou limite de recherches atteinte |
| `503` | Configuration IA ou base indisponible |
| `504` | Délai de réponse dépassé |

Les détails internes du fournisseur ne sont pas renvoyés au navigateur. Si Mistral retourne `429`, vérifier les limites du compte dans Studio et réessayer lorsque de nouvelles requêtes sont autorisées.

## Tests et CI

```bash
cd backend
uv sync --frozen
uv run --no-sync pytest -q
```

SQLite en mémoire, `TestModel`, `FunctionModel` et `Agent.override` isolent les tests. `ALLOW_MODEL_REQUESTS=False` interdit les appels LLM réels. `httpx.MockTransport` simule les réponses de World News API et ses erreurs.

Les tests couvrent les accès autorisés, les lectures et modifications interdites sur les discussions d'autrui, la liste filtrée, la persistance JSON, la reprise du contexte, les erreurs IA et les conflits de sauvegarde. Pytest collecte aussi les tests d'authentification existants. La GitHub Action lance les tests, le lint frontend et la compilation sur les pushes et pull requests de `main`.

Les tests d'actualités vérifient la sélection sans contenu complet, le bornage du contexte, les erreurs et quotas, la sauvegarde avant le premier message et la stabilité du prompt lors d'une reprise le lendemain. Une nouvelle discussion reçoit le nouveau contexte.

Les tests d'outils utilisent `FunctionModel` pour demander une recherche, lire son résultat et formuler une réponse sourcée. Ils vérifient l'appel HTTP, la validation des arguments, les résultats bornés, les liens autorisés, les erreurs, la limite de recherches et la sauvegarde/reprise des articles. Un utilisateur non propriétaire ne peut pas déclencher l'outil sur une discussion d'autrui.

## Piste d'optimisation

Sur un jeu de discussions de 50 à 100 échanges, mesurer les tokens d'entrée et la latence. Une amélioration possible consiste à résumer les anciens échanges, conserver l'historique complet en base, puis transmettre le résumé et les derniers messages au modèle. Objectif à valider : réduire d'au moins 50 % les tokens d'entrée sans perte d'information essentielle dans les réponses.

## Références

- [PydanticAI : exemple de chat](https://ai.pydantic.dev/examples/chat-app/)
- [PydanticAI : historique](https://ai.pydantic.dev/message-history/)
- [PydanticAI : tests](https://ai.pydantic.dev/testing/)
- [PydanticAI : Mistral](https://ai.pydantic.dev/models/mistral/)
- [World News API : Top News](https://worldnewsapi.com/docs/top-news/)
- [World News API : authentification](https://worldnewsapi.com/docs/authentication/)
- [World News API : Search News](https://worldnewsapi.com/docs/search-news/)
- [PydanticAI : outils](https://ai.pydantic.dev/tools/)
