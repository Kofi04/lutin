# Little Wizard — plan d'évolution

Document de travail. Prose en français, identifiants et code en anglais, comme
partout ailleurs dans le projet.

## État d'avancement

| Phase | État |
|---|---|
| 0 Renommage · 1 Personnage · 2 Claude au lancement · 3 UI/UX · 4 Guidage | ✅ faites |
| 5 Voix | ⏸️ en pause — la dictée winrt est la reconnaissance **en ligne** de Windows (vérifié : `0x80045509`), contraire à « traitement local ». Choix du moteur local à faire (Vosk recommandé) |
| 6 Mode Live | ⏸️ en pause, dépend du moteur choisi en phase 5 |
| 7 Historique des discussions | ✅ faite |
| 8 Fonctions d'assistant | ✅ faite (sélection, agents, mémoire, OCR, rappels, images) |
| Migration UI vers Tauri (M1–M7) | M1 ✅ faite (protocole, serveur WebSocket, `--headless`) · M2–M7 à faire — voir « Migration UI » en fin de document |

## Contexte

L'app s'appelle aujourd'hui **Lutin** : un compagnon de bureau Windows en PySide6
(4 commits, 110 tests, lint propre) qui sait déjà montrer une zone d'écran, une
fenêtre ou un fichier à Claude Code, afficher les sessions Claude Code externes et
faire approuver leurs permissions — sans terminal visible.

Ce plan la fait passer au rang d'assistant de bureau : nouveau personnage
(**Little Wizard**), UI/UX Windows 11 haut de gamme, Claude prêt dès le lancement,
guidage visuel à l'écran, voix et dictée, mode Live, historique des discussions.

### Décisions prises avec l'utilisateur

| Question | Choix |
|---|---|
| Nom de l'app | **Renommée « Little Wizard »** (le personnage et l'app portent le même nom) |
| Moteur vocal | **Le plus léger** : reconnaissance/synthèse Windows via `winrt` (~5 Mo), pas de modèle à télécharger |
| Mode Live | **Micro + audio système** (loopback WASAPI), avec indicateur d'enregistrement permanent |
| Rappels persistants | **Non** — ils restent en mémoire, comme aujourd'hui |
| Personnage | **On garde le dessin par code** (phase 1). Les PNG restent ajoutables à tout moment via `assets/character/`, sans modification de code |
| Dossier du dépôt | **Reste `desktop-avatar`** — abandonné définitivement, VS Code le tient ouvert et l'incohérence de nom n'a aucune conséquence technique |
| Masquer l'app des captures | **Oui par défaut** (`ui.exclude_from_capture = true`) |
| Capture d'écran jointe aux questions vocales | **Oui par défaut**, avec indicateur visible |
| Réponses parlées (TTS) | **Oui par défaut** (le brief disait l'inverse ; l'utilisateur a tranché) |

### Environnement vérifié sur cette machine

Ce ne sont pas des hypothèses : chaque ligne a été mesurée avant d'écrire ce plan.

| Fait | Valeur | Conséquence |
|---|---|---|
| OS | **Windows 10 Pro 22H2** (build 19045) | **Mica, backdrops et coins arrondis natifs sont impossibles ici.** Seul le repli Windows 10 est testable sur cette machine ; le chemin Windows 11 sera écrit mais non vérifié |
| Python | 3.14.3 (`.venv`) | Les wheels cp314 sont le risque n°1 du projet — d'où les vérifications ci-dessous |
| PySide6 | 6.11.2, QtMultimedia inclus | Capture micro et lecture audio **sans aucune dépendance ajoutée** |
| `claude-agent-sdk` | 0.2.161 | `ClaudeSDKClient`, `create_sdk_mcp_server`, `tool` tous présents (vérifié par introspection) |
| SQLite | 3.50.4, **FTS5 présent**, `unicode61 remove_diacritics 2` accepté | Recherche plein texte insensible aux accents, sans dépendance |
| `winrt-*` 3.2.1 | wheels **cp314** pour SpeechRecognition, SpeechSynthesis, Media.Ocr, Graphics.Imaging, Globalization, Storage.Streams | Voix, TTS et OCR local faisables, tous légers |
| Reconnaissance vocale Windows | recognizers `MS-1033` (en-US) et **`MS-1036` (fr-FR)** installés | La dictée française marchera sans rien télécharger. C'était le risque du choix « le plus léger » ; il est levé |
| Synthèse vocale Windows | 3 voix françaises OneCore (Hortense, Julie, Paul) | TTS français disponible immédiatement |
| Micro | QtMultimedia voit 1 entrée (Microphone Array Realtek) | Capture micro sans dépendance |
| `sounddevice` 0.5.6 | wheel `py3-none-win_amd64` | Loopback WASAPI pour le mode Live |
| `faster-whisper` | résout aussi (17 paquets, ~400 Mo) | **Écarté pour l'instant** sur votre consigne « le moins lourd » ; l'architecture garde la porte ouverte |
| `pyinstaller` | **absent, pas de wheel cp314** | Le bloc « Packaging » du README n'est pas exécutable aujourd'hui. À signaler, pas à corriger en douce |
| `claude auth status` | `loggedIn: false` | **Tout ce qui parle vraiment à Claude reste non vérifiable de bout en bout** jusqu'à `claude auth login` |

---

## Règles qui ne bougent pas

1. **Une session Claude Code n'est jamais bloquée.** Observation en `async: true`,
   sortie 0 sans décision sur tout chemin d'échec. Les trois délais imbriqués
   (110 s app < 130 s hook < 150 s config hook < 600 s Claude Code) restent ordonnés.
2. **Le silence ne vaut pas accord.** Une approbation sans réponse est un refus.
3. **Aucune capture ne part sans être montrée**, sauf le mode vocal explicitement
   activé — et là un indicateur visible signale la capture.
4. **`bypassPermissions` n'apparaît nulle part.**
5. **PySide6 reste la seule dépendance obligatoire** (plus `claude-agent-sdk`, déjà
   là). Tout le reste va dans des extras, et l'app démarre sans eux en désactivant
   proprement la fonction concernée.
6. **Traitement local.** Reconnaissance, synthèse et OCR tournent sur la machine.
7. **Budget au repos : < 1 % d'un cœur**, mesuré, pas supposé.
8. Tests pytest pour toute logique testable sans écran.

---

## Architecture cible

```
src/wizard/                         (était src/lutin/)
  branding.py            APP_NAME = "Little Wizard", SLUG = "LittleWizard"
  mood.py                humeur système + Claude (inchangé)
  paths.py          NEW  dossiers, et migration depuis %APPDATA%\Lutin
  character/        NEW  le personnage, indépendant du reste
    emote.py             Emote enum + emote_for(mood, activity) — pur
    animation.py         timeline, états, transitions, easing — pur, sans Qt
    renderer.py          protocole Renderer + choix de la source
    painter.py           Little Wizard dessiné en QPainter
    sheet.py             chargeur PNG / spritesheet + JSON, prioritaire si présent
  design/           NEW  le design system
    tokens.py            couleurs clair/sombre, espacements, rayons, ombres, typo, motion
    theme.py             suit Windows (thème + couleur d'accent), signal de changement
    qss.py               génère la feuille de style depuis les tokens
    surface.py           Mica/Acrylic (Win11) + repli Windows 10, coins, ombres
    motion.py            durées/courbes, respecte « effets d'animation » désactivés
  overlay/          NEW  guidage visuel à l'écran
    surface.py           fenêtre click-through par moniteur
    shapes.py            flèche, spot, étapes numérotées, bulle
    mapping.py           pixels image -> coordonnées logiques Qt — pur, très testé
    flight.py            le sorcier vole jusqu'au point désigné
    tools.py             serveur MCP in-process : point_at, highlight, show_steps, clear_overlay
    tutorial.py          mode pas à pas
  voice/            NEW  extra [voice]
    state.py             machine à états idle -> listening -> transcribing -> sending -> answering
    mic.py               QtMultimedia, niveau en direct, VAD simple
    recognizer.py        protocole + backend winrt (Whisper possible plus tard)
    synth.py             TTS winrt, interruption immédiate
    dictation.py         insertion SendInput Unicode, repli presse-papiers restauré
    pushtotalk.py        WH_KEYBOARD_LL (appui maintenu) + mode bascule
  live/             NEW  extra [live]
    loopback.py          audio système via sounddevice/WASAPI
    session.py           transcription continue, résumé de fin
  storage/          NEW  (était storage.py)
    schema.py            échelle de migrations sur PRAGMA user_version
    notes.py, clips.py   existant, déplacé
    history.py           conversations, messages, captures, outils, transcriptions
    search.py            FTS5
  assistant/        NEW
    selection.py         actions sur le texte sélectionné
    agents.py            tâches de fond, une session SDK chacune
    memory.py            memory.md injecté dans le system prompt
    ocr.py               Windows.Media.Ocr
    reminders_nl.py      « rappelle-moi dans 20 minutes… » via outil MCP
  ui/               NEW  (les ui*.py actuels, regroupés)
    palette.py           palette de commandes
    answer.py            panneau de réponse ancré à l'avatar
    toast.py             notifications maison
    settings.py          fenêtre Paramètres (écrit config.toml en gardant les commentaires)
    onboarding.py        premier lancement
    history.py           fenêtre Historique
assets/character/       NEW  PNG du personnage, s'ils existent
hooks/wizard_hook.py         (était wizard_hook.py)
docs/ASSETS_BRIEF.md    NEW  fiche personnage + prompts d'images
```

### Ce qui est réutilisé, pas réécrit

- `winapi.py` — les handles `_user32/_kernel32/_shell32`, la garde `IS_WINDOWS`, le
  motif « retour neutre hors Windows ». Les nouveaux appels vont là.
- `config.py` — `_coerce` / `_load_section` / la collecte de `warnings` gèrent déjà
  la tolérance aux valeurs invalides. On ajoute des sections, pas un système.
- `sessions.py` — `SessionRegistry`, `PALETTE`, `EVENT_STATES` resservent tels quels
  pour les agents de fond de la phase 8.
- `capture/` — `prepare()`, `fit_within()`, `grab_rect()` restent le seul endroit où
  vivent les maths de DPI. Le mapping de la phase 4 s'y branche.
- `mood.py` — `combine()` et `claude_mood_for()` restent l'arbitre ; `Emote` se place
  au-dessus, sans les remplacer.
- `bridge/` — le contrat des hooks ne change que pour le nom du pipe.
- `ui.py` — `_centre_on_cursor`, `_preview`, `_relative_time` sont gardés et
  déplacés ; `STYLESHEET`, aujourd'hui recopié dans 4 fichiers, disparaît au profit
  de `design/qss.py`.

### Dépendances ajoutées

| Extra | Paquets | Justification |
|---|---|---|
| — (obligatoire) | `pygments` | Coloration des blocs de code du panneau de réponse. Déjà présent (tiré par `claude-agent-sdk`), pur Python. L'alternative — un `QSyntaxHighlighter` par langage — c'est réinventer mal |
| `[voice]` | `winrt-runtime`, `winrt-Windows.Media.SpeechRecognition`, `winrt-Windows.Media.SpeechSynthesis`, `winrt-Windows.Globalization`, `winrt-Windows.Storage.Streams` | Reconnaissance et synthèse **on-device** fournies par Windows. ~5 Mo, zéro modèle à télécharger, wheels cp314 confirmés. Le micro passe par QtMultimedia, donc rien de plus |
| `[live]` | `sounddevice` | Seul chemin raisonnable vers le loopback WASAPI (audio système). QtMultimedia ne sait pas capter la sortie |
| `[ocr]` | `winrt-Windows.Media.Ocr`, `winrt-Windows.Graphics.Imaging` | OCR local Windows, sans réseau ni service |

Écartés, et pourquoi : `faster-whisper` (400 Mo pour un besoin que vous avez qualifié
de secondaire — l'architecture le garde branchable), `tomlkit` (un éditeur de config
ligne par ligne de ~60 lignes préserve les commentaires sans dépendance),
`pywin32` (installé mais non déclaré ; ctypes suffit, on ne s'appuiera pas dessus),
`Pillow` (Qt redimensionne et encode déjà).

### Schéma SQLite et migrations

`storage.py` n'a **aucun versionnement** aujourd'hui : il s'appuie sur
`CREATE TABLE IF NOT EXISTS`, donc ajouter une colonne à une base existante ne ferait
rien et casserait à la requête. Première chose à construire : une échelle de
migrations sur `PRAGMA user_version`.

```
v0  base existante (notes, clips) — détectée, pas recréée
v1  conversations(id, kind, title, started_at, ended_at, sdk_session_id,
                  pinned, project)
    messages(id, conversation_id, role, body, created_at, cost_usd, turns)
    captures(id, message_id, kind, label, width, height, thumbnail BLOB,
             created_at)
    tool_calls(id, message_id, tool, detail, decision, decided_at)
    transcripts(id, conversation_id, source, body, started_at, ended_at)
    messages_fts  FTS5(body, content='messages',
                       tokenize='unicode61 remove_diacritics 2')
    + triggers INSERT/UPDATE/DELETE pour garder l'index en phase
```

Règles : une migration par version, jamais modifiée après coup ; `user_version`
inférieur = on applique la suite ; supérieur = on refuse de démarrer sur cette base
et on le dit, plutôt que de la corrompre. Miniatures en BLOB PNG plafonnées à 256 px
— pas les captures pleine taille, qui n'ont pas à traîner sur le disque.

---

## Phases

Chaque phase se termine sur un état qui marche, des tests verts et un résumé court.

### Phase 0 — Renommage et fondations

Le renommage d'abord, parce qu'il touche tout et que le faire plus tard multiplierait
les conflits.

- `branding.py` : `APP_NAME = "Little Wizard"`, `SLUG = "LittleWizard"`,
  `APP_USER_MODEL_ID = "LittleWizard.Companion"`, pipe `LittleWizard-hooks`.
- Paquet Python `src/lutin` → `src/wizard` ; distribution `little-wizard` ;
  `[project.gui-scripts] wizard = "wizard.app:main"`.
- `hooks/wizard_hook.py` → `hooks/wizard_hook.py`, et `installer._is_ours()` reconnaît
  **les deux** noms, pour que « désinstaller les hooks » nettoie encore une
  installation faite sous l'ancien nom.
- `paths.py` : migration au premier lancement — `%APPDATA%\Lutin` →
  `%APPDATA%\LittleWizard` (config, base, `state.ini`), et l'ancienne valeur `Run` du
  registre retirée si elle existe. Idempotent, testé.
- ~~Dossier du dépôt renommé~~ — **abandonné** : VS Code tient le dossier ouvert et
  Windows refuse de le renommer. Sans conséquence technique.

**Vérification** : `pytest` vert après renommage ; l'app démarre ; une installation de
hooks faite sous « Lutin » se désinstalle proprement.

### Phase 1 — Little Wizard

Un petit sorcier africain, mignon et soigné, lisible à 48 px. Peau foncée, grands yeux
ronds, grosse tête et petit corps, robe et chapeau pointu à motifs bogolan/kente
sobres et géométriques, cauris, bâton sculpté dont l'embout s'illumine selon l'état.
Palette indigo / ocre / terre cuite / or, avec un accent lumineux qui **est**
l'indicateur d'état. Respectueux et valorisant, jamais une caricature.

1. **Le moteur d'animation d'abord** (`character/animation.py`), pur et sans Qt :
   états, transitions, timeline, easing, `advance(dt) -> Frame`. C'est la partie
   durable et testable ; le rendu est interchangeable derrière elle.
2. **`Emote`** couvre les 8 humeurs existantes redessinées, plus `idle` (respiration,
   clignement, mouvement du bâton), `greeting`, `listening` (main à l'oreille, bâton
   au rythme du micro), `thinking` (étoiles tournant au-dessus du chapeau),
   `speaking`, `pointing`, `waiting_approval` (parchemin), `success`, `confused`,
   `sleeping`.
3. **Deux sources de rendu derrière un protocole.** `sheet.py` charge
   `assets/character/wizard_<emote>_<frame>.png` (ou spritesheet + JSON) et **prend le
   pas** sur `painter.py` quand les fichiers existent. Le reste de l'app ne sait
   jamais laquelle sert.
4. **`docs/ASSETS_BRIEF.md` est écrit dans cette phase, quel que soit le résultat du
   QPainter** : fiche personnage (description, palette en hex, proportions), liste
   exhaustive des fichiers (nom exact, nombre de frames, 512×512, fond transparent,
   même cadrage), un prompt prêt à coller par émote, où déposer les fichiers et
   comment vérifier. Vous n'aurez pas à attendre mon verdict pour lancer une
   génération d'images si vous en avez envie.
5. **Mon engagement sur la qualité** : je ferai une vraie tentative QPainter, pas un
   bonhomme géométrique. Mais je vous le dis franchement dès maintenant — du code
   vectoriel écrit à la main atteint « charmant et propre », rarement « illustration
   de mascotte ». Je vous montrerai le rendu et je vous dirai honnêtement où il se
   situe ; le chargeur de sprites existe précisément pour que votre réponse ne coûte
   pas un refactor.
6. `tools/make_icon.py` régénéré depuis la nouvelle source, en gardant l'échelle de
   `feature_scale` pour les petites tailles.

**Vérification** : rendu offscreen de toutes les émotes en planche PNG, contrôlée à
l'œil ; test de complétude palette/émote (comme le test actuel sur `_PALETTE`) ;
`.ico` régénéré et inspecté aux 9 tailles.

### Phase 2 — Claude prêt dès le lancement

Le vrai changement est interne : `claude/session.py` utilise aujourd'hui `query()`,
qui **relance le CLI à chaque question**. On passe à `ClaudeSDKClient` (`connect()` au
démarrage, `query()` / `receive_response()` ensuite), donc un seul processus maintenu
et une première question instantanée.

- `connect()` dans le thread worker existant, jamais sur le thread UI.
- `check_auth()` au lancement ; si absent, un toast avec la marche à suivre exacte.
- `ConnectionState` (connecting / ready / offline) visible sur l'avatar — l'embout du
  bâton suffit, pas besoin d'un badge de plus.
- Reconnexion automatique avec backoff exponentiel plafonné (1, 2, 4, … 60 s).
- `claude.prewarm = true` par défaut.

**Vérification** : chronométrer la première question avant/après ; couper le réseau et
voir l'état passer à « hors ligne » puis revenir seul. **Bloqué sur
`claude auth login`** pour le bout en bout.

### Phase 3 — Refonte UI/UX

- `design/tokens.py` est la seule source de couleurs, espacements, rayons, ombres,
  typo (Segoe UI Variable, repli Segoe UI), durées et courbes. Aucune couleur codée en
  dur ailleurs — les 4 feuilles de style dupliquées disparaissent.
- Thème clair/sombre suivant Windows automatiquement, avec la couleur d'accent du
  système.
- Mica/Acrylic via `DwmSetWindowAttribute` **si build ≥ 22000**, sinon repli propre :
  fond opaque des tokens + ombre dessinée. Sur cette machine seul le repli sera
  visible, et je le dirai plutôt que de prétendre l'avoir vérifié.
- Animations 150–250 ms ease-out, court-circuitées quand Windows a les effets
  désactivés (`SPI_GETCLIENTAREAANIMATION`).
- **Palette de commandes** sur `Ctrl+Alt+Space` (remplace le menu Lancer) : champ
  unique, recherche floue sur actions, lanceurs, notes, presse-papiers et discussions
  récentes, tout au clavier.
- **Panneau de réponse** ancré à l'avatar : Markdown propre, blocs de code colorés
  avec bouton copier, streaming fluide, stop, redimensionnable.
- **Toasts maison** au lieu des bulles de la zone de notification.
- **Fenêtre Paramètres** : `config.toml` reste la source de vérité, et l'écriture se
  fait ligne par ligne pour **préserver vos commentaires français**. Capture de
  raccourcis en direct et détection de conflits.
- **Écran d'accueil** au premier lancement : présentation du personnage, raccourcis,
  permissions (micro, hooks), vérification de l'authentification.
- Accessibilité : clavier partout, focus visible, contrastes, DPI et multi-écrans.
- Masquage auto de l'avatar quand une app est en plein écran
  (`SHQueryUserNotificationState`, plus fiable qu'une comparaison de rectangles).

**Vérification** : captures des deux thèmes ; bascule du thème Windows à chaud ;
parcours entier au clavier seul ; effets d'animation désactivés ; second écran à
facteur d'échelle différent.

### Phase 4 — Guidage visuel à l'écran

- Overlay transparent par moniteur, `WindowTransparentForInput` +
  `WS_EX_TRANSPARENT | WS_EX_LAYERED`, toujours au premier plan, ne capte aucun clic.
- Primitives animées : flèche/pointeur, cercle ou rectangle de mise en évidence avec
  le reste légèrement assombri, étapes numérotées, bulles de texte, et le sorcier qui
  vole jusqu'au point en émote `pointing`.
- Exposées à Claude comme outils via un **serveur MCP in-process**
  (`create_sdk_mcp_server` + `@tool`, confirmés présents dans le SDK) : `point_at`,
  `highlight`, `show_steps`, `clear_overlay`.
- **`mapping.py` est le point critique.** Claude raisonne en pixels de l'image envoyée
  (réduite à 1568 px) ; il faut revenir aux coordonnées logiques Qt en tenant compte du
  facteur de réduction, de l'origine de la zone capturée, du DPI par moniteur et des
  écrans à coordonnées négatives. Donc : `Capture` gagne un champ `frame` qui
  enregistre l'origine et l'échelle au moment de la capture, et `mapping.py` reste une
  fonction pure couverte par des tests paramétrés (origine négative, ratio
  1.0/1.25/1.5/2.0, zone hors écran, image non réduite).
- Mode tutoriel pas à pas avec Suivant / Précédent, `Échap` efface tout, effacement
  automatique après un délai configurable.
- Raccourci « écran actif » (sans sélection de zone).
- `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` sur nos fenêtres, **activé par
  défaut**, réglable via `ui.exclude_from_capture`, et **documenté dans le README** y
  compris son effet de bord sur les partages d'écran.

**Vérification** : tests de mapping (le cœur) ; à l'écran, demander à Claude de
pointer un bouton précis et mesurer l'écart en pixels ; vérifier qu'un clic passe bien
à travers l'overlay ; vérifier qu'une capture ne contient pas l'overlay.

### Phase 5 — La voix

- Micro par **QtMultimedia** (`QAudioSource`) : aucune dépendance ajoutée, niveau en
  direct pour la forme d'onde et un VAD simple par énergie.
- Reconnaissance et synthèse par **winrt** (`Windows.Media.SpeechRecognition`,
  `Windows.Media.SpeechSynthesis`), à l'intérieur d'un protocole `Recognizer` /
  `Synthesizer` — c'est ce protocole qui rend Whisper ajoutable plus tard sans toucher
  au reste.
- **Parler à Claude** : raccourci en appui maintenu (push-to-talk) ou en bascule.
  `RegisterHotKey` ne signale que l'appui, pas le relâchement, donc le maintien exige
  un `SetWindowsHookEx(WH_KEYBOARD_LL)` ; si ce hook échoue, on retombe sur le mode
  bascule en le disant. Pendant l'écoute : émote `listening` et forme d'onde près de
  l'avatar. La capture de l'écran actif est jointe **par défaut**, avec indicateur
  visible pendant la capture.
- **Dictée partout** : un raccourci, le texte transcrit s'insère dans le champ qui a le
  focus par `SendInput` Unicode ; repli presse-papiers avec restauration du contenu
  d'origine. Ponctuation automatique, et passage optionnel par Claude pour nettoyer
  hésitations et fautes.
- **Réponses parlées activées par défaut** (votre choix) : voix française OneCore,
  réponses courtes quand la sortie est vocale, émote `speaking`, interruption immédiate
  au raccourci ou dès que vous reparlez.
- Français par défaut, langue configurable. **Limite honnête à documenter** : la
  reconnaissance Windows exige le pack vocal de la langue installé ; s'il manque, la
  voix se désactive proprement avec un message expliquant où l'installer.
- Mot d'activation (« Hey Wizard ») : l'architecture le prévoit, l'option reste
  désactivée et sera traitée après tout le reste.

**Vérification** : la machine à états testée sans micro (tous les chemins, y compris
l'échec de transcription et l'interruption) ; dictée réelle dans le Bloc-notes, VS Code
et un champ de navigateur ; presse-papiers d'origine retrouvé intact.

### Phase 6 — Mode Live

- Transcription en direct du micro **et** de l'audio système (loopback WASAPI via
  `sounddevice`), dans un panneau compact et discret.
- Raccourci « Aide-moi » : Claude reçoit les dernières minutes de transcription et
  l'écran actif, et propose une réponse ou les points clés.
- À la fin : résumé, décisions, actions à faire, enregistrés dans l'historique.
- **Indicateur d'enregistrement visible en permanence** tant que le mode est actif, et
  au premier usage un rappel que les autres participants doivent être informés.

**Vérification** : une vraie visio de test, les deux voix transcrites et distinguables ;
couper le périphérique en cours de route et vérifier que le mode s'arrête proprement au
lieu de planter.

### Phase 7 — Historique des discussions

- Tout en SQLite avec l'échelle de migrations : conversations, messages, miniatures de
  captures, appels d'outils, transcriptions vocales et sessions Live, avec le
  `session_id` du SDK.
- Fenêtre Historique : groupée par date (aujourd'hui, hier, cette semaine…), recherche
  plein texte FTS5, filtres par type (question, voix, Live, agent), renommer, épingler,
  supprimer, exporter en Markdown.
- **Reprendre** une discussion via `resume` du SDK, directement depuis la liste.
- Vue en lecture seule de vos propres sessions Claude Code, lues dans
  `~/.claude/projects` (fichiers `.jsonl`) — lecture seule, jamais d'écriture là-bas.
- Rétention configurable et bouton « tout effacer ».

**Vérification** : migration d'une base v0 réelle (celle de `%APPDATA%`) vers v1 sans
perte ; recherche avec et sans accents (« reunion » trouve « réunion ») ; reprise d'une
vieille conversation qui continue bien le même fil.

### Phase 8 — Fonctionnalités d'assistant

Dans cet ordre :

1. **Actions sur la sélection** — mini-menu sur le texte sélectionné dans n'importe
   quelle app : traduire FR↔EN, reformuler, corriger, résumer, expliquer. Le résultat
   remplace la sélection ou va au presse-papiers, et le contenu d'origine est restauré.
2. **Agents en arrière-plan** — une tâche lancée avec un dossier de travail tourne dans
   sa propre session SDK, affiche sa progression sur un mini-avatar (réutilise
   `sessions.py`), passe par le même panneau d'approbation, et notifie à la fin.
3. **Mémoire** — `memory.md` éditable depuis les paramètres, ajouté au system prompt.
4. **OCR local** (`Windows.Media.Ocr`) — « copier le texte de cette zone » sans passer
   par Claude.
5. **Rappels en langage naturel** via un outil MCP `set_reminder`. Ils restent **en
   mémoire** (votre choix), donc perdus au redémarrage — et l'interface le dit.
6. **Presse-papiers étendu aux images**.

Puis je vous en proposerai d'autres.

---

## Vérification globale

Au-delà de chaque phase :

1. `pytest` — parsers, stockage et migrations, mapping de coordonnées, machine à états
   de la voix, écriture de config préservant les commentaires, protocole du pont.
2. `ruff check src tests tools hooks`.
3. **Non-régression sur Claude Code** : hooks installés, mesurer une session témoin,
   tuer l'app, refaire la même session. Écart attendu : nul.
4. **Mode dégradé** : chaque extra absent une par une (`[voice]`, `[live]`, `[ocr]`),
   l'app doit démarrer et désactiver proprement la fonction.
5. **Budget au repos** : mesure sur 60 s, cible < 1 % d'un cœur, avec l'overlay et le
   mode Live à l'arrêt.
6. Bout en bout à l'écran : capture → question → réponse → l'overlay montre l'endroit,
   terminal jamais visible.

---

## Ce que ce plan ne fait pas

- **Vérifier Mica/Acrylic** : impossible sur Windows 10. Le code existera, le repli
  sera testé, le chemin Win11 sera marqué non vérifié.
- **`faster-whisper`** : écarté sur votre consigne. Branchable derrière le protocole
  `Recognizer` quand vous voudrez.
- **Packaging PyInstaller** : pas de wheel cp314. Je le signale, je ne le contourne pas
  en silence.
- **Lire l'URL du navigateur** par UI Automation : beaucoup de travail, fragile, et la
  capture montre l'URL de toute façon.
- **Mot d'activation** : architecture prévue, désactivé, traité en dernier.
- **CI** : il n'y en a pas aujourd'hui. À signaler, hors périmètre.

---

## Migration UI — de Qt Widgets à Tauri 2

Référence : `DESIGN.md` (renommé depuis `design_md.md` et suivi par git à la
phase M1).

**Validé le 2026-10-02** avec les quatre propositions par défaut : complément de
protocole écrit dans DESIGN.md §2, phase M6 bis adoptée, `DESIGN.md` commité,
installation de Rust (M2) et de Python 3.13 (M7) repoussée à ces phases.

**Ce qui ne change pas :** tout le code Python qui fonctionne reste le « core » :
Agent SDK, pont hooks, SQLite et migrations, historique, OCR, captures et
`overlay/mapping.py`, presse-papiers, raccourcis, agents, mémoire, rappels. Seules
les fenêtres partent.

### Environnement vérifié pour cette migration

| Élément | État | Conséquence |
|---|---|---|
| Node.js / npm | 22.12 / 10.9 | OK pour Vite, React, Motion |
| WebView2 | 154 installé | OK, Tauri peut afficher |
| Build Tools C++ | Visual Studio Build Tools 2019 | OK pour compiler Rust |
| **Rust / cargo** | **absent** | **À installer (rustup) avant la phase 2** — décision et installation à vous |
| `PySide6.QtWebSockets` | disponible | `QWebSocketServer` utilisable, aucune dépendance ajoutée |
| **Python 3.12 / 3.13** | **absents** (3.14 et 3.11 seulement) | **À installer avant la phase 7** pour PyInstaller |

### Le point clé : « headless » ne veut pas dire « sans Qt »

Le core garde une `QApplication` sur la **vraie** plateforme Windows (pas
`offscreen`), simplement sans afficher aucun widget. C'est ce qui fait marcher sans
changement : `QScreen` et `grabWindow` (captures), `QCursor.pos()`, le presse-papiers,
`QLocalServer` (pont hooks) et `RegisterHotKey` (la fenêtre propriétaire des
raccourcis est déjà une fenêtre native jamais affichée). Le mode `offscreen` des
tests, lui, ne sait ni capturer l'écran ni recevoir de raccourcis : il ne convient
pas au core réel.

### Inventaire : où le code dépend d'un widget Qt visible, et ce qu'on en fait

| Dépendance actuelle | Fichier | Traitement |
|---|---|---|
| Placement de l'avatar (`availableGeometry`, coin de la barre des tâches, position mémorisée, « est-il encore sur un écran ? ») | `avatar_window.py` | Passe côté Tauri (`Monitor::work_area`, position sauvegardée côté UI). La logique `_reserved_edge` / `_clamp_to` est portée telle quelle en TS, avec ses tests |
| **Cloak** (cacher nos fenêtres le temps d'une capture) | `capture/cloak.py` | Le core ne peut plus cacher des fenêtres d'un autre processus. Il envoie `cloak.hide`, attend `cloak.ack` (délai max 600 ms), attend 80 ms de repaint, capture, envoie `cloak.show`. **Sans ack à temps, la capture est annulée** avec un message, plutôt que d'envoyer une image qui contiendrait nos fenêtres. Le `Cloak` actuel devient une interface à deux implémentations (widgets locaux / UI distante) |
| Sélection de zone (voile + rectangle élastique) | `capture/region.py` | Passe dans les fenêtres overlay Tauri. Le core reçoit `capture.region { screen_id, x, y, w, h }` en pixels logiques, puis fait le `grab_rect` existant. La fonction de capture reste en Python |
| Ctrl + glisser l'avatar sur une fenêtre (halo arc-en-ciel) | `capture/window.py`, `controller.py` | Le glisser se fait dans l'avatar Tauri, qui envoie la position ; le core répond avec le rectangle de la fenêtre visée (`WindowFromPoint`) ; l'UI dessine le halo. Les fenêtres à ignorer deviennent « toutes celles du processus Tauri » (PID transmis au `hello`), au lieu d'une liste de handles Qt |
| Overlay (flèche, surlignage, étapes) | `overlay/surface.py`, `manager.py` | Remplacé par le curseur guide Tauri (§6). Le core garde `mapping.py` et les outils MCP, et émet `guide.*` en pixels logiques d'écran. La machine à états du tutoriel (`scene.py`) passe côté UI, puisque Précédent/Suivant sont dans le panneau |
| Vol de l'avatar jusqu'à la cible | `app.py` `_fly_towards` | **Supprimé** : DESIGN §6 dit que l'avatar reste chez lui et que c'est le curseur guide qui vole |
| Échap pendant l'affichage d'un guide | `app.py` `_grab_escape` | Reste dans le core (raccourci global). L'UI signale `guide.active { true/false }` pour que le core réserve puis libère Échap |
| Masquage en plein écran | `app.py` `_update_quiet_mode` | La détection reste dans le core ; il émet `quiet { on }`, l'UI cache ses fenêtres |
| Exclusion du partage d'écran (`WDA_EXCLUDEFROMCAPTURE`) | `app.py` `_protect` | Doit être appliquée par Tauri (Rust, sur le HWND de chaque fenêtre). **À vérifier en phase 2** : on a mesuré que Windows la refuse sur les fenêtres « layered » ; on ne sait pas encore si une fenêtre WebView2 transparente l'est |
| Fenêtres modales bloquantes (`QMessageBox`, `QMenu.exec`, `HookDiffDialog.confirm`, `dialog.exec()` de l'accueil) | `app.py` (8 appels) | Deviennent des requêtes protocole avec réponse corrélée par `id`. Le core n'attend jamais en bloquant : il reprend quand la réponse arrive |
| Menu de l'icône de notification | `tray.py` | Passe dans Tauri (`tray`), ses entrées deviennent des commandes |
| Mini-sorciers des sessions | `ui_sessions.py` | Passent dans l'UI à partir de `sessions.update` |
| Le personnage en QPainter | `character/painter.py`, `sheet.py` | Remplacé par l'avatar Canvas de DESIGN §4 (un dessin plus simple et différent). L'icône d'app sera régénérée depuis le nouveau dessin (phase 7) |

### Ce que le protocole de DESIGN §2 ne couvre pas encore

DESIGN.md dit qu'une décision d'interface doit y figurer **avant** d'être codée. Le
protocole listé §2 ne suffit pas pour la phase 1 ; il faut y ajouter, avant de coder :

- **Connexion :** `hello { token, protocol, role, pid }` → `hello.ok` / fermeture.
- **Erreurs et réponses :** `reply { id, ok, payload | error }` pour toute commande qui attend une réponse.
- **Ouverture du panneau** par un raccourci : `panel.open { state }`.
- **Plein écran :** `quiet { on }`. **Guide :** `guide.active`, et la navigation du tutoriel.
- **Captures :** `capture.region`, ciblage de fenêtre (`target.move` → `target.window`, `target.pick`).
- **Requêtes de données** pour les fenêtres que DESIGN prévoit mais que la liste ne nourrit pas : `history.*`, `settings.get|set`, `palette.query`, `hooks.plan|apply`.

Je propose ce complément à DESIGN.md en même temps que la phase 1.

### Écart de périmètre à trancher avant la phase 7

Les 7 phases demandées couvrent l'avatar, le panneau et le curseur guide, mais **pas**
les fenêtres Paramètres, Historique, Accueil, palette de commandes, confirmation des
hooks, lancement d'agent. Or la phase 7 supprime les `ui_*.py` qui les portent.
Sans phase dédiée, ces fonctions disparaîtraient. Je propose une **phase 6 bis —
Fenêtres secondaires** (Paramètres, Historique, Accueil, Hooks, Agents ; la palette
devient le `/` de la barre, comme le prévoit DESIGN §5).

### Principe de transition

Jusqu'à la phase 7, **l'interface Qt actuelle reste le mode par défaut et continue
de marcher**. `--headless` est opt-in. Le passage se fait à l'intérieur de `app.py`
par une seule couture : un `Presenter` (afficher une humeur, un toast, une
approbation, un flux de réponse…) avec deux implémentations, `QtPresenter` (les
widgets d'aujourd'hui) et `ProtocolPresenter` (émet sur le WebSocket). La logique
métier n'appelle plus jamais un widget directement. À la phase 7, `QtPresenter` et
les `ui_*.py` disparaissent.

---

### Phase M1 — Protocole, serveur WebSocket, `--headless`

**Créé**
- `protocol/messages.json` — la liste unique des types de messages et de leurs champs, lue par les deux côtés (pas de dérive possible entre Python et TypeScript).
- `protocol/fixtures/*.json` — messages d'exemple valides et invalides, utilisés par les tests des deux côtés.
- `src/wizard/protocol.py` — encodage, décodage, validation, numéro de version.
- `src/wizard/ws_server.py` — `QWebSocketServer` sur `127.0.0.1`, port aléatoire.
- `src/wizard/presenter.py` — l'interface `Presenter`, `QtPresenter`, `ProtocolPresenter`.
- `ui/package.json`, `ui/src/protocol.ts`, `ui/src/protocol.test.ts` (Vitest seulement ; l'app React vient en M2/M3).
- `tests/test_protocol.py`, `tests/test_ws_server.py`, `tests/test_headless.py`.

**Modifié**
- `app.py` : passe par le `Presenter` ; `--headless` construit le core sans aucune fenêtre visible.
- `__main__.py` : options `--headless`, et en headless l'annonce du port sur la sortie standard (`WIZARD_READY {"port": …}`) pour que Tauri le lise.
- `capture/cloak.py` : interface + implémentation « UI distante ».

**Retiré :** rien. L'interface Qt reste le défaut.

**Sécurité du canal** (un WebSocket local est joignable par n'importe quelle page web
ouverte dans un navigateur de la machine) :
- jeton secret aléatoire, transmis au core **par variable d'environnement** (pas en
  argument : la liste des processus affiche les arguments), comparé en temps constant ;
- premier message obligatoire `hello` avec le jeton sous 2 s, sinon fermeture ;
- vérification de l'en-tête `Origin` (seules les origines Tauri et le serveur de dev sont acceptées) ;
- écoute sur `127.0.0.1` uniquement, taille de message plafonnée ;
- le jeton n'est jamais écrit dans un log.

**Vérification**
- `pytest` : aller-retour encodage/décodage, chaque fixture valide acceptée et chaque invalide refusée ; serveur : mauvais jeton → fermé, pas de `hello` → fermé, mauvaise origine → refusé, message trop gros → refusé, deux clients reçoivent les mêmes événements.
- Vitest : `protocol.ts` accepte et refuse les mêmes fixtures.
- Test de bout en bout : lancer `python -m wizard --headless`, lire le port, se connecter avec le jeton, recevoir `hello.ok` puis `mood` et `connection` ; simuler une demande d'approbation et y répondre ; demander une capture et vérifier la séquence `cloak.hide` → `cloak.ack` → capture → `cloak.show`.
- `EnumWindows` sur le processus headless : **aucune fenêtre visible**.
- Mode Qt : les 648 tests existants passent toujours, l'app se lance comme avant.

**Risques**
- `app.py` fait ~1 200 lignes et appelle les widgets directement à de nombreux endroits : la couture `Presenter` est le gros du travail. Mitigation : migration appel par appel, tests existants verts à chaque étape.
- Les fenêtres modales bloquantes deviennent asynchrones : une réponse peut ne jamais venir (UI fermée). Chaque requête a un délai, et l'absence de réponse prend le choix sûr (approbation → refus, capture → annulée, hooks → rien n'est écrit).

**Fait (M1)** — 745 tests Python (97 nouveaux) et 43 tests Vitest verts, lint propre.
Écarts par rapport au plan ci-dessus, et pourquoi :
- La spécification est `src/wizard/protocol_messages.json` et non `protocol/messages.json` :
  le core empaqueté doit pouvoir la lire, elle doit donc être dans le paquet. Les fixtures
  partagées sont `tests/protocol_fixtures.json`.
- `presenter.py` est découpé en trois fichiers (`presenter.py` l'interface,
  `presenter_qt.py`, `presenter_remote.py`) : à la phase M7, `presenter_qt.py` se supprime
  d'un bloc.
- Le ciblage par Ctrl + glisser n'est pas dans le protocole : il dépend du glisser de
  l'avatar Tauri, il sera défini en M4. Le dépôt de fichier, lui, y est (`capture.file`).
- Ajout de `screens.py` (conversion bureau ↔ écran), utilisée par le guide et la sélection
  de zone, et de Prettier en dépendance de développement de `ui/` (formateur standard TS).
- Les menus et fenêtres modales devenus asynchrones en headless : menu de sélection →
  `selection.menu`/`selection.pick` ; menu des mini-sorciers → `session.dismiss`,
  `agent.stop` et le compte rendu dans `sessions.update` ; diff des hooks, accueil et
  fenêtres secondaires → `window.open`, sans rien écrire.

Vérifié sur la vraie plateforme Windows (pas `offscreen`), par un script qui lance le core
comme le fera Tauri : **0 fenêtre visible** (5 fenêtres internes de Qt, cachées) ; origine
étrangère refusée ; capture d'écran via `cloak.hide` → `cloak.ack` → `cloak.show` en
0,35 s, PNG valide ; **0,08 % d'un cœur au repos** sur 60 s avec un client connecté ; arrêt
propre en 0,3 s par `action quit`. Le mode Qt par défaut démarre toujours (avatar visible,
aucune erreur). Ce script a trouvé un vrai bug : à la sortie du processus, un socket détruit
avant son gestionnaire `disconnected` levait une exception — corrigé (`UiServer.stop()`
débranche ses gestionnaires avant de fermer).

### Phase M2 — Squelette Tauri

**Créé** : `ui/src-tauri/` (Rust : `main.rs`, `core.rs` lancement/surveillance du core,
`windows.rs`, `tray.rs`, `tauri.conf.json`), `ui/src/` avec une page par fenêtre
(avatar, panel, overlay) qui se connecte et affiche les événements bruts.

- Fenêtres : avatar (72 px, transparente, toujours au premier plan, sans focus, sans barre des tâches) ; panel (transparente, ancrée) ; **une overlay par écran**, recréées quand on branche ou débranche un écran ; tray.
- Lancement du core en tâche de fond (`python -m wizard --headless` en dev, l'exe en prod), lecture du port, **redémarrage s'il plante** avec temporisation croissante et abandon après plusieurs échecs rapprochés, arrêt propre à la fermeture (Windows ne tue pas les processus enfants : on l'a mesuré avec les agents).

**Vérification** : l'avatar apparaît au-dessus de la barre des tâches ; tuer le core à la main → Tauri le relance et les fenêtres se reconnectent ; un clic traverse l'overlay (même test `WindowFromPoint` que pour l'overlay Qt) ; aucune fenêtre ne vole le focus pendant qu'on tape ailleurs.

**Risques à lever dans cette phase, pas plus tard**
- `WDA_EXCLUDEFROMCAPTURE` sur une fenêtre WebView2 : à mesurer (voir l'inventaire).
- Fenêtre panel « sans focus sauf quand on tape » : la bascule de focusabilité d'une fenêtre Tauri à l'exécution est à vérifier.
- Fenêtre overlay traversée par les clics et toujours au premier plan sur Windows 10.
- Mémoire : chaque fenêtre WebView2 a son processus de rendu ; il faut mesurer le total (aujourd'hui 67 Mo).

### Phase M3 — Playground navigateur

**Créé** : `ui/src/playground/` — `npm run dev` ouvre une page qui affiche les
fenêtres côte à côte et **rejoue des scénarios factices** (`scenarios/*.json` :
réponse en streaming, approbation avec compte à rebours, capture, curseur qui
pointe sur deux écrans, hors ligne). Une fausse source d'événements remplace le
WebSocket ; elle n'a aucun lien avec le core.

**Vérification** : chaque scénario se joue sans erreur ; un test Vitest charge tous les scénarios et vérifie qu'ils respectent `protocol/messages.json`.

**Risque** : faible. Le seul piège est que le faux et le vrai divergent — d'où la validation des scénarios contre le même schéma.

### Phase M4 — Design tokens et avatar Canvas 2D (DESIGN §3, §4)

**Créé** : `ui/src/design/tokens.ts` (+ variables CSS), `ui/src/avatar/` (dessin,
machine à états, respiration, clignement, regard, orbe), `ui/src/motion.ts` (les
quatre ressorts, réglage « mouvement réduit »).

**Vérification** : chaque état du tableau DESIGN §4 visible dans le playground ; test du mapping humeur du core → état visuel (complet, comme le test actuel sur les poses) ; **budget CPU mesuré** sur l'app réelle au repos.

**Risque principal : le budget de 1 % d'un cœur.** Un Canvas animé avec
`requestAnimationFrame` tourne à 60 images/s par défaut, soit bien pire que
l'avatar Qt actuel. Il faudra : ne redessiner que si l'image change (la même
technique qu'on vient d'appliquer en Python), cadence réduite au repos, arrêt
complet quand la fenêtre est cachée. À mesurer, pas à supposer.

### Phase M5 — Le panneau et ses états (DESIGN §5)

**Créé** : `ui/src/panel/` (`bar`, `answer`, `approval`, `capture`, `selection`,
toasts), la machine à états du §5, le rendu Markdown et les blocs de code avec
Copier, l'anneau de compte à rebours autour de l'avatar.

**Vérification** : tests de la machine à états (toutes les transitions du schéma
§5, y compris `approval` qui revient à l'état précédent) ; au clavier seul : ouvrir,
envoyer, Échap ferme toujours, Entrée = Autoriser, Échap = Refuser ; une approbation
sans réponse est refusée ; aucune capture ne part sans l'écran `capture`.

**Risque** : le redimensionnement de fenêtre « taille finale d'abord, puis
animation » (§5) dépend du comportement de Tauri sous Windows ; à prototyper en
premier dans la phase.

### Phase M6 — Le curseur guide (DESIGN §6)

**Créé** : `ui/src/guide/` (états `follow` … `returning`, vol en Bézier, surlignage,
étapes), et **une seule fonction** de conversion écran → fenêtre overlay.

**Vérification** : la fonction de conversion testée à 100, 125, 150, 175 et 200 % et
sur écrans à coordonnées négatives (les mêmes cas que `test_overlay_mapping.py`) ;
le curseur n'apparaît jamais dans une capture (cloak) ; Échap efface tout ; mouvement
réduit → pas de vol, simple fondu.

**Risques** : suivre le vrai pointeur demande sa position en continu — ce sera un
abonnement actif **seulement** en mode `follow`, jamais au repos, sinon le budget
CPU saute. Le vol entre deux écrans de facteurs d'échelle différents. La précision
par UI Automation (§6) est explicitement une phase ultérieure.

### Phase M6 bis — Fenêtres secondaires (proposée, voir plus haut)

Paramètres, Historique, Accueil, confirmation des hooks, lancement d'agent, en
fenêtres Tauri normales nourries par les requêtes `settings.*`, `history.*`,
`hooks.*`. La palette devient le `/` de la barre.

### Phase M7 — Suppression du Qt visible, puis packaging

**Retiré** : `ui.py`, `ui_*.py`, `avatar_window.py`, `tray.py`, `overlay/surface.py`,
`overlay/manager.py`, `capture/region.py` (le voile ; `grab_rect` est déplacé),
`capture/window.py` (le halo ; la recherche de fenêtre reste), `design/qss.py`,
`design/surface.py`, `character/painter.py` et `sheet.py`, `QtPresenter`, et les
tests de ces widgets. `--headless` devient le seul mode.

**Packaging** : le core en exe PyInstaller (`--onedir` plutôt que `--onefile`, qui se
réextrait à chaque lancement) sous **Python 3.13** dans un venv dédié, déclaré en
`externalBin` dans Tauri ; installeur Tauri (NSIS ou MSI).

**Vérification** : `pytest` vert après suppression ; `git grep QtWidgets` ne trouve
plus que la fenêtre propriétaire des raccourcis ; installer sur une session Windows
propre, lancer, capturer, poser une question, tuer le core et le voir revenir ;
désinstaller sans laisser de processus.

**Risques** : wheels `winrt-*` et `sounddevice` à vérifier pour cp313 (vérifiés
aujourd'hui pour cp314 seulement) ; taille de l'exe (PySide6 + SDK) ; antivirus qui
signalent les exe PyInstaller non signés.

---

### Questions à trancher avant la phase M1

Tranchées le 2026-10-02 (voir en tête de section). Reste ouvert : **qui installe Rust**
avant la phase M2 (`rustup`, environ 1 Go avec la chaîne MSVC déjà présente).
