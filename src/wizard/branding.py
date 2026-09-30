"""The application's identity, in one place.

Everything that carries the product name goes through here: the config folder,
the registry autostart value, the single-instance key, the shell identity, the
hook pipe and the window titles. Renaming the app is therefore a matter of
editing this file (plus the distribution name in pyproject.toml and the
shortcut script).

Keeping it separate also stops display names and *identifiers* from drifting
apart. The identifiers below must stay ASCII, space-free and stable: changing
SLUG moves the config folder, which orphans the user's existing notes and
settings. That is exactly what happened when the app was renamed from "Lutin",
so the LEGACY_* names below record the old identity and `paths.py` uses them to
carry the user's data across. Do not delete them; a machine that skipped a
version still needs them.
"""

from __future__ import annotations

#: Shown to the user: window titles, notifications, the About text.
APP_NAME = "Little Wizard"

#: The character's name. The same as the app's today, kept separate because the
#: two have already drifted once and may again.
CHARACTER_NAME = "Little Wizard"

#: One line describing the app, used in the shortcut tooltip.
TAGLINE = "Un petit sorcier posé sur votre barre des tâches"

#: ASCII identifier used for paths and registry keys. Changing it relocates
#: %APPDATA%\<SLUG>, so do not change it casually.
SLUG = "LittleWizard"

#: Qt's organisation name, used for QSettings.
ORG_NAME = "LittleWizard"

#: Shell identity, so notifications are attributed to the app and not to
#: "python.exe". Convention is CompanyName.ProductName.
APP_USER_MODEL_ID = "LittleWizard.Companion"

#: Name of the HKCU\...\Run value that implements "start with Windows".
AUTOSTART_VALUE = "LittleWizard"

#: Key for the shared-memory segment that enforces a single running instance.
INSTANCE_KEY = "LittleWizard-single-instance"

#: Basename of the SQLite database inside the config folder.
DATABASE_NAME = "wizard.db"

# -- the previous identity, kept only so we can migrate away from it ---------

#: The old %APPDATA% folder and registry value, from when the app was "Lutin".
LEGACY_SLUG = "Lutin"
LEGACY_AUTOSTART_VALUE = "Lutin"
LEGACY_DATABASE_NAME = "lutin.db"
