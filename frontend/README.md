# NewsFoundry Frontend

Projet Next.js avec JavaScript, App Router, CSS Modules et ESLint.

## Démarrage

Depuis le dossier `frontend/` :

```bash
npm install
cp .env.example .env.local
npm run dev
```

Ouvrir `http://localhost:3000`.

Le backend doit être démarré. `NEXT_PUBLIC_API_URL` dans `.env.local` indique son adresse ; la valeur locale est `http://127.0.0.1:8000`.

Ouvrir `/connexion` et utiliser `test@test.com` avec le mot de passe `test`. Le JWT est enregistré dans le local storage sous la clé `access_token`, conformément à la consigne. Le mot de passe n'est pas enregistré. Au rechargement, `/me` vérifie la session ; un token invalide est supprimé. Le bouton de déconnexion supprime également le token.

## Organisation

- `src/app/page.jsx` : accueil connecté et vérification de session.
- `src/app/page.module.css` : styles locaux de la page d'accueil.
- `src/app/layout.jsx` : mise en page commune et métadonnées.
- `src/app/connexion/` : formulaire de connexion et CSS Module.
- `src/lib/auth.js` : appels API et stockage du token.
- `src/components/RobotIcon.jsx` : icône utilisée par les deux écrans.
- `src/components/ChatWorkspace.jsx` : historique, sélection et envoi des messages.
- `src/components/MessageBubble.jsx` : réponses affichées en Markdown.
- `src/lib/chats.js` : appels API du chat.
- `src/app/globals.css` : styles globaux.
- `public/` : fichiers statiques.

L'alias `@/*` pointe vers `src/*`. Pour les styles d'un composant, créer un fichier `*.module.css` et l'importer dans le composant.

## Discussions

Après connexion, démarrer une discussion ou reprendre son historique dans la barre latérale. L'adresse `/?chat=<id>` conserve la discussion ouverte au rechargement. Un loader s'affiche pendant la réponse ; en cas d'erreur, la saisie est conservée. Le Markdown des réponses est affiché sans interpréter le HTML du modèle.

Voir le [guide du chat](../docs/chat.md).

## Vérifications

```bash
npm run lint
npm run build
```

Pour lancer la version de production après compilation :

```bash
npm run start
```

Les polices Geist du modèle initial utilisent `next/font/google` : la compilation nécessite un accès réseau à Google Fonts.

Documentation : [Next.js](https://nextjs.org/docs).

## Déploiement

Dans Vercel, configurer `NEXT_PUBLIC_API_URL` avec l'URL HTTPS publique du backend Railway et redéployer. Cette URL est intégrée au JavaScript pendant la compilation ; elle ne contient aucun secret.

Dans Railway, ajouter l'origine exacte de Vercel à `CORS_ORIGINS`, sans slash final, par exemple `https://mon-projet.vercel.app`. La clé `JWT_SECRET_KEY` reste exclusivement dans Railway.

## Revues de presse

Depuis une discussion, le bouton « Générer la revue de presse » ouvre une modale de choix du sujet. L'onglet « Revue de presse » rassemble les revues de toutes les discussions de l'utilisateur. `ReviewDialog.jsx` gère la modale et `PressReviews.jsx` affiche les synthèses, les articles et les liens. Les styles utilisent des CSS Modules. Voir le [guide des revues](../docs/reviews.md).
