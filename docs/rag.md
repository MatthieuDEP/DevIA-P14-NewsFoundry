# Sélection des articles avec LlamaIndex

Le [guide d'architecture](architecture.md) situe le RAG dans le parcours de génération des revues.

## Utilisation

Dans le chat, demander une recherche de nouveaux articles sur un sujet, puis cliquer sur **Générer la revue de presse** et préciser le thème. Le backend sélectionne des passages dans les textes complets des articles chargés dans cette discussion. L'agent de revue rédige ensuite les synthèses des sources pertinentes.

La revue affiche « Synthèse à partir du contenu des articles chargés ». Si aucun article ne correspond suffisamment, une revue vide l'indique explicitement. Les anciennes revues restent conservées.

Les anciennes discussions n'ont pas les textes complets : elles peuvent encore générer une revue à partir de leur historique, avec une indication dans l'interface. Une nouvelle recherche, même dans une ancienne discussion, permet de charger les textes complets et d'activer cette sélection. Le contenu complet indisponible chez World News API n'est pas inventé ni téléchargé directement depuis le site de l'éditeur.

## Configuration

La clé `MISTRAL_API_KEY` existante est utilisée pour les embeddings et pour la rédaction. Le modèle d'embedding est configurable dans le backend :

```text
MISTRAL_EMBEDDING_MODEL=mistral-embed
```

Cette valeur est le défaut, y compris dans Railway si la variable n'est pas renseignée. `llama-index-core` est ajouté aux dépendances Python. `embeddings.MistralEmbedding` adapte le SDK Mistral déjà utilisé par PydanticAI à l'interface `BaseEmbedding` de LlamaIndex. Aucun modèle local supplémentaire ni fournisseur OpenAI n'est chargé.

## Stockage des sources

`Chat.loaded_articles` conserve les URLs uniques et `Chat.article_documents` conserve le titre, le résumé, le texte complet, la date de publication et la date de récupération. Les textes restent ceux obtenus lors du tool-call ; la génération n'a pas besoin de recharger des URLs susceptibles de changer ou de devenir indisponibles.

L'outil `search_news` garde son retour court pour le LLM : titre, résumé, extrait borné, lien et date. Un objet `ChatDocuments` propre à chaque exécution collecte séparément les documents complets. Il évite de partager des sources entre requêtes ou entre utilisateurs. La base sauvegarde les documents et l'échange dans la même transaction avec le contrôle de révision existant. Un échange échoué ne laisse pas de sauvegarde partielle.

Une nouvelle recherche de la même URL remplace son contenu conservé par la dernière version obtenue, sans dupliquer son URL. Les revues déjà générées gardent leurs synthèses enregistrées. La migration additive `ensure_chat_columns()` ajoute les champs JSON aux anciennes bases avec une liste vide ; elle s'applique au démarrage du backend.

## Index et retrieval

`rag.retrieve_articles()` travaille uniquement sur les documents de la discussion dont l'appartenance vient d'être vérifiée :

1. Chaque texte devient un `Document` LlamaIndex avec l'URL et le titre comme métadonnées.
2. `TokenTextSplitter` découpe le contenu en passages de 512 tokens, avec un chevauchement de 64 tokens. Le découpage ne nécessite pas de corpus linguistique téléchargé à l'exécution.
3. Mistral calcule les embeddings, par batches séquentiels de 32 passages. Le titre contribue aux embeddings ; l'URL en est exclue.
4. Un `VectorStoreIndex` est créé en mémoire avec ces vecteurs. Il n'est pas persisté en base ni partagé entre discussions.
5. Le retriever retourne jusqu'à 25 passages proches du sujet. On conserve ceux dont la similarité est au moins 0,72 et à moins de 0,08 du meilleur score.
6. Les passages sont regroupés par URL, avec au maximum cinq articles et trois passages par article.

Le seuil de 0,72 et l'écart au meilleur score écartent les passages éloignés du sujet avant la rédaction. Les candidats retenus sont ensuite soumis à l'agent, qui peut écarter les articles hors sujet.

Pour garder les appels bornés, un corpus dépassant 600 passages retourne `422`. Les batches et la requête de recherche ont des délais réseau de 15 secondes. Le délai global de génération de la revue reste de 50 secondes, indexation incluse. Un problème du service d'embedding est signalé à l'utilisateur ; il ne provoque pas un remplacement silencieux par une revue sans retrieval.

## Génération et validation

L'agent PydanticAI de revue reçoit l'historique pour comprendre la demande et les passages sélectionnés comme sources de la synthèse. Il ne dispose d'aucun outil de recherche. Le prompt lui demande d'écarter les candidats hors sujet et de résumer chaque source pertinente retenue.

En mode RAG, tous les articles de la revue doivent avoir un lien présent parmi les candidats sélectionnés, sans doublon. Les liens insérés dans les synthèses sont vérifiés aussi. Les titres et dates enregistrés sont repris directement des documents conservés. Le modèle peut écarter des candidats ; s'il n'en retient aucun, la réponse affiche explicitement l'absence de correspondance.

Les revues restent structurées avec `ReviewContent` et sauvegardées dans `Chat.reviews`. Le champ `source_mode` indique `full_text`, `history` ou `no_match` et permet une information claire dans l'interface.

## Erreurs et tests

Les routes sont identiques à celles décrites dans le [guide des revues](reviews.md). Les erreurs d'embedding sont converties en messages publics sans divulguer les détails privés : `429` pour une limite Mistral, `503` pour un service indisponible, `504` pour un timeout et `502` pour des données incorrectes. Les sources et les anciennes revues sont préservées en cas d'échec.

```bash
cd backend
uv run pytest -q
```

Les tests utilisent un vrai index LlamaIndex avec des embeddings déterministes locaux. Tout appel réel aux embeddings Mistral est interdit dans les tests. Ils vérifient la sélection, les sujets sans correspondance, les faits situés au-delà des extraits du chat, la validation des sources, les erreurs fournisseur, la persistance des textes et la migration. Ils vérifient aussi qu'un utilisateur ne peut pas indexer la discussion d'autrui et que deux utilisateurs avec la même URL conservent des corpus distincts.

Références : [RAG LlamaIndex](https://developers.llamaindex.ai/python/framework/understanding/rag/), [index vectoriel](https://developers.llamaindex.ai/python/framework/module_guides/indexing/vector_store_index/), [embeddings personnalisés](https://developers.llamaindex.ai/python/framework/integrations/embeddings/custom_embeddings/).
