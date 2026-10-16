# NewsFoundry Frontend

Interface Next.js avec JavaScript, fichiers JSX, App Router, CSS Modules et ESLint. Node.js 24 est utilisé dans la CI. Voir le [guide d'architecture](../docs/architecture.md) pour l'organisation et les choix techniques.

## Configuration et démarrage

Depuis `frontend/`, à la première installation :

```bash
npm ci
cp .env.example .env.local
npm run dev
```

Le backend doit être démarré. `frontend/.env.local` contient son adresse :

```text
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Ouvrir <http://localhost:3000>. `npm ci` installe les versions de `package-lock.json`, comme dans la CI et Vercel. Pour les démarrages suivants, lancer `npm run dev` avec le fichier local déjà configuré.

## Session et navigation

Se connecter sur `/connexion` avec **`test@test.com`** et le mot de passe **`test`**. Le JWT est enregistré dans le local storage sous `access_token`. Les appels protégés transmettent `Authorization: Bearer <token>`. Au rechargement, `/me` vérifie la session ; un token rejeté ou la déconnexion supprime la session locale.

La barre latérale permet de créer et reprendre les discussions. `/?chat=<id>` retrouve la discussion ouverte après rechargement. Les réponses sont affichées en Markdown avec `skipHtml`. Les formulaires conservent la saisie en cas d'erreur et affichent l'état des appels en cours.

Dans une discussion, le bouton **Générer la revue de presse** ouvre une modale pour choisir le sujet. L'espace **Revue de presse** rassemble les revues de toutes les discussions de l'utilisateur. `/?view=reviews` retrouve cet espace après rechargement. Les cartes affichent les synthèses, les articles, les liens et un bouton de copie.

L'interface indique si la revue utilise le contenu des articles chargés, l'historique disponible ou n'a trouvé aucune correspondance. Les guides [chat](../docs/chat.md), [revues](../docs/reviews.md) et [RAG](../docs/rag.md) détaillent ces parcours.

## Organisation

| Fichier ou dossier | Rôle |
| --- | --- |
| `src/app/layout.jsx` | Mise en page commune, polices et métadonnées |
| `src/app/page.jsx` | Vérification de session et espace connecté |
| `src/app/connexion/` | Formulaire de connexion et CSS Module |
| `src/components/ChatWorkspace.jsx` | Navigation, historique et échanges |
| `src/components/MessageBubble.jsx` | Affichage des messages et du Markdown |
| `src/components/ReviewDialog.jsx` | Modale du sujet et progression de génération |
| `src/components/PressReviews.jsx` | Consultation, liens et copie des revues |
| `src/components/RobotIcon.jsx` | Icône commune |
| `src/lib/auth.js` | Appels HTTP, gestion des erreurs et session |
| `src/lib/chats.js` | Appels des discussions et revues |
| `src/app/globals.css` | Styles communs |
| `*.module.css` | Styles propres à une page ou un composant |
| `public/` | Emplacement des fichiers statiques |

L'alias `@/*` pointe vers `src/*`. Les fichiers qui génèrent l'interface portent l'extension `.jsx`. La directive `use client` marque l'entrée des composants qui utilisent l'état React, les événements et les API du navigateur.

La modale utilise `dialog` pour le focus et la navigation au clavier. Les champs sont étiquetés et les erreurs et états d'attente sont annoncés aux lecteurs d'écran.

## Vérifications

Depuis `frontend/` :

```bash
npm ci
npm run lint
npm run build
```

La [GitHub Action](../.github/workflows/ci.yml) exécute ces vérifications après les tests du backend. La compilation utilise `next/font/google` pour les polices Geist et accède à Google Fonts.

Pour lancer la version de production après compilation :

```bash
npm run start
```

## Déploiement

Dans Vercel, définir `frontend` comme répertoire racine et renseigner `NEXT_PUBLIC_API_URL` avec l'URL publique HTTPS du backend Railway. Cette valeur est intégrée au JavaScript pendant la compilation. Les clés Mistral, World News API et JWT sont configurées exclusivement dans le backend.

Dans Railway, `CORS_ORIGINS` contient l'origine exacte du frontend, sans slash final. Le [guide de déploiement](../docs/deploiement.md) décrit les variables, les domaines et les déploiements automatiques depuis `main`.
