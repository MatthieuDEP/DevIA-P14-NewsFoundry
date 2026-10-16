# Revues de presse

Le [guide d'architecture](architecture.md) présente les composants et les parcours de génération.

La sélection des articles complets avec LlamaIndex est détaillée dans le [guide RAG](rag.md).

## Utilisation

Après un échange dans le chat, cliquer sur **Générer la revue de presse**, choisir un sujet abordé et valider **Générer**. Un indicateur de génération apparaît dans la modale. En cas d'échec, le sujet reste saisi et un message explique l'erreur.

La revue générée apparaît dans l'espace **Revue de presse**. Cet espace rassemble les revues de toutes les discussions de l'utilisateur, de la plus récente à la plus ancienne. Chaque carte affiche le titre, le sujet, la date de génération, la synthèse générale et les synthèses d'articles. Les liens permettent de lire les sources et de retrouver la discussion d'origine. Le bouton **Copier** copie le contenu dans le presse-papiers. L'URL `/?view=reviews` permet de retrouver cet espace après rechargement.

La modale utilise l'élément natif `dialog`, avec un titre, une description, un champ étiqueté et une gestion du focus. La génération empêche les doubles soumissions et affiche son état aux lecteurs d'écran. Les erreurs sont annoncées avec `role="alert"`. Les écrans sont adaptés aux petits écrans.

## Agent et sortie structurée

`backend/src/review_agent.py` contient un agent PydanticAI distinct de l'agent de chat. Il utilise le modèle Mistral déjà configuré, sans aucun outil de recherche. Aucune nouvelle clé n'est nécessaire.

Le backend lui transmet le sujet et l'historique JSON complet de la discussion : contexte initial, messages et résultats des outils. Si des textes complets ont été chargés, LlamaIndex ajoute les passages pertinents des articles sélectionnés. Ces informations sont fournies comme données dans le prompt utilisateur. Cela évite d'appliquer les instructions de l'agent de chat au rédacteur spécialisé. La génération n'appelle pas World News API.

Le prompt demande de synthétiser uniquement les faits présents dans l'historique, de rapprocher les points communs et divergences et d'expliciter les informations manquantes. Il interdit les articles, dates, liens ou citations inventés et rappelle que les sources peuvent être anciennes. Si le sujet n'est pas documenté, la synthèse doit le signaler et la liste d'articles peut rester vide.

`ToolOutput(ReviewContent)` définit le format attendu :

- `title` : titre de la revue ;
- `summary` : synthèse générale ;
- `articles` : jusqu'à dix articles, avec `title`, `summary`, `url` et `published_at`.

Le mécanisme de sortie structurée de PydanticAI utilise un outil de sortie ; cet outil ne fait aucun appel externe. Les textes sont validés et bornés avec Pydantic. Un validateur compare les liens générés à ceux des sources sélectionnées en mode RAG, ou à ceux de l'historique sinon. Un lien inconnu provoque une demande de correction au modèle. En mode RAG, les titres et dates sont repris des documents conservés.

## Sauvegarde et migration

`Chat.reviews` est un champ JSON contenant les revues structurées, avec un UUID, le sujet, la date de génération et la révision de la discussion utilisée. Plusieurs revues peuvent être générées pour une même discussion. Les messages et le prompt initial restent conservés.

Au démarrage, `migrations.ensure_chat_columns()` ajoute les champs JSON aux bases qui ne les possèdent pas encore, avec une liste vide pour les anciennes discussions. La migration est additive et répétable ; elle ne supprime aucune discussion. Elle fonctionne avec PostgreSQL en production et SQLite dans les tests. Le redémarrage du backend l'applique automatiquement.

La génération libère la connexion SQL pendant l'attente du modèle. La sauvegarde vérifie le propriétaire et la révision lue initialement. Une modification concurrente retourne `409` au lieu d'écraser des messages ou une autre revue. L'historique et les anciennes revues sont préservés en cas d'échec.

## Routes et erreurs

Toutes les routes exigent le JWT de l'utilisateur.

| Route | Résultat |
| --- | --- |
| `POST /chats/{id}/reviews` | Reçoit `{"topic":"Le sujet"}`, génère et sauvegarde une revue, retourne `201` |
| `GET /reviews` | Retourne les revues de toutes les discussions appartenant à l'utilisateur |

Les réponses utilisent `Cache-Control: no-store`. Les lectures et écritures filtrent l'utilisateur dans la requête SQL. La vérification du propriétaire précède l'appel LLM ; une discussion absente ou appartenant à quelqu'un d'autre retourne le même `404`.

| Statut | Situation |
| --- | --- |
| `401` | Session absente ou invalide |
| `404` | Discussion absente ou non autorisée |
| `409` | Discussion modifiée pendant la génération |
| `422` | Sujet invalide, discussion encore sans échange ou corpus trop volumineux |
| `429` | Limite de requêtes du fournisseur |
| `502` | Réponse incorrecte, lien inventé persistant ou erreur du fournisseur |
| `503` | Configuration du modèle ou base indisponible |
| `504` | Génération dépassant 50 secondes |

## Vérifications

```bash
cd backend
uv run pytest -q
```

Les tests utilisent `TestModel` et `FunctionModel`, sans appels réels. Ils couvrent plusieurs revues par chat et plusieurs chats, la persistance de la sortie structurée, l'historique complet reçu par l'agent, l'absence d'outils de recherche, la validation des liens, les erreurs, les conflits, la migration et les autorisations entre utilisateurs. La CI GitHub existante exécute aussi ces tests.

Référence : [sorties structurées PydanticAI](https://ai.pydantic.dev/output/#tool-output).
