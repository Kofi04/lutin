# DESIGN.md — Little Wizard

Ce document est la source de vérité pour l'interface. Toute décision visuelle ou d'interaction qui n'est pas ici doit être ajoutée ici avant d'être codée.

---

## 1. Principes

1. **Une seule présence, une seule surface.** L'avatar, et un panneau qui naît de lui et change de forme. Pas de fenêtres qui surgissent ailleurs à l'écran.
2. **Le mouvement plutôt que le détail.** L'avatar est simple ; c'est l'animation (ressorts, regard, respiration) qui le rend vivant.
3. **Invisible quand rien ne se passe.** Rien ne clignote, rien ne bouge sans raison. On n'interrompt l'utilisateur que quand il est nécessaire.
4. **Clavier d'abord.** Tout ce qui se fait à la souris se fait au clavier. Esc ferme toujours.
5. **Ne jamais gêner.** Aucune surface flottante ne vole le focus. L'overlay ne prend jamais un clic.

---

## 2. Architecture cible

```
┌──────────────────────────── Tauri 2 (Rust + TypeScript) ─────────────────────────────┐
│  Fenêtres :                                                                          │
│   avatar     petite, transparente, toujours au premier plan, sans focus              │
│   panel      ancrée à l'avatar, transparente, sans focus sauf quand on tape          │
│   overlay×N  une par écran, plein écran, transparente, traversée par les clics       │
│   settings   fenêtre normale (Mica sur Windows 11)                                   │
│   history    fenêtre normale                                                         │
│  Tray icon, lancement et surveillance du core Python (redémarrage s'il plante)       │
└──────────────────────────────────────┬───────────────────────────────────────────────┘
                                       │ WebSocket 127.0.0.1:<port aléatoire>
                                       │ + jeton secret passé au lancement
┌──────────────────────────────────────┴───────────────────────────────────────────────┐
│  Core Python (le code actuel, sans fenêtres visibles)                                │
│   Claude Agent SDK, hooks/pipe, SQLite, OCR, captures, presse-papiers, hotkeys,      │
│   overlay/mapping.py, outils MCP point_at / highlight / show_steps / clear_overlay   │
│   Garde Qt comme boucle d'événements (QLocalServer, RegisterHotKey) — pas de widgets │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**Front :** React + Vite + TypeScript, **Motion** (ex-Framer Motion) pour les animations, CSS Modules ou Tailwind, icônes **Lucide**. L'avatar et le curseur guide sont dessinés en **Canvas 2D** (Rive envisageable plus tard pour l'avatar).

**Protocole :** messages JSON `{ "type": "...", "id": "...", "payload": {...} }`.
- Core → UI (événements) : `mood`, `connection`, `stream.start|chunk|end`, `approval.request`, `capture.preview`, `selection.result`, `sessions.update`, `toast`, `guide.point`, `guide.highlight`, `guide.steps`, `guide.clear`, `cloak.hide|show`.
- UI → Core (commandes) : `ask`, `approval.answer`, `capture.confirm|cancel`, `selection.replace|copy`, `agent.start|stop`, `guide.done`, `cloak.ack`.
- Le protocole est typé des deux côtés (`protocol.ts`, `protocol.py`) et testé.

**Complément au protocole (phase M1).** La liste de référence est `src/wizard/protocol_messages.json`, lue par les deux côtés : en cas d'écart, c'est ce fichier qui fait foi. Ajouts par rapport à la liste ci-dessus, et pourquoi :
- **Connexion :** `hello { token, protocol, role, pid? }` en premier message sous 2 s, sinon fermeture ; réponse `hello.ok`. Jeton transmis au core par variable d'environnement (`WIZARD_UI_TOKEN`), jamais en argument ; vérification de l'`Origin` ; 127.0.0.1 seulement ; 1 Mo max par message.
- **Requête / réponse :** un message UI qui porte un `id` reçoit `reply { ok, data? }` avec ce même `id` (`ping` pour l'instant). Toute commande refusée reçoit `error { error, message }`, comme les erreurs de nos API REST.
- **À la connexion,** le core renvoie l'état courant (`mood`, `connection`, `sessions.update`, `quiet`, l'approbation en attente) : une fenêtre relancée ne perd rien.
- **Panneau :** `panel.open { state, capture?, context?, status? }` (raccourci, capture confirmée, discussion reprise) ; `stream.status`, `stream.reset`, `stream.error` complètent `stream.*` ; `ask.cancel` interrompt.
- **Approbations :** `approval.cancel` quand la demande est réglée (réponse, ou refus automatique à l'expiration, décidé par le core).
- **Captures :** `capture.start { mode }`, `capture.select` → `capture.region { mode, screen_id, x, y, width, height }` (la zone se dessine dans l'overlay, le core capture), `capture.file { path }`. `capture.confirm` doit nommer la capture exacte montrée.
- **Sélection :** `selection.menu` remplace le menu Qt ; réponse `selection.pick`.
- **Guide :** `guide.active { active }` pour qu'Échap ne soit réservé que pendant l'affichage.
- **Divers :** `quiet { on }` (plein écran), `system` (charge machine pour l'infobulle), `avatar.toggle`, `session.dismiss`, `action { name }` pour les entrées de menu sans données.
- **Fenêtres pas encore portées :** `window.open { name }` (paramètres, historique, palette, accueil, hooks… — phase M6 bis). Les hooks ne sont jamais écrits tant que la fenêtre de diff n'existe pas côté Tauri.
- **Prévu, pas encore défini :** le ciblage d'une fenêtre par Ctrl + glisser l'avatar (phase M4), les requêtes de données `history.*`, `settings.get|set`, `palette.query`, `hooks.plan|apply` (phase M6 bis).

**Mode développement :** `npm run dev` ouvre un **playground navigateur** qui rejoue des événements factices (réponse en streaming, approbation, curseur qui pointe…). On règle le look là, sans lancer l'app.

---

## 3. Design tokens

Toutes les valeurs vivent dans `ui/src/design/tokens.ts` (et en variables CSS). Aucun composant ne contient de couleur en dur.

### Couleurs — surfaces flottantes (toujours sombres)

| Token | Valeur | Usage |
|---|---|---|
| `surface` | `rgba(16,16,20,0.94)` | fond du panneau, toasts |
| `surface-raised` | `rgba(30,30,36,0.96)` | champs, cartes internes |
| `border` | `rgba(255,255,255,0.08)` | bordure intérieure 1 px |
| `border-strong` | `rgba(255,255,255,0.14)` | focus, survol |
| `text` | `#F2F2F5` | texte principal |
| `text-2` | `rgba(242,242,245,0.64)` | texte secondaire |
| `text-3` | `rgba(242,242,245,0.40)` | indices, placeholders |
| `accent` | `#7C7BFF` | indigo du sorcier : boutons principaux, focus, curseur guide |
| `accent-hover` | `#918FFF` | |
| `state-working` | `#5AA9FF` | Claude travaille |
| `state-waiting` | `#FFB547` | quelque chose attend l'utilisateur |
| `state-success` | `#3DDC97` | terminé |
| `state-danger` | `#FF5C5C` | erreur, refus |
| `state-offline` | `#8A8A93` | pas de connexion |
| `staff-rest` | `#E8B04A` | lumière du bâton au repos |

Les fenêtres Paramètres et Historique suivent le thème clair/sombre de Windows ; les surfaces flottantes restent sombres.

### Forme, espace, ombre

- **Rayons :** 8 (boutons, chips) · 12 (champs, cartes) · 18 (panneau) · 999 (pills)
- **Espacement :** grille de 4 — 4, 8, 12, 16, 20, 24
- **Ombre panneau :** `0 16px 48px rgba(0,0,0,.45), 0 2px 8px rgba(0,0,0,.30), inset 0 1px 0 rgba(255,255,255,.06)`
- **Pas de flou obligatoire** : sur Windows 10 le flou derrière la fenêtre est peu fiable. Le fond à 94 % + bordure + ombre suffit. Acrylic/Mica uniquement en bonus si disponible.

### Typographie

- Police : `"Segoe UI Variable", "Inter", system-ui` ; code : `"Cascadia Code", "JetBrains Mono", monospace`
- Tailles : 12 (méta) · 13 (texte courant) · 15 (titres de carte) · 20 (titres de fenêtre)
- Graisses : 400 / 500 / 600. Jamais de 700+.
- `letter-spacing: -0.01em` à partir de 15 px.

### Mouvement

| Nom | Ressort | Usage |
|---|---|---|
| `snappy` | stiffness 520, damping 38 | boutons, chips, petits changements |
| `smooth` | stiffness 320, damping 32 | ouverture/transformation du panneau |
| `bouncy` | stiffness 420, damping 16 | réactions de l'avatar |
| `glide` | durée 500–900 ms, ease-in-out | vol du curseur guide |

- Entrée : opacité 0→1, scale 0.96→1, y 6→0, **origine = l'avatar**. Sortie à ~70 % de la durée d'entrée.
- Fondus simples : 120–180 ms. Jamais d'easing linéaire.
- **Mouvement réduit** (réglage Windows) : on garde les fondus, on supprime déplacements, rebonds et vols.

---

## 4. L'avatar

**Taille :** 56 px logiques (zone de la fenêtre : 72 px pour le halo).

**Silhouette :** trois formes plates et un point lumineux.
1. Un **chapeau pointu** indigo profond (`#2E2F7A`), pointe légèrement courbée qui oscille avec la respiration.
2. Un **visage** en squircle, peau foncée (`#5A3825`), qui occupe le bas.
3. Deux **grands yeux** (blanc + pupille sombre) qui suivent le pointeur.
4. Le **bâton** : un trait fin à droite, avec une **orbe lumineuse** au bout — c'est le témoin d'état.

Une seule touche culturelle : une bande de trois motifs géométriques sur le chapeau, affichée seulement à partir de 48 px. Pas de cauris, pas de dégradés, pas de textures.

**Vie au repos :** respiration (scale Y 1 → 1.02, 3,5 s), clignement aléatoire toutes les 3–6 s, regard qui suit la souris (pupilles limitées à 30 % du rayon de l'œil).

**États** (les humeurs actuelles du core, rendues ainsi) :

| État | Orbe du bâton | Corps / yeux |
|---|---|---|
| calme | or, fixe | respiration normale |
| occupé (machine) | or, pulse lente | respiration plus rapide |
| stressé | or → orange | yeux plissés |
| fatigué (batterie) | or pâle | paupières mi-closes |
| Claude travaille | bleu, pulse 1,2 s | yeux qui « lisent » (gauche-droite) |
| attend l'utilisateur | ambre, pulse vive | petit saut, regarde vers le panneau |
| terminé | vert, flash unique | saut de joie (`bouncy`) |
| erreur | rouge, fixe | secoue la tête une fois |
| connexion en cours | pâle, pulse lente | normal |
| hors ligne | gris, éteinte | normal |
| endormi (3 min) | éteinte | yeux fermés, « z » discret |

**Interactions :**
- **Clic** → ouvre la barre de commande (§5). Rien d'autre.
- **Clic droit** → mini-menu de 3 entrées max : Masquer · Paramètres · Quitter.
- **Glisser** → déplace (position mémorisée). **Ctrl + glisser** → pointer une fenêtre.
- **Fichier déposé** → l'avatar ouvre grand la bouche/le chapeau, l'avale, puis la barre s'ouvre avec la pièce jointe.
- **Survol** → yeux qui grandissent légèrement, orbe un peu plus vive.

---

## 5. Le panneau (une surface, plusieurs états)

Le panneau naît de l'avatar et se transforme. Machine à états :

```
hidden ──clic/hotkey──▶ bar ──Entrée──▶ answer ──Esc──▶ hidden
   │                     ▲                 │
   │                     └──── nouvelle question
   ├──approval.request──▶ approval ──réponse──▶ état précédent
   ├──capture.preview───▶ capture  ──confirmer──▶ bar (avec pièce jointe)
   └──selection.result──▶ selection
```

**Taille de fenêtre :** au moment d'agrandir, la fenêtre prend d'abord sa taille finale (transparente), puis le contenu s'anime dedans. Pour réduire, on anime d'abord, puis on rétrécit la fenêtre. Jamais de redimensionnement de fenêtre image par image.

### `bar` — la barre de commande
- Largeur 520 px, hauteur 52 px. Champ unique, placeholder « Demande au sorcier… ».
- Sous le champ, des **chips** contextuelles : 📎 pièce jointe en cours, puis `Écran` · `Zone` · `Sélection` · `Agent`. Icônes Lucide, pas d'emoji dans le rendu final.
- Taper `/` filtre les actions (même moteur flou que la palette).
- Entrée envoie, Esc ferme, Tab parcourt les chips.

### `answer` — la réponse
- S'agrandit vers le haut jusqu'à 560 × 420 px max, puis défile.
- Texte en streaming, curseur de frappe discret. Markdown rendu à la fin du stream (comme aujourd'hui), blocs de code avec bouton Copier.
- Barre basse : champ de relance + `Nouvelle discussion`.

### `approval` — demande de permission
- Titre : « Claude veut exécuter » + nom de la session (pastille de couleur).
- La commande ou le fichier dans un bloc mono, 4 lignes max, extensible.
- Boutons : `Refuser` (fantôme) · `Toujours` (secondaire) · `Autoriser` (accent). Entrée = Autoriser, Esc = Refuser.
- Un anneau fin autour de l'avatar montre le temps restant avant refus automatique (le silence vaut refus).

### `capture` — confirmation avant envoi
- Aperçu de l'image exacte qui partira, coins arrondis 12, max 480 px de large.
- `Annuler` · `Envoyer`. Il n'y a aucun moyen de sauter cette étape.

### `selection` — résultat d'une action sur texte
- Texte modifiable, `Copier` · `Remplacer la sélection`.

### Toasts
- Sortent de l'avatar, empilés au-dessus, 3 max, 4 s, pause au survol, clic = fermer.
- Une ligne de titre + une ligne optionnelle. Pastille de couleur d'état à gauche.

---

## 6. Le curseur guide (façon Clicky)

Un **petit curseur compagnon** qui vit à côté du vrai pointeur, et qui **s'envole** jusqu'à l'élément dont Claude parle pour montrer quoi faire.

### Apparence
- Forme de flèche de curseur, 22 px, remplie `accent`, contour blanc 1,5 px (visible sur fond clair comme sombre), halo doux `accent` à 35 %.
- Il « naît » de l'orbe du bâton : à la première apparition, il part de l'avatar.

### Fenêtres
- Un overlay par écran, plein écran, transparent, **traversé par les clics** (`set_ignore_cursor_events(true)` + styles Win32 `WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE` déjà validés dans le code actuel), jamais focus.
- **Mode transitoire** : l'overlay n'est affiché que pendant une interaction (question → réponse → pointage), puis s'efface 1,2 s après la dernière activité. Coût nul au repos.

### États

| État | Comportement |
|---|---|
| `hidden` | rien |
| `follow` | suit le vrai pointeur avec un décalage (+18, +20) et un léger retard (ressort `snappy`) |
| `thinking` | trois points qui respirent à côté du curseur |
| `talking` | bulle de texte à côté du curseur : 280 px max, 3 lignes, le reste dans le panneau |
| `flying` | vol vers la cible (voir ci-dessous) |
| `pointing` | posé sur la cible, anneau qui pulse 2 fois, étiquette (« Clique ici ») |
| `steps` | pointe l'étape N, étiquette « 2/5 · Ouvre le menu Fichier », boutons Précédent / Suivant dans le panneau |
| `returning` | revient vers le vrai pointeur puis passe en `follow`, ou s'efface |

### Le vol
- Trajectoire en **courbe de Bézier quadratique** : point de contrôle au milieu du segment, décalé perpendiculairement de 20–30 % de la distance (vers le haut de préférence).
- Durée : `clamp(450 + distance × 0.35, 450, 900)` ms, ease-in-out.
- Le curseur s'oriente selon la tangente de la courbe, et se remet droit à l'arrivée (ressort `bouncy`).
- Traînée légère : 4 fantômes à opacité décroissante, désactivée en mouvement réduit.
- Cible sur un autre écran : fondu sortant sur l'écran de départ, fondu entrant près de la cible sur l'écran d'arrivée.
- Mouvement réduit : pas de vol, fondu sur place à la cible.

### Surlignage
- `highlight` : rectangle aux coins arrondis 8, contour `accent` 2 px, le reste de l'écran assombri à 35 %, avec une découpe douce autour de la zone.

### Coordonnées
- Le core reste seul responsable de la conversion « pixels de l'image envoyée à Claude → coordonnées écran logiques » (`overlay/mapping.py`, déjà testé).
- Il envoie `guide.point { screen_id, x, y, label }` en **pixels logiques de l'écran**.
- Le front convertit écran → fenêtre overlay dans **une seule fonction**, testée à 100–200 % de mise à l'échelle et sur écrans à coordonnées négatives.

### Précision (phase 2)
Claude estime les coordonnées à partir de l'image, avec quelques pixels d'erreur. Amélioration : au moment de pointer, le core interroge **UI Automation** (`IUIAutomation::ElementFromPoint`) au point donné. Si un élément raisonnable (bouton, case, élément de menu, < 400 × 200 px) est trouvé, on pointe son centre et on surligne son rectangle réel.

### Règles
- Le curseur guide n'est jamais dans les captures (le mécanisme `cloak` existant cache aussi les fenêtres Tauri : le core envoie `cloak.hide`, attend `cloak.ack`, capture, puis `cloak.show`).
- Esc efface tout (hotkey globale réservée seulement pendant l'affichage, comme aujourd'hui).
- Si l'utilisateur bouge beaucoup sa souris pendant `pointing`, le curseur reste sur la cible jusqu'à la fin du délai ou jusqu'à Esc.
- L'avatar ne se déplace plus vers la cible : il reste chez lui, son orbe s'éteint pendant que le curseur vole et se rallume à son retour.

---

## 7. Ce qui doit survivre à la migration

Ces comportements existent et sont bons. Ils sont non négociables :
- Aucune capture envoyée sans confirmation visuelle.
- Le silence sur une approbation vaut refus. Une session Claude Code n'est jamais bloquée par l'app.
- Masquage pendant les applications plein écran (`SHQueryUserNotificationState`).
- Respect du réglage Windows d'animations.
- Panneaux opaques exclus du partage d'écran (`WDA_EXCLUDEFROMCAPTURE`) quand l'option est active.
- Interface en français, code en anglais.

---

## 8. À faire / à ne pas faire

**À faire :** une icône par action (Lucide), des libellés de 1 à 3 mots, un retour visuel au survol pour tout ce qui est cliquable, un état vide soigné partout, des raccourcis affichés dans les infobulles.

**À ne pas faire :** emoji dans l'interface, dégradés décoratifs, plus de 2 niveaux de gris de texte dans une même carte, `QMenu`/menus système pour les actions principales, nouvelles fenêtres flottantes indépendantes, copier le personnage, le nom ou les sons de Coucou (droits réservés — seul son code est MIT).
