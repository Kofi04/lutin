# Little Wizard

A small animated wizard who floats just above the Windows taskbar, with a tray
icon, global hotkeys, clipboard history, quick notes and countdown reminders.
He shows you what your machine and your Claude Code sessions are doing, and he
answers questions about whatever is on your screen.

![the fourteen poses](docs/poses.png)

> **This app used to be called Lutin.** The rename moved its data folder from
> `%APPDATA%\Lutin` to `%APPDATA%\LittleWizard`, so the first start after
> upgrading **copies** your settings, notes, clipboard history and saved avatar
> position across and tells you it did. The old folder is left exactly as it
> was — delete it yourself once you are satisfied. If you had the Claude Code
> hooks installed, they still point at the old script name: the tray menu
> offers *Réinstaller les hooks Claude Code…* to fix that, and says so on
> startup.

## Requirements

- Windows 10 or 11
- Python 3.11+ (tested on 3.14)
- PySide6 — the only runtime dependency (plus `claude-agent-sdk` for the Claude
  features and `pygments` for code highlighting)

Optional extras, each of which the app starts fine without:

| Extra | Brings | Needed for |
|---|---|---|
| `[voice]` | Windows on-device speech bindings (~5 MB, no model download) | talking to Claude, dictation, spoken answers |
| `[live]` | `sounddevice` | transcribing system audio during a meeting |
| `[ocr]` | Windows OCR bindings | copying text out of a screen region locally |

## Install

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts\shortcut.ps1
```

The last line puts a **Little Wizard** icon on the Desktop and in the Start
Menu. Double-click it to launch — that is the whole story from then on. To keep
it one click away, right-click the Start Menu entry → *More* → *Pin to taskbar*.

`scripts\shortcut.ps1 -Remove` deletes both shortcuts again;
`-DesktopOnly` skips the Start Menu entry.

The shortcut points at `.venv\Scripts\wizard.exe`, the GUI launcher that
`pip install -e .` generates from the `[project.gui-scripts]` entry point. It is
a GUI-subsystem binary, so no console window ever appears. If you prefer the
command line, `.venv\Scripts\pythonw.exe -m wizard` does the same thing.

> **The shortcut hard-codes this folder.** Move or rename the project and the
> icon breaks — just re-run `scripts\shortcut.ps1` to point it at the new path.

> **Windows 10 hides new tray icons.** On first run the wizard's tray icon goes
> into the overflow area behind the `^` chevron. Drag it onto the taskbar, or
> use *Taskbar settings → Select which icons appear on the taskbar*, to keep it
> visible.

## What it does

> **The interface is in French; the code is in English.** Identifiers, comments,
> docstrings and this README stay English, as does anything the user never sees
> (the `Mood` values, config keys, hotkey modifier names). Everything displayed —
> menus, dialogs, notifications, the comments inside `config.default.toml` — is
> French. Strings are inline rather than routed through Qt's `tr()`, because the
> app targets one language and a `.ts`/`.qm` pipeline would be pure ceremony.

| Action | Hotkey | Menu entry |
|---|---|---|
| Ask Claude | `Ctrl+Alt+C` | *Demander à Claude…* |
| Show a screen region | `Ctrl+Alt+S` | *Montrer une zone…* |
| Show a window | `Ctrl`+drag the avatar onto it | — |
| Show an image | drop the file on the avatar | — |
| Quick note | `Ctrl+Alt+N` | *Note rapide* |
| Clipboard history | `Ctrl+Alt+V` | *Presse-papiers* (or a single tray click) |
| Launcher menu | `Ctrl+Alt+Space` | *Lancer* |
| Show / hide the avatar | `Ctrl+Alt+A` | *Masquer / Afficher le sorcier* |
| Reminders | — | *Me rappeler…* |

- **Left-click the avatar** opens the full action menu; **drag it** to move it
  anywhere, and it remembers where you left it.
- **Clipboard history** records text copies into SQLite, skipping blanks and
  consecutive duplicates, pruned to `max_entries`. Select an entry and press
  Enter to put it back on the clipboard.
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
  downsamples anyway) and always shown in a confirmation dialog before they can
  be used. Plain drag still moves the avatar; `Ctrl`+drag is what points at a
  window, so neither gesture shadows the other.

- **Claude** answers in the wizard, never in a terminal. The conversation is one
  long-lived connection rather than a fresh CLI per question, so asking twice
  costs one startup, not two. Confirming a capture
  opens the question panel; the answer streams back in place. The conversation
  persists (the SDK's `resume`) until *Nouvelle discussion Claude*.
- **Approvals** appear on the avatar with Autoriser / Toujours / Refuser, for
  both the sessions Little Wizard starts and the ones you run yourself. Not answering
  denies: silence is not consent.
- **Your own Claude Code sessions** show up too, once the hooks are installed:
  what each one is reading, editing and running, one coloured avatar per
  session.

## Claude Code hooks

*Installer les hooks Claude Code…* in the tray menu adds Little Wizard to
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
- `wizard.db` — notes and clipboard history (SQLite)
- `state.ini` — the avatar's last position

`%APPDATA%\Lutin\` may also still exist: it is the pre-rename folder, kept as a
backup, plus a `.migrated-to-LittleWizard` marker. Nothing reads it after the
first start.

**What leaves your machine.** Asking Claude sends your question and, when you
attach one, the capture — to Anthropic, through the Claude Code CLI you are
already signed in to. That is the whole point of the feature, and it is the only
network traffic this app causes: there is no telemetry, no analytics and no
other endpoint. Two guarantees around it:

- **No capture is ever sent without you seeing it first**, in a confirmation
  window that shows exactly the image that will go. There is deliberately no
  setting to skip it.
- **Nothing is captured in the background.** Every capture starts from an action
  you took.

Since clipboard history captures whatever you copy — passwords included — turn
**Enregistrer le presse-papiers** off in the tray menu before copying secrets, or
set `clipboard.enabled = false`. A screenshot carries the same risk over a wider
area: displayed passwords, private messages, client data. Check the preview.

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

## The character

Little Wizard is a small African wizard: dark skin, big round eyes, an indigo
robe and a pointed hat banded with sober bogolan- and kente-inspired geometry,
cowrie shells, and a carved staff whose tip carries the app's state light.

He is drawn **twice over**, and the app picks whichever is available:

| Source | When | Where |
|---|---|---|
| `character/painter.py` | always — no assets needed | QPainter, resolution-independent |
| `character/sheet.py` | as soon as `assets/character/wizard_idle_1.png` exists | PNG frames, which then take over silently |

Nothing else in the app knows which one it got. `character/animation.py` owns
the clock — poses, transitions, blinking, dozing off — and hands both renderers
the same `Frame`. It imports nothing from Qt, which is why the fiddly parts (a
pose that never reverts, blinking that stops re-arming, waking up onto a mood
that changed while he slept) are covered by ordinary unit tests instead of by
looking at the screen.

To generate hand-drawn art, **`docs/ASSETS_BRIEF.md`** has the character sheet,
the exact palette, the framing rules and a ready-to-paste prompt per pose. A
partial set is fine: only `idle` is required and missing poses fall back to it.

To look at every pose at once:

```powershell
.venv\Scripts\python.exe tools\contact_sheet.py            # from code
.venv\Scripts\python.exe tools\contact_sheet.py --assets   # from assets/
```

That writes `docs/poses.png` at 96, 48, 32 and 16px, and prints which renderer
it used — which is the quickest way to find out why your PNGs are not showing
up (almost always a filename that does not match).

**Cost.** The body — gradients, clipped paths, woven bands — is rendered once
into a pixmap and reused; only the eyes, mouth, staff light and props are drawn
each frame, and the halo is a cached pixmap rather than a live radial gradient.
Drawn naively the character cost 5.3% of a core at idle; it now costs **0.7% of
one core** (0.18% of a four-core machine), measured over 40 seconds.

## The icon

`src/wizard/app.ico` is generated, not hand-drawn — it comes from the same
code as the running character:

```powershell
.venv\Scripts\python.exe tools\make_icon.py
```

Re-run it after changing the character, then re-run `scripts\shortcut.ps1` so the
shell picks up the new file. It writes nine sizes (16 to 256) because Windows
picks a different one per context, and below 32px it enlarges the eyes and
thickens the mouth — at 16px the default proportions blur into the body.

## Packaging

```powershell
.venv\Scripts\pyinstaller.exe --noconsole --onefile --name Wizard ^
  --icon src\wizard\app.ico ^
  --add-data "src\wizard\config.default.toml;wizard" ^
  --add-data "src\wizard\app.ico;wizard" ^
  --paths src ^
  src\wizard\__main__.py
```

`--icon` sets the icon baked into the .exe; the second `--add-data` ships the
same file inside the bundle so `app_icon()` still finds it at runtime for the
dialogs. Point `scripts\shortcut.ps1` at `dist\Wizard.exe` afterwards, or
just make a shortcut to it by hand — a packaged build needs no virtualenv.

## Architecture

```
src/wizard/
  branding.py       the app name and every identifier derived from it
  paths.py          where files live, and the migration from the old name
  mood.py           the eight moods, and which one wins
  sessions.py       every Claude Code session seen, internal or external
  claude/           the Agent SDK: one persistent session, permissions
  capture/          region, window and file capture
  bridge/           named pipe + settings.json hook installer
  ui_claude.py      ask panel, approval card
  ui_capture.py     the confirm-before-send preview
  ui_hooks.py       the settings.json diff
  app.ico           the app icon, generated by tools/make_icon.py
  winapi.py         ctypes wrappers: taskbar, CPU/RAM/battery, hotkeys, autostart
  config.py         TOML loading with defaults and clamping
  storage.py        SQLite: notes + clipboard history
  character/        the wizard: poses, animation engine, two renderers
  avatar_window.py  the frameless translucent always-on-top window
  hotkeys.py        RegisterHotKey bridged into Qt via a native event filter
  tray.py           tray icon and menu
  ui.py             quick note, history panel, reminder dialog
  app.py            wiring only: who talks to whom
  features/         launcher, clipboard watcher, monitor, timers
hooks/
  wizard_hook.py    the hook handler Claude Code spawns (stdlib only)
scripts/
  shortcut.ps1      creates/removes the Desktop and Start Menu shortcuts
tools/
  make_icon.py      renders the character into a multi-resolution app.ico
  contact_sheet.py  renders every pose to docs/poses.png, to look at them
assets/character/   hand-drawn frames, if you have any (see docs/ASSETS_BRIEF.md)
PLAN.md             the plan this app is being built out against
```

Decisions worth knowing about:

- **Placement uses Qt, not Win32.** `QScreen.availableGeometry()` already
  reports the area the taskbar left free, in logical pixels and DPI-correct.
  `SHAppBarMessage` is only consulted for the auto-hide flag, which Qt does not
  expose.
- **Global hotkeys need a native event filter.** `RegisterHotKey` posts
  `WM_HOTKEY` to a window's message queue, and Qt owns that queue, so
  `QAbstractNativeEventFilter` is the supported place to intercept it. A
  never-shown widget owns the registrations so hotkeys survive hiding the
  avatar.
- **Two permission paths, one panel.** Sessions Little Wizard starts are gated by the
  SDK's `can_use_tool` callback; sessions you start are gated by the hook. Both
  end up in the same approval card, and the hook skips sessions Little Wizard started
  (`WIZARD_OWN_SESSION`) so nothing is asked twice.
- **The bridge is a named pipe.** `QLocalServer` is one on Windows, which is
  the exact equivalent of the Unix socket coucou uses, and it already lives in
  the Qt event loop.

## Known limits

- Windows only. The modules import cleanly elsewhere (the Win32 calls degrade to
  neutral values) so the tests run anywhere, but the app itself does not.
- Reminders live in memory: they do not survive a restart, by design.
- Clipboard history is text only — images and files are ignored.
- The avatar is always-on-top, so it can cover a corner of a window underneath.
  Drag it somewhere else, or hide it with `Ctrl+Alt+A`.
- **Packaging does not currently work on this machine.** PyInstaller has no
  wheel for Python 3.14, so the command in *Packaging* above cannot run until
  either PyInstaller ships one or you build the app on 3.12/3.13. The command
  itself is correct; it is the tool that is missing.
- There is no CI. The tests and the linter are run by hand.
