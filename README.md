# Little Wizard

A small animated wizard who floats just above the Windows taskbar, with a tray
icon, global hotkeys, clipboard history, quick notes and countdown reminders.
He shows you what your machine and your Claude Code sessions are doing, and he
answers questions about whatever is on your screen.

> **This app used to be called Lutin.** The rename moved its data folder from
> `%APPDATA%\Lutin` to `%APPDATA%\LittleWizard`, so the first start after
> upgrading **copies** your settings, notes, clipboard history and saved avatar
> position across and tells you it did. The old folder is left exactly as it
> was — delete it yourself once you are satisfied. If you had the Claude Code
> hooks installed, they still point at the old script name: the tray menu
> offers *Hooks Claude Code…* → *Réinstaller…* to fix that, and says so on
> startup.

## Requirements

- Windows 10 or 11, with WebView2 (built into Windows 11, installed by Edge on
  Windows 10)
- To run from source: Python 3.11+ (tested on 3.14), Node 20+, and Rust
  (`rustup`, MSVC toolchain) for the Tauri shell

Two halves, one app. **The core** is Python (PySide6 without any window, the
Claude Agent SDK, SQLite): hotkeys, captures, Claude, the hook bridge, the
data. **The UI** is Tauri 2 (React, TypeScript, WebView2): the avatar, the
panel, the guide cursor, the app window, the tray icon. Tauri starts the core
and they talk over a local WebSocket (see *How the UI talks to the core*).

Optional extras of the core, each of which the app starts fine without:

| Extra | Brings | Needed for |
|---|---|---|
| `[voice]` | Windows on-device speech bindings (~5 MB, no model download) | talking to Claude, dictation, spoken answers |
| `[live]` | `sounddevice` | transcribing system audio during a meeting |
| `[ocr]` | Windows OCR bindings | copying text out of a screen region locally |

## Install

From source:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd ui
npm install
npm run tauri dev     # Vite + the Rust shell, which starts the core
```

The shell finds the core in the repository's `.venv` (or wherever the
`WIZARD_CORE` environment variable points). Packaging into one installer is
described in *Packaging*.

> **Windows 10 hides new tray icons.** On first run the wizard's tray icon goes
> into the overflow area behind the `^` chevron. Drag it onto the taskbar, or
> use *Taskbar settings → Select which icons appear on the taskbar*, to keep it
> visible.

## What it does

> **The interface is in French; the code is in English.** Identifiers, comments,
> docstrings and this README stay English, as does anything the user never sees
> (the `Mood` values, config keys, hotkey modifier names). Everything displayed —
> menus, dialogs, notifications, the comments inside `config.default.toml` — is
> French. Strings are inline rather than routed through a translation layer,
> because the app targets one language and that pipeline would be pure ceremony.

| Action | Hotkey | Menu entry |
|---|---|---|
| Ask Claude | `Ctrl+Alt+C` | *Demander à Claude…* |
| Show a screen region | `Ctrl+Alt+S` | *Montrer une zone…* |
| Show the whole active screen | `Ctrl+Alt+E` | — |
| Act on the selected text (translate, fix, summarise…) | `Ctrl+Alt+T` | — |
| Copy the text in a screen region (local OCR) | `Ctrl+Alt+O` | — |
| Launch a background agent | — | *Lancer un agent…* |
| Conversation history | — | *Historique des discussions…* |
| Show a window | `Ctrl`+drag the avatar onto it | — |
| Show an image | drop the file on the avatar | — |
| Quick note | `Ctrl+Alt+N` | *Note rapide* |
| Clipboard history | `Ctrl+Alt+V` | *Presse-papiers* |
| Command palette | `Ctrl+Alt+Space` | `/` in the panel's bar |
| Show / hide the avatar | `Ctrl+Alt+A` | *Masquer / Afficher le sorcier* |
| Reminders | — | *Me rappeler…* |

- **The command palette** (`Ctrl+Alt+Space`) opens the panel's bar with `/`
  typed: the actions, the views of the app window, your launcher entries and
  the running agents, in one list. Fuzzy, accent-insensitive (`reunion` finds
  *Réunion*), and entirely keyboard-driven. Type a reminder in plain words
  (`/rappel dans 20 min sortir le pain`) and it is offered first.
- **Click the avatar** to open the panel; **drag him** to move him anywhere,
  and he remembers where you left him (tray: *Replacer sur la barre*).
- **Clipboard history** records copies into SQLite, skipping blanks and
  consecutive duplicates, pruned to `max_entries`. Double-click an entry in the
  app window to put it back on the clipboard (a picture as a picture).
- **Moods** come from CPU, RAM and battery: calm → busy → stressed, plus a
  tired face when you are below `battery_low` on battery power. A mood that
  comes from Claude — a session working, or waiting for your answer — outranks
  the machine's, because one needs you and the other is just weather.
- **The staff is the status light.** Its colour and its pulse are the state
  indicator, rather than a badge stuck to the side of the character: gold at
  rest, blue while Claude works, bright amber pulsing when something is waiting
  on you. He also dozes off after three minutes of nothing, and wakes when you
  come near.
- **Reminders** accept `25`, `25m`, `1h30`, `90s` or `25:00`, with presets
  including a 25-minute pomodoro.
- **Captures** are downscaled to a 1568px long edge (past that Claude
  downsamples anyway) and always shown in the panel for confirmation before
  they can be used. Plain drag still moves the avatar; `Ctrl`+drag is what
  points at a window (released over it), so neither gesture shadows the other.

- **Claude** answers in the wizard, never in a terminal. The conversation is one
  long-lived connection rather than a fresh CLI per question, so asking twice
  costs one startup, not two. Confirming a capture
  opens the question panel; the answer streams back in place. The conversation
  persists (the SDK's `resume`) until *Nouvelle discussion Claude*.
- **Approvals** appear on the avatar with Autoriser / Toujours / Refuser, for
  both the sessions Little Wizard starts and the ones you run yourself. Not answering
  denies: silence is not consent.
- **Your own Claude Code sessions** show up too, once the hooks are installed:
  what each one is reading, editing and running, one coloured line per session
  above the panel's bar, with the agents the wizard runs (*Arrêter* stops one).

## Claude Code hooks

*Hooks Claude Code…* → *Installer…* in the tray menu adds Little Wizard to
`~/.claude/settings.json` so your own sessions show up in the avatar and their
permission prompts can be answered there. Before writing anything it backs the
file up with a timestamp, **merges** rather than replaces, and shows you the
exact diff. Uninstalling removes only Little Wizard's entries.

The rule that governs the whole bridge: **a Claude Code session is never
blocked by Little Wizard.** Observational events are registered with `"async": true`,
so they cannot delay a session at all. Only `PermissionRequest` waits, and
every failure path in the hook exits 0 with no output, which leaves the normal
permission flow untouched. Measured with the app stopped: the hook returns in
about 0.6s having rendered no decision, and the terminal asks you as usual.

Hooks run in exec form (`command` + `args`) pointing at `pythonw.exe`, a real
executable, so no shell is spawned per tool call and no console window appears.

## Requirements for the Claude features

Claude Code must be logged in on this machine:

```powershell
claude auth status    # "loggedIn": true
claude auth login     # if not
```

Little Wizard uses your existing subscription through the Agent SDK. There is no API
key to obtain and nothing billed on top.

**The connection opens at startup**, in the background, so the first question
does not wait for it (`claude.prewarm`, on by default). The staff carries the
result: lit in its usual colour when the link is up, a slow pale pulse while it
is connecting, and drained grey when it is not. The tray tooltip and menu say
why.

> **A missing login does not announce itself at connection time.** The CLI
> starts and the handshake succeeds; only the first real question comes back
> with *"OAuth session expired and could not be refreshed"*. So the connection
> state follows the first turn's verdict rather than the handshake's, and
> Little Wizard shows you the `claude auth login` instruction instead of the raw
> English error. It then stops retrying, because retrying cannot log anyone in —
> asking again after you have logged in reconnects immediately.

Other failures (a dropped pipe, a killed CLI) do retry, backing off 1, 2, 4 …
up to 60 seconds.

## Configuration

Edit `%APPDATA%\LittleWizard\config.toml` (created on first run from
`src/wizard/config.default.toml`), then pick **Recharger la configuration** in the tray menu.
No restart needed, hotkeys included.

Launcher entries take anything the Run dialog accepts — an executable, a
document, a folder, a `shell:` moniker or a URL:

```toml
[[launcher]]
label = "Project"
target = "code"
args = ["C:\\Users\\me\\projects\\thing"]

[[launcher]]
label = "Downloads"
target = "shell:Downloads"
```

A malformed file never blocks startup: bad values fall back to defaults and the
app reports what it ignored in a tray notification.

## Data and privacy

What is stored, all of it on your machine, in `%APPDATA%\LittleWizard\`:

- `config.toml` — your settings
- `wizard.db` — notes, clipboard history, and the history of your
  conversations with Claude (SQLite): questions, answers, the actions you
  allowed or refused, and a **256 px thumbnail** of each capture — never the
  full image. Turn it off with `history.enabled = false`, purge it by age with
  `history.retention_days`, or wipe it with *Tout effacer…* in the History
  window.
- `state.ini` — the avatar's last position
- `memory.md` — what you asked Claude to remember about you, if you wrote one

`%APPDATA%\Lutin\` may also still exist: it is the pre-rename folder, kept as a
backup, plus a `.migrated-to-LittleWizard` marker. Nothing reads it after the
first start.

**What leaves your machine.** Asking Claude sends your question and, when you
attach one, the capture — to Anthropic, through the Claude Code CLI you are
already signed in to. That is the whole point of the feature, and it is the only
network traffic this app causes: there is no telemetry, no analytics and no
other endpoint. Three more things are sent, each only because you asked:

- **`memory.md`**, with every question, if you wrote one.
- **The selected text**, when you use an action on a selection.
- **A background agent's task** and whatever it reads in the folder you gave it.

Local OCR sends nothing. Two guarantees around captures:

- **No capture is ever sent without you seeing it first**, in a confirmation
  window that shows exactly the image that will go. There is deliberately no
  setting to skip it.
- **Nothing is captured in the background.** Every capture starts from an action
  you took.

Since clipboard history captures whatever you copy — passwords included — turn
*Enregistrer l'historique du presse-papiers* off (Paramètres → Système) before
copying secrets, or set `clipboard.enabled = false`. **Copied images are kept
too** (screenshots included) — `clipboard.images = false` stops that while
keeping text. A screenshot carries the same risk over a wider
area: displayed passwords, private messages, client data. Check the preview.

The History window's *Mes sessions Claude Code* view **reads** the transcripts
in `~/.claude/projects` when you open it, and never writes to them. Nothing
from them is copied into `wizard.db`.

**Headless mode listens locally.** `--headless` (the core for the Tauri UI
being built, see below) opens a WebSocket on `127.0.0.1` only, on a random port.
It is not reachable from the network, and since any web page open in a browser
on this machine *could* reach it, every connection must present a secret token
within two seconds, and connections from a web origin other than our own UI's
are refused. The token is handed over by the process that launched the core and
removed from its environment at once, so Claude Code, agents and launched apps
never inherit it. It is never logged. The default (Qt) mode opens no socket.

*Lancer au démarrage de Windows* writes one `HKCU\...\CurrentVersion\Run` value
and removes it when you untick it. The first start after the rename also removes
the old `Lutin` value and writes the new one in its place, so autostart keeps
working. Nothing else touches the registry.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest
```

The suite covers the logic that is worth protecting and does not need a
display: config parsing and clamping, SQLite behaviour (dedup, pruning, LIKE
escaping), the mood thresholds, the hotkey/duration parsers, image sizing,
the hook framing and settings.json surgery, and the rename migration.

The protocol shared with the Tauri UI is tested from both sides, against the
same fixtures (`tests/protocol_fixtures.json`):

```powershell
cd ui
npm install
npm run check      # tsc --noEmit, then Vitest
```

## Assistant features

**Actions on the selected text** (`Ctrl+Alt+T`) — in any application: pick
*Traduire en anglais / en français, Reformuler, Corriger, Résumer* or
*Expliquer*. The result opens in a small window, editable, with *Remplacer la
sélection* (pasted back into the app it came from) or *Copier*. There is no API
for another app's selection, so it does what a person would — Ctrl+C, then
Ctrl+V — with three precautions: it waits for you to release the shortcut's
keys (Ctrl+C sent while Ctrl+Alt are still down is Ctrl+Alt+C, this app's own
"ask Claude" shortcut); it watches the clipboard's sequence number rather than
its text, so a selection identical to what was already copied is still seen;
and it snapshots every clipboard format and **puts your clipboard back**
afterwards, rich text and images included, without any of it landing in the
clipboard history. The job runs as its own one-question Claude session **with
no tools**: selected text can be someone else's email containing instructions,
and a job that can only return text cannot be talked into anything else. It
never touches the conversation in the answer panel.

**Background agents** (*Lancer un agent…*) — a task and a folder; the agent
works in its own Claude Code session, every action still goes through the
approval card (the card says which agent is asking), and a toast reports when
it is done. At most three run at once. Each one — and each of your own Claude
Code sessions seen through the hooks — gets a **mini-wizard** beside the main
one, in the pose of its state (working, waiting for you, done, failed), ringed
in its colour; hover for its last actions, click to read the report or stop it.
They are drawn once per change, never animated, so they cost nothing at rest.

**Memory** (*Paramètres → Mémoire*) — a `memory.md` in the config folder,
added to Claude's instructions: how you like to be answered, what you work on.
Capped at 6,000 characters in what is sent (the file itself is never cut), and
HTML comments are not sent.

**Copy the text in a region** (`Ctrl+Alt+O`) — Windows' own OCR, on the
machine: nothing is sent, nothing is billed. French and English here. The
region is read at full resolution (the downscale meant for Claude would blur
small interface text) and doubled when small. One trap worth recording: called
on the GUI thread, the WinRT calls **deadlock** — Qt makes that thread a COM
single-threaded apartment, WinRT delivers completions there as window messages,
and nothing pumps them. They always run on a thread of their own.

**Reminders in plain words** — type *rappelle-moi dans 20 minutes d'appeler
Koffi* in the command palette and it becomes the top suggestion; *dans une
heure et demie*, *dans un quart d'heure*, *à 15h30* work too. Claude can set one
with its `set_reminder` tool. Reminders still live **in memory**: closing the
app loses them, and every message that creates one says so.

**Images in the clipboard history** — copied pictures and screenshots are kept
too, with a thumbnail, and can be copied back. They are capped (2,560 px on the
long edge, 30 kept by default) because a screenshot weighs what two hundred
text clips do.

## Conversation history

*Historique des discussions…* (tray menu or command palette) lists every
conversation, grouped by day with pinned ones on top, and filters by kind.
Search is SQLite FTS5 with accent folding, so `reunion` finds *réunion*; what
you type is turned into quoted prefix terms first, so a stray quote or `OR`
is searched for rather than parsed as query syntax (raw FTS5 raises on an
unbalanced quote). Rename, pin, delete, export to Markdown — and **Reprendre**,
which reconnects with the SDK's `resume` so Claude has the old context back.

The last filter, *Mes sessions Claude Code*, reads the transcripts Claude Code
keeps in `~/.claude/projects`. Strictly read-only: those files are Claude
Code's state, and a damaged transcript can break resuming it in the terminal.
Their format is Claude Code's and changes between versions, so the reader
skips anything it does not recognise instead of failing.

**The schema is versioned now.** It used to be a `CREATE TABLE IF NOT EXISTS`
script, which works right up to the first new column: on an existing database
the create is skipped and the next query fails, on the user's machine only.
`schema.py` is a ladder of numbered migrations on `PRAGMA user_version`, each
applied once inside a transaction; a failed step leaves nothing behind, and a
database newer than the code is refused rather than touched. Verified on a
copy of a real pre-versioning database: version 0 to 3, every row identical.

## On-screen guidance

Claude can *show* things on your screen, not only describe them: an arrow at a
button, a highlighted area with the rest of the screen dimmed, or a step-by-step
walkthrough with *Précédent / Suivant*. It does this through four tools —
`point_at`, `highlight`, `show_steps`, `clear_overlay` — served in-process by an
SDK MCP server and pre-approved, since drawing an arrow cannot change anything.
When Claude points, the wizard walks over and stands beside the spot, staff
aimed at it, then goes home when the annotation clears.

The overlay is one click-through window per monitor. It never takes a click or
a key: WindowTransparentForInput *and* `WS_EX_TRANSPARENT | WS_EX_LAYERED |
WS_EX_NOACTIVATE` set explicitly, because an overlay that eats one click breaks
the app it is explaining. Verified by asking Windows which window is under the
target point — it answers with the window *beneath*. Escape clears everything:
the overlay cannot have focus, so Escape is claimed as a global hotkey **only
while something is on screen**, and released the moment it clears. Annotations
also clear themselves after `ui.overlay_seconds`, and the timer that does it
wakes once per expiry rather than polling.

**Mapping Claude's coordinates back onto the screen** is the part that has to be
exactly right. Claude reasons in pixels of the image it received, which was
cropped, grabbed at the monitor's scale factor and downscaled to 1568 px. Each
capture records the logical rectangle it covered and the final size of the
image sent; device pixels and the downscale then cancel out, and a point is a
proportion of one mapped onto the other. `overlay/mapping.py` does this and
nothing else, with tests at every stock scale factor (100–200 %), on monitors at
negative coordinates, and against the real downscaling function. The tools refuse
to draw against a dropped photo — it has no place on the screen, and a
confidently wrong arrow is worse than none.

### Keeping our windows out of the screenshots

The obvious tool, `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, **does not
work on the avatar or the overlay**. Measured on Windows 10 22H2: it succeeds on
an opaque window and fails with error 8 on any translucent (layered) one — and
both of those are translucent. The avatar had been appearing in captures despite
a setting meant to prevent it.

So every capture now goes through a *cloak*: our windows are hidden, the screen
is given 80 ms to repaint, the grab happens, and they come back — even if the
grab fails. The avatar blinks out for a tenth of a second; in exchange, the
image sent to Claude is guaranteed clean. Checked with a control: a raw grab
shows a test window and the overlay's accent ring, and the same capture through
the cloak shows neither. This also fixed the window picker, which used to grab
immediately after hiding its halo, before the screen had repainted.

`ui.exclude_from_capture` therefore does something narrower, and true: it hides
the **opaque panels** — answers, command palette, approvals, settings — from
screen sharing and recording, which Windows does allow (verified: affinity
`0x11` on all four). You see them; the people watching your Teams or Zoom share
do not. **The wizard himself and the on-screen arrows cannot be hidden from
screen sharing**; they are only ever removed from the captures this app makes.

## Look and feel

One design system, `ui/src/design/tokens.ts`, holds every colour, size,
radius, font and spring (DESIGN.md section 3). A test fails if a colour is
written anywhere else.

- **Dark, always.** The floating surfaces are dark by design (DESIGN.md
  section 3), and the app window follows them. There is no light theme.
- **Animations honour the system setting**: WebView2 reports Windows'
  *Show animations* as `prefers-reduced-motion`, and the avatar and the
  panel then jump to their end states.
- **Notifications are ours**, not tray balloons: three at most, stacked above
  the avatar in the panel's window, dismissed on a click. Approvals stay in
  the panel until answered or timed out, because a toast is something you may
  ignore and an approval is not.
- **He gets out of the way of full-screen apps.** Rather than comparing window
  rectangles — which a maximised window fools and a borderless game defeats —
  the core asks Windows through `SHQueryUserNotificationState` and the windows
  hide while a game, a video or a presentation is running. He comes back
  afterwards, unless you had hidden him yourself first.
- **Size, opacity and click-through** (`[appearance]` in config.toml, or the
  settings) apply to the avatar as soon as they are saved.

### Settings, and why they do not wreck your config

*Paramètres…* (tray menu, or `/` in the panel) is a view over `config.toml`,
which stays the source of truth. It writes **only the keys you changed, one
line at a time**, so two things survive a save that a normal TOML serialiser
would destroy:

- **The French comments** explaining each setting. A round-trip through a
  TOML library drops every one of them; `config_writer.py` replaces just the
  value and keeps the comment in its column.
- **A hand edit made while the view was open.** Writing a full snapshot
  would silently revert it. Writing only what changed does not.

Shortcuts are captured live — click the field, press the combination — and
checked for conflicts before saving, by what they *mean* rather than how they
are spelt: `ctrl+alt+n`, `Control+Alt+N` and `alt+ctrl+n` are one shortcut, and
a text comparison would let you register the second one, which would then
silently never fire. Shift on its own is refused as a modifier, since
`shift+A` would swallow every capital A you type anywhere.

### Answers with code

Answers are Markdown, rendered as text and never as HTML (an answer quoting a
`<script>` shows it, it does not run it). Each code block keeps its own line
breaks, scrolls sideways when long — wrapping would misrepresent indentation,
which in Python is the syntax — and has **its own Copier button**.

### First run

A welcome view, shown once, introduces him, lists the shortcuts worth
learning, and **checks this machine** rather than promising: whether Claude
Code is logged in, whether the hooks are installed (with a button to do it),
and where Windows 10 hides the tray icon.

## The character

Little Wizard is a small African wizard: dark skin, big round eyes, an indigo
robe and a pointed hat, and a carved staff whose orb carries the app's state
light. He is drawn in code on a 2D canvas (`ui/src/avatar/`): `pose.ts` turns
a state and a clock into a pose, `draw.ts` paints it, `renderer.ts` decides
when a frame is worth painting at all. Those parts are pure functions, tested
without a screen; DESIGN.md section 4 describes every state.

## Packaging

```powershell
.venv\Scripts\python.exe -m pip install -e ".[build]"   # PyInstaller
.venv\Scripts\python.exe packaging\build.py
```

That produces `ui\src-tauri\target\release\bundle\nsis\Little Wizard_<version>_x64-setup.exe`
(about 51 MB), an installer for the current user that needs no Python, Node or
Rust on the machine — only Claude Code itself, for the Claude features.

- **The core is frozen with PyInstaller `--onedir`** (`packaging/dist/wizard-core`,
  about 150 MB unpacked), not `--onefile`, which unpacks itself to a temporary
  folder on every start: slower, and what antivirus software flags. It is a
  console exe started with `CREATE_NO_WINDOW`, so its standard streams always
  work and no window ever shows.
- **The hook is frozen on its own** (`wizard-hook.exe`, 21 MB): the installed
  app has no Python to run `wizard_hook.py` with, and starting the core's exe on
  every tool call would load PySide6 for nothing. Installing the hooks from the
  packaged app writes `wizard-hook.exe <event>`; uninstalling the app leaves
  those entries pointing at nothing, which the app reports as stale — remove
  the hooks (*Hooks Claude Code…*) before uninstalling.
- **Tauri ships both folders as resources** (`core/`, `hook/`) rather than as
  `externalBin`, which takes a single file only. The shell starts
  `core/wizard-core.exe` in a release build and the repository's `.venv` in a
  debug one; `WIZARD_CORE` overrides either.
- **The Rust release build is long here**: 28 minutes, one job at a time
  (`CARGO_BUILD_JOBS=1`, which `build.py` sets) because compiling the `tauri`
  crate in parallel runs out of memory on a 4 GB machine.
- `packaging\build.py --python` builds the two exes only, to test them.

Measured: the frozen core is ready 3.9 s after it starts and exits 0.3 s after
its stdin closes. The frozen hook takes 150–170 ms per event with the app
running (as the script under `pythonw.exe` did), and about 0.6 s when the app is
closed, almost all of it the hook's 0.4 s connection timeout.

## Architecture

```
src/wizard/              the core (Python, no window)
  app.py                 wiring only: who talks to whom
  presenter.py           what the app shows, as one interface
  presenter_remote.py    ...as protocol events to the Tauri UI
  protocol.py            the UI protocol, checked both ways
  protocol_messages.json every message, read by Python and TypeScript
  ws_server.py           the local WebSocket: token, origin, size cap
  rpc.py, services.py    the requests the app window may make, by name
  settings_schema.py     the settings' labels and limits, checked again here
  onboarding.py          the first-run state and the machine's checks
  screens.py             desktop coordinates <-> (screen id, position)
  branding.py, paths.py  the name, where files live, migration from Lutin
  config.py              TOML loading with defaults and clamping
  config_writer.py       edits config.toml one line at a time, keeping comments
  storage.py, schema.py  SQLite: notes, clipboard, numbered migrations
  history.py             conversations, messages, thumbnails, FTS5 search
  claude/                the Agent SDK: one persistent session, permissions
  claude_transcripts.py  read-only access to ~/.claude/projects
  capture/               grabbing a region, a window, a file; the cloak
  overlay/               on-screen guidance: mapping, scene, MCP tools
  bridge/                named pipe + settings.json hook installer
  assistant/             selection actions, agents, memory, local OCR
  features/              launcher, clipboard watcher, monitor, timers, reminders
  hotkeys.py             RegisterHotKey, owned by one invisible widget
  hotkey_spec.py         finding two shortcuts that collide
  winapi.py              ctypes: taskbar, CPU/RAM/battery, hotkeys, autostart
  mood.py, sessions.py   the moods, and every Claude Code session seen
hooks/
  wizard_hook.py         the hook handler Claude Code spawns (stdlib only)
ui/                      the Tauri UI
  src-tauri/             the Rust shell: windows, tray, core supervisor
  src/avatar/            the drawn avatar
  src/panel/             the panel and its states
  src/guide/             the guide cursor
  src/app/               the app window and its views
  src/core/              the connection to the core
  src/playground/        the browser playground and its fake core
PLAN.md                  the plan this app is being built out against
DESIGN.md                the design of the UI
```

Decisions worth knowing about:

- **Global hotkeys need a window.** `RegisterHotKey` posts `WM_HOTKEY` to a
  window's message queue; one never-shown Qt widget owns the registrations and
  a native event filter reads them. It is the core's only widget, and why the
  core is a `QApplication` at all.
- **Two permission paths, one panel.** Sessions Little Wizard starts are gated
  by the SDK's `can_use_tool` callback; sessions you start are gated by the
  hook. Both end up in the same approval card, and the hook skips sessions
  Little Wizard started (`WIZARD_OWN_SESSION`) so nothing is asked twice.
- **The bridge is a named pipe.** `QLocalServer` is one on Windows, which is
  the exact equivalent of the Unix socket coucou uses, and it already lives in
  the Qt event loop.

## How the UI talks to the core

The core has no window (phase M7 removed the Qt ones) and talks to the Tauri UI
over a local WebSocket. Run on its own, for a test:

```powershell
$env:WIZARD_UI_TOKEN = "<a long random secret>"
.venv\Scripts\python.exe -m wizard --headless
# WIZARD_READY {"port": 51234, "pid": 9796}
```

It creates no visible window: hotkeys, captures, Claude, the hook bridge and
the database all run as before, and everything they would have shown becomes
an event on the socket. Without `WIZARD_UI_TOKEN`, a token is generated and
printed on that ready line, for a manual run. Exit codes: 3 if the app is
already running, 4 if the socket cannot listen.

- **One protocol, one file.** `src/wizard/protocol_messages.json` lists every
  message; `protocol.py` and `ui/src/protocol.ts` both read it, and the
  TypeScript types do not compile if they drift from it.
- **One seam.** `app.py` never touches a widget: it talks to a *presenter*,
  `ProtocolPresenter`, which turns everything into events on the socket.
- **The promises hold without the UI.** An approval nobody answers is denied
  at its timeout by the core itself. A capture reaches Claude only after a
  `capture.confirm` naming the exact capture the UI was shown. Before a grab,
  every UI window must confirm it is hidden (`cloak.hide` → `cloak.ack`); one
  that does not answer within 600 ms cancels the capture rather than let our
  own windows into it.
- **Coordinates** go out as a screen id (`\\.\DISPLAY1`, the name Qt and Tauri
  both use) plus logical pixels from that screen's corner (`screens.py`).

Measured on the real Windows platform: no visible window, a screen capture
through the cloak handshake in 0.35 s, 0.08 % of one core idle with a UI
connected (60 s), and a clean exit in 0.3 s on the `quit` action.

### The Tauri shell (phase M2)

`ui/src-tauri` is the Tauri 2 application: it starts the core, keeps it
alive, and opens the windows. It needs Rust (`rustup`, MSVC toolchain) and
Node:

```powershell
cd ui
npm install
npm run tauri dev     # Vite dev server + the Rust shell, which starts the core
```

- **The core** is started as `python -m wizard --headless
  --exit-on-stdin-close`, from the repository's `.venv` (or `WIZARD_CORE`). It
  is restarted if it dies, after 1, 2, 4, 8, 16 s, and given up on after five
  crashes within a minute; exit code 3 (already running) is never retried.
- **Stopping it** never kills what it launched for you: Tauri closes the
  core's stdin, which is the signal to quit, and that also happens by itself
  if Tauri crashes. Only a core still there after 10 s is killed, and then only
  the interpreter, so an editor opened from the launcher stays open. A
  kill-on-close job object was ruled out for that reason.
- **The token** is generated by Tauri, given to the core in its environment,
  and to the windows through a Tauri command: it never appears in a URL or in
  a log.
- **Windows**: an avatar of 72 px that never takes the focus; a panel above
  it; one click-through overlay per screen, realigned to the monitors each
  time the guide draws.
- **Screen sharing**: `WDA_EXCLUDEFROMCAPTURE` is **accepted on all three**
  WebView2 windows, overlay included, where Qt was refused it on every
  translucent window. `ui.exclude_from_capture = false` turns it off on every
  window. The order matters: the overlay gets it before being made
  click-through, which makes it layered, and keeps it afterwards.

Measured on this machine: the core ready 2.3–9.6 s after launch; after a
simulated crash of the core, the windows reconnected to its new port; after a
simulated crash of Tauri, the core left on its own in 6–7 s. **Memory: about
550 MB in all**, of which ~240 MB for WebView2 (9 processes), ~145 MB for the
Python processes and ~135 MB for the Claude Code process.

**Idle CPU, with the drawn avatar (phase M4)**, mouse still, production
frontend: WebView2 0.36 %, the Tauri shell 0.02 %, the core 0.02 % of one
core, plus the warm Claude Code process (0.6–1 % that run). Getting there took
measuring inside WebView2: every frame of a transparent always-on-top window is
recomposed in full, however small, so the avatar **settles** after a quiet
minute (no breathing, no blinking; DESIGN.md section 4), its eyes move in 16
directions rather than glide, and the cursor is pushed by a Rust thread only
when it moves. While the mouse is in use the gaze still costs 2–4 % until he
settles.

### The playground (phase M3)

```powershell
cd ui
npm run playground    # opens http://127.0.0.1:5173/playground.html
```

The real window views, fed by a fake core that replays a scenario
(`ui/src/playground/scenarios/*.json`: a streamed answer, an approval running
out, a capture through the cloak, the guide on two screens, a core crash). No
Python, no Tauri: this is where the look is worked on. Only the socket is
fake: each window keeps its real connection code, reconnection and cloak
included, and every scenario is checked against the protocol by the tests.

### The panel (phase M5)

One window above the avatar that changes shape (DESIGN.md section 5): the bar
(chips, `/` to filter the actions with the palette's fuzzy matcher), the
answer (streamed, then rendered), the approval (with a countdown ring around
the avatar), the capture to confirm, the selection result, and the toasts.
Its states are a pure, tested reducer (`ui/src/panel/machine.ts`).

- **Answers are never HTML.** Markdown becomes React elements, so an answer
  quoting a page with a `<script>` in it shows the script, never runs it: the
  panel's window can call Tauri. Links are shown with their address and not
  followed, since following one would navigate the panel itself.
- **Nothing steals the focus.** The panel takes the keyboard only when you
  open it to type; an approval or a capture appears without taking it.
- **An approval cannot be dismissed by a click on the avatar**, since it would
  then time out unseen: Escape answers it (refuse).

### The guide cursor (phase M6)

When Claude points at something, a small cursor leaves the avatar's orb and
flies there (a curved path, 450 to 900 ms), rings twice and says what to do;
a tutorial walks step by step, with Previous / Next in the panel. It lives in
one click-through overlay per screen, drawn only while it has something to
show: at rest the overlays are hidden and receive nothing. Measured with the
panel and the guide in place, mouse still: **0.76 % of one core for the whole
app, the warm Claude Code process included**.

### The app window (phase M6 bis)

Everything the Qt dialogs did now lives in one ordinary, resizable window:
history (including your Claude Code sessions, read-only), clipboard, notes,
reminders, agent launch, Claude Code hooks, settings and the welcome. Open it
from the tray, a hotkey, or `/` in the panel's bar. Closing it only hides it.

The window keeps nothing itself: it asks the core by method name
(`request`/`reply`, the list is in `src/wizard/services.py`), and the core
checks every value again before acting. Installing the hooks writes
`settings.json` only if the diff you approved is still the one the core would
write. The avatar now remembers where you left him (tray: *Replacer sur la
barre* to forget it).

## Known limits

- Windows only. The modules import cleanly elsewhere (the Win32 calls degrade to
  neutral values) so the tests run anywhere, but the app itself does not.
- Reminders live in memory: they do not survive a restart, by design.
- Clipboard history keeps text and images; copied files are ignored.
- The avatar is always-on-top, so it can cover a corner of a window underneath.
  Drag it somewhere else, or hide it with `Ctrl+Alt+A`.
- **The installer is not signed.** Windows SmartScreen warns on first run,
  and some antivirus software distrusts unsigned PyInstaller executables.
- There is no CI. The tests and the linter are run by hand.
- **Idle CPU is under 1 % of one core for the whole app** once the avatar
  has settled (phase M6: 0.76 %, the warm Claude Code process included).
  `claude.prewarm = false` removes that process, at the cost of a slower first
  answer. **While a Claude session works, the avatar animates and WebView2
  then costs about 25 % of one core** (measured in phase M7, a hooked session
  working): every frame of a transparent always-on-top window is recomposed in
  full. Not optimised yet.
- Quitting within the first seconds, while the Claude connection is still
  being made, takes about 4 seconds: starting the Claude Code process cannot be
  cancelled instantly. Nothing is left running afterwards (checked).
- Selection actions start a Claude Code process per request, so expect a few
  seconds before the result.
