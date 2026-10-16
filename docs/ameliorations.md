# Regard critique et pistes d'amélioration

Analyse réalisée le **12 octobre 2026** sur la version actuelle de NewsFoundry. Les pistes ci-dessous sont des propositions : elles ne sont pas encore implémentées dans l'application. Les objectifs sont distincts des résultats mesurés.

## 1. Méthode et preuves disponibles

Une campagne de **21 appels à la route de génération de revue** a été réalisée, avec trois répétitions pour chacun des sept scénarios. Les fonctions actuelles du backend ont été utilisées avec des appels Mistral réels, une base SQLite en mémoire et un corpus fictif. Aucune discussion utilisateur n'a été modifiée et World News API n'a pas été appelée pendant ces mesures.

Les résultats complets, le corpus, les sorties générées, les versions des dépendances et le hash du code sont disponibles dans [les données de mesure](mesures/performance-2026-10-12.json). Le [script de benchmark](../backend/scripts/benchmark_performance.py) chronomètre le traitement de l'endpoint, le RAG, les embeddings, la construction d'index, l'agent rédacteur et les instructions SQL. Il relève aussi les tokens et les références aux sources.

### Protocole

- Python 3.13.9, PydanticAI 2.55.0, SDK Mistral 3.2.0 et LlamaIndex Core 0.14.25.
- Modèle de rédaction : `ministral-8b-latest`. Embeddings : `mistral-embed`.
- Historiques de 10, 30 ou 60 messages visibles, complétés par le prompt et les résultats d'outils sérialisés.
- Corpus de 5, 15 ou 30 articles : deux documents sur le stockage solaire et les batteries, puis des distracteurs sur le football, l'école et la musique.
- Même sujet et même corpus pour comparer les longueurs d'historique ; même historique visible pour comparer les tailles de corpus. Le nombre de résultats d'outils augmente cependant avec le corpus.
- Ordre des scénarios inversé au deuxième passage pour réduire l'effet de l'ordre des appels.
- Index reconstruit à chaque revue, comme dans le code actuel.
- Cas sans RAG et cas sans correspondance évalués séparément.

Le temps total va du début de l'appel HTTP en processus local à la réception de sa réponse complète, sauvegarde comprise. L'import du serveur, la création des fixtures et la connexion de test sont hors de cette mesure. Le temps de l'agent inclut la rédaction, les validations et les éventuelles nouvelles tentatives.

### Portée des mesures

Ces chiffres sont **exploratoires** : trois répétitions par condition et deux sources pertinentes distinctes ne constituent pas une évaluation représentative de tous les sujets. Le corpus et les historiques sont synthétiques. Les appels Mistral traversent le réseau, mais les temps de transfert Vercel/Railway, PostgreSQL distant, le rendu du navigateur, la charge concurrente et le démarrage à froid du serveur ne sont pas mesurés.

Les premières tentatives du script avaient une erreur d'instrumentation sur la propriété d'usage de PydanticAI. Elles ont été exclues. Les données publiées contiennent uniquement les 21 mesures complètes après correction et vérification du script avec un modèle simulé. Le faible nombre de répétitions conduit à présenter moyenne, médiane et min–max ; un p95 de production devra être établi sur un échantillon plus large.

### Reproduire la campagne

Depuis `backend/`, avec la clé Mistral configurée :

```bash
uv sync --frozen
uv run --env-file .env python scripts/benchmark_performance.py \
  --output /tmp/newsfoundry-performance.json --repeats 3 --measure-list
```

Le script appelle réellement Mistral. Les bases sont créées en mémoire et les données sont fictives. Pour reprendre une campagne interrompue avec le même code, le même environnement et les mêmes paramètres, ajouter `--resume`. Les mesures peuvent varier avec le réseau et le service du fournisseur ; les versions et la date doivent accompagner toute comparaison.

## 2. Temps de génération observés

Chaque ligne représente trois appels réussis.

| Scénario | Temps moyen | Médiane | Min–max | Tokens d'entrée moyens du rédacteur |
| --- | ---: | ---: | ---: | ---: |
| RAG, 10 messages, 5 articles | 8,49 s | 7,53 s | 6,26–11,67 s | 5 731 |
| RAG, 30 messages, 5 articles | 7,88 s | 6,91 s | 6,55–10,17 s | 10 227 |
| RAG, 60 messages, 5 articles | 6,88 s | 7,04 s | 5,45–8,14 s | 16 977 |
| RAG, 10 messages, 15 articles | 7,59 s | 7,60 s | 7,05–8,12 s | 7 304 |
| RAG, 10 messages, 30 articles | 9,86 s | 8,61 s | 8,05–12,91 s | 9 681 |
| Historique seul, 10 messages | 6,43 s | 6,76 s | 5,68–6,86 s | 3 958 |
| Aucun article pertinent, 10 messages, 5 articles | 1,12 s | 1,25 s | 0,61–1,52 s | Agent non appelé |

**Les 15 revues avec RAG prennent 8,14 secondes en moyenne**, avec une médiane de 7,60 secondes et un intervalle de 5,45 à 12,91 secondes. Les 18 revues non vides, avec et sans RAG, prennent 7,85 secondes en moyenne. Les trois réponses sans correspondance ne doivent pas être mélangées à cette moyenne : elles n'appellent pas l'agent rédacteur. Aucun échec HTTP ni timeout n'a été observé dans la campagne publiée.

Le délai de **50 secondes** dans le code est un timeout, pas un temps moyen mesuré. Il n'a pas été atteint ici.

### Influence de la longueur du chat

Sur ce petit échantillon, le délai **n'augmente pas régulièrement** avec la longueur du chat. On ne peut donc pas affirmer qu'un chat de 60 messages est plus lent, ni qu'il est plus rapide en général. Les réponses générées ont des longueurs différentes : environ 625 tokens de sortie pour les chats de 10 messages, contre 531 pour ceux de 60 messages. La variabilité du fournisseur et du réseau doit aussi être considérée.

En revanche, les tokens d'entrée passent de **5 731 à 16 977**, soit presque trois fois plus. Le prompt de revue transmet actuellement l'historique complet, même lorsque les passages RAG sont déjà sélectionnés. La réduction de ce contexte est donc une piste étayée pour diminuer le volume transmis ; son effet sur le délai reste à vérifier.

### Influence du nombre d'articles

À historique visible identique, les phases RAG se répartissent ainsi :

| Corpus | Passages indexés | Temps RAG moyen | Embeddings moyens, requête comprise | Construction d'index moyenne | Tokens d'embedding |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5 articles | 10 | 0,81 s | 0,78 s | 0,0013 s | 5 326 |
| 15 articles | 30 | 1,20 s | 1,16 s | 0,0034 s | 15 597 |
| 30 articles | 60 | 2,71 s | 2,63 s | 0,0051 s | 31 062 |

Le coût temporel de cette phase vient surtout des **appels d'embeddings**, plutôt que de la création de l'index en mémoire. Sur les 15 revues RAG, l'agent de rédaction et validation représente environ **85 % du temps total cumulé**. Les instructions SQL de SQLite prennent moins de 0,2 ms en moyenne par scénario ; cela ne mesure pas les performances de PostgreSQL sur Railway.

### Fluidité perçue

Un délai moyen d'environ huit secondes est raisonnable pour une génération ponctuelle de revue, mais il reste perceptible. Trois des quinze revues RAG dépassent dix secondes. La modale affiche une attente générique et empêche actuellement la fermeture et la navigation pendant la génération.

Les repères de [Nielsen Norman Group](https://www.nngroup.com/articles/response-times-3-important-limits/) distinguent une réaction presque instantanée autour de 0,1 s, une navigation fluide autour de 1 s et une attente nécessitant un retour explicite lorsqu'elle dépasse environ 10 s. Ce sont des repères d'expérience utilisateur, pas un engagement de durée pour un LLM.

## 3. Qualité des résultats : constats

### Recherche et périmètre de la question

Dans une réponse partagée pendant le développement sur l'intelligence artificielle en France, le chat annonçait ne pas avoir trouvé d'article spécifique, puis proposait des mentions indirectes. Il associait notamment une application d'aide aux personnes non-voyantes à l'IA avec la formulation « probablement liées ». Cet exemple montre le risque de présenter des rapprochements supposés lorsque les résultats sont insuffisants. Les instructions du chat ont depuis été renforcées pour respecter le périmètre, écarter ces rapprochements et affiner les résultats hors sujet.

Cette correction de prompt ne remplace pas une évaluation sur un jeu varié. Les tests techniques actuels contrôlent les appels, les autorisations et les structures, mais utilisent des modèles simulés pour leurs réponses.

### Pertinence des références et fidélité des synthèses

Sur le corpus fictif, les 18 revues non vides citent chacune les deux sources pertinentes : **36 références correctes sur 36**, aucune URL inconnue et aucun distracteur cité. Les trois demandes de pâtisserie produisent une revue sans article. Ces résultats concernent deux documents pertinents répétés dans plusieurs scénarios ; ils ne prouvent pas une précision de 100 % sur les actualités réelles.

La fidélité des textes est une autre question. Dans `rag-h30-a5`, répétition 1, la synthèse du deuxième article affirme que ses caractéristiques « pourraient réduire les coûts de maintenance et prolonger la durée de vie utile des installations ». Le document fictif fournit 900 cycles et trois heures de charge, mais aucune donnée sur les coûts de maintenance ni comparaison de durée de vie. C'est une interprétation non étayée, même si le lien source est correct.

**Valider les URLs, les titres et les dates ne suffit donc pas à valider chaque affirmation.** La pertinence des articles, les chiffres, les interprétations et les omissions doivent être évalués séparément.

## 4. Pistes d'amélioration

Les objectifs suivants sont des critères proposés pour les prochaines étapes. Aucun gain annoncé n'est déjà acquis.

### Piste 1 — Évaluer et améliorer la fidélité des réponses

**Preuves :** les rapprochements supposés avec l'IA dans la réponse partagée pendant le développement et l'interprétation sur les coûts de maintenance dans le benchmark.

**Réalisation envisagée :**

1. Constituer un jeu versionné d'au moins 20 questions, avec des sources figées et annotées : sujets précis, requêtes ambiguës et sujets sans correspondance.
2. Noter séparément la pertinence des articles, la présence des faits attendus, les affirmations non sourcées et les liens.
3. Comparer le prompt actuel à une variante demandant de séparer faits de la source et interprétations, ou de supprimer ces dernières.
4. Tester les paramètres du retrieval et un éventuel classement supplémentaire des candidats sur ce même jeu.
5. Garder les tests d'autorisation et de validation de sources existants ; examiner les sorties réelles sur les critères de qualité.

**Mesures :** précision des sources, rappel des sources pertinentes, proportion d'affirmations étayées, nombre de liens inconnus et réponses correctes aux questions sans correspondance.

**Objectifs proposés :** au moins 90 % de sources pertinentes et 95 % d'affirmations étayées sur le jeu annoté, aucun lien inconnu et aucune source inventée dans les cas sans correspondance. Publier les résultats avant/après avec le même modèle et les mêmes sources.

### Piste 2 — Afficher les réponses du chat en streaming

**Preuve :** `ChatWorkspace.jsx` attend le résultat de `sendMessage`, et `apiRequest` lit la réponse JSON complète avant affichage. Le texte du chat n'est donc pas affiché pendant sa génération. Les temps de génération de revue mesurés ne constituent pas une mesure du délai du chat.

**Réalisation envisagée :**

1. Ajouter un endpoint de messages en streaming, avec le même contrôle du JWT et du propriétaire avant de commencer la réponse.
2. Consommer les événements PydanticAI, par exemple avec `run_stream_events`, disponible dans la version installée. Transmettre les états des recherches puis les fragments de réponse avec une `StreamingResponse` FastAPI au format SSE.
3. Lire le flux via `fetch` dans le frontend, en conservant le header Bearer. Décoder correctement l'UTF-8 et les événements ; ne pas utiliser le helper qui appelle actuellement `response.json()`.
4. Afficher un message assistant provisoire et mettre à jour son texte progressivement. Conserver la saisie et annoncer les états importants aux lecteurs d'écran, sans annoncer chaque caractère.
5. À la fin, appliquer la sauvegarde complète avec les contrôles de révision existants. Un échec ou une interruption ne doit pas enregistrer un échange présenté comme terminé.
6. Vérifier le flux sur Railway/Vercel pour détecter un éventuel buffering, ainsi que les déconnexions et les erreurs après le début de la réponse.

**Mesures :** délai jusqu'au premier texte utile, durée totale, interruptions et erreurs. Distinguer les conversations avec et sans appels d'outils.

**Objectif proposé :** premier texte utile en moins de trois secondes en médiane sur les échanges sans recherche externe. Le streaming améliore l'attente perçue ; il ne garantit pas une réduction de la durée totale. Voir [le streaming PydanticAI](https://ai.pydantic.dev/examples/chat-app/) et [l'explication du streaming](https://ai-sdk.dev/docs/foundations/streaming).

### Piste 3 — Réutiliser les embeddings des documents

**Preuve :** les mêmes vecteurs sont recalculés à chaque revue. Pour 30 articles, la phase d'embedding prend ici 2,63 secondes en moyenne et traite 31 062 tokens, alors que la construction d'index prend environ cinq millisecondes.

**Réalisation envisagée :** créer un cache mémoire borné des embeddings ou de l'index. La clé doit inclure le propriétaire, la discussion, le hash du contenu des documents, le modèle d'embedding et les paramètres de découpage. Une modification de texte ou de modèle invalide le cache. Une durée de vie et un budget mémoire empêchent son accumulation. Le sujet de chaque revue conserve son propre embedding.

Le compteur `Chat.revision` ne doit pas être la seule clé : il augmente aussi à la sauvegarde d'une revue, même quand les documents n'ont pas changé. L'index reste non persisté en base. Les tests doivent vérifier l'absence de réutilisation entre utilisateurs, y compris avec une URL identique.

**Mesures :** taux de cache utilisé, appels et tokens d'embedding des documents, mémoire occupée, durée RAG et durée totale.

**Objectif proposé :** éviter au moins 90 % des recalculs des documents lors d'une deuxième revue sur le même corpus. Le gain sur le temps total sera plus faible : la rédaction représente ici l'essentiel de l'attente.

### Piste 4 — Réduire le contexte des longues discussions

**Preuve :** à corpus constant, les tokens d'entrée du rédacteur passent de 5 731 à 16 977 entre 10 et 60 messages. `review_prompt` transmet à la fois tout l'historique et les passages sélectionnés.

**Réalisation envisagée :** conserver l'historique intégral en base mais construire un contexte de rédaction ciblé : passages des sources sélectionnées, échanges utiles au sujet, consignes de l'utilisateur et résumé des anciens échanges. Ce résumé doit conserver les décisions et références, être daté et renouvelé lorsque les messages concernés changent. Comparer cette version à l'historique complet sur le jeu de qualité avant de la retenir.

**Mesures :** tokens d'entrée, durée de rédaction, faits conservés, références et réponses aux questions nécessitant un ancien échange.

**Objectif proposé :** réduire d'au moins 50 % les tokens d'entrée sur les chats longs sans diminuer les scores de qualité du jeu annoté. Le benchmark actuel ne prouve pas une hausse linéaire du délai avec la longueur ; le gain temporel devra être mesuré séparément.

### Piste 5 — Afficher l'avancement et permettre l'annulation

**Preuves :** les revues RAG prennent jusqu'à 12,91 secondes dans ce test. La modale affiche uniquement une génération en cours, désactive son bouton de fermeture et bloque Échap pendant l'attente.

**Réalisation envisagée :** transmettre les étapes réellement atteintes : sélection des sources, rédaction et sauvegarde. Ne pas afficher un pourcentage ou une estimation non mesurés. Ajouter une action d'annulation accessible au clavier et rendre la navigation possible quand le traitement n'exige plus une modale bloquante.

L'annulation côté navigateur doit être reliée à la tâche serveur, via la gestion de déconnexion ou le mécanisme de cancellation de PydanticAI. Arrêter seulement `fetch` ne garantit pas l'arrêt du traitement serveur. Une annulation avant la sauvegarde doit laisser les messages et revues antérieurs intacts.

**Mesures :** délai d'affichage de l'état, interruptions, temps passé avec une modale bloquante et résultats enregistrés après annulation.

**Objectifs proposés :** retour visuel en moins de 100 ms, étape visible pendant chaque traitement long et aucun résultat présenté comme final après une annulation confirmée avant sauvegarde. La revue structurée reste validée avant son affichage final ; le streaming de texte est d'abord prévu pour le chat.

### Piste 6 — Paginer la liste des revues

**Preuve mesurée :** le GET actuel retourne toutes les synthèses et tous les articles. Une archive fictive basée sur une revue du benchmark donne :

| Revues | Temps backend moyen local | Réponse complète |
| --- | ---: | ---: |
| 10 | 1,55 ms | 30 882 octets |
| 100 | 3,61 ms | 308 903 octets |
| 500 | 16,88 ms | 1 545 303 octets |

Ces temps utilisent SQLite local et ne comprennent ni le transfert réseau ni le rendu de 500 cartes dans le navigateur. Le poids de la réponse, plus que le temps SQL local, justifie cette piste.

**Réalisation envisagée :** utiliser une table de revues avec une référence à `Chat`, migrer les revues existantes en conservant leur UUID et ajouter une liste paginée de métadonnées. Charger le contenu complet à l'ouverture d'une revue. Filtrer le propriétaire dans les requêtes de liste et de détail, avec des tests couvrant les accès d'autrui.

Une projection simulée des métadonnées de 20 revues pèse 4 373 octets sur l'archive de 500. Cette projection n'est pas un endpoint déjà implémenté ; elle indique le gain possible en séparant liste et détail.

**Mesures :** octets transférés pour la première page, délai d'affichage dans le navigateur, durée des requêtes PostgreSQL et accès non autorisés.

**Objectifs proposés :** première page inférieure à 100 Ko et affichage en moins d'une seconde sur une archive de 500 revues dans un environnement réseau défini, sans changement des règles d'autorisation.

## 5. Observabilité et ordre de réalisation

Les chronomètres du benchmark donnent une première visibilité, mais ils ne sont pas activés dans le service en production. Pour suivre des usages réels, l'intégration [MLflow/PydanticAI](https://mlflow.org/docs/latest/genai/tracing/integrations/listing/pydantic_ai) fournit le tracing des appels, outils, erreurs et tokens via `mlflow.pydantic_ai.autolog()`.

La mise en place consisterait à vérifier l'intégration sur un scénario dédié, organiser une expérience MLflow et ajouter des spans pour le découpage, les embeddings, la sélection et la sauvegarde. Conserver modèle, paramètres, tailles de contexte, durées et états de succès. Les exemples doivent être anonymisés et les clés et tokens d'authentification exclus des traces.

Le tableau de suivi devrait distinguer temps du premier texte et temps final, moyenne/médiane/p95 sur un nombre suffisant de requêtes, taux d'erreur, qualité des sources et fidélité des synthèses. Les mesures avant/après doivent reprendre les mêmes scénarios et identifier le changement évalué.

L'ordre proposé est :

1. Jeu d'évaluation de qualité et instrumentation reproductible.
2. Progression et annulation, puis streaming du chat.
3. Cache des embeddings et réduction ciblée de l'historique, évalués séparément.
4. Pagination des revues sur un jeu d'archives plus volumineux.

Ce classement part des observations : la génération fonctionne sur le corpus contrôlé, la rédaction domine le délai, les liens seuls ne prouvent pas la fidélité et la réponse de liste grossit avec toute l'archive. Les objectifs d'amélioration restent à vérifier lors de leur réalisation.

## Références

- [Données brutes du benchmark](mesures/performance-2026-10-12.json)
- [Script reproductible](../backend/scripts/benchmark_performance.py)
- [Architecture actuelle](architecture.md)
- [MLflow : intégration PydanticAI](https://mlflow.org/docs/latest/genai/tracing/integrations/listing/pydantic_ai)
- [MLflow : analyse des traces](https://mlflow.org/docs/latest/genai/tracing/observe-with-traces/)
- [PydanticAI : chat et streaming](https://ai.pydantic.dev/examples/chat-app/)
- [AI SDK : streaming](https://ai-sdk.dev/docs/foundations/streaming)
- [Nielsen Norman Group : repères de temps de réponse](https://www.nngroup.com/articles/response-times-3-important-limits/)
