"""The application's identity, in one place.

Everything that carries the product name goes through here: the config folder,
the registry autostart value, the single-instance key, the shell identity and
the window titles. Renaming the app is therefore a matter of editing this file
(plus the distribution name in pyproject.toml and the shortcut script).

Keeping it separate also stops display names and *identifiers* from drifting
apart. The identifiers below must stay ASCII and stable: changing SLUG moves
the config folder, which orphans the user's existing notes and settings.
"""

from __future__ import annotations

#: Shown to the user: window titles, notifications, the About text.
APP_NAME = "Lutin"

#: One line describing the app, used in the shortcut tooltip.
TAGLINE = "Un petit compagnon de bureau posé sur votre barre des tâches"

#: ASCII identifier used for paths and registry keys. Changing it relocates
#: %APPDATA%\<SLUG>, so do not change it casually.
SLUG = "Lutin"

#: Qt's organisation name, used for QSettings.
ORG_NAME = "Lutin"

#: Shell identity, so notifications are attributed to the app and not to
#: "python.exe". Convention is CompanyName.ProductName.
APP_USER_MODEL_ID = "Lutin.Companion"

#: Name of the HKCU\...\Run value that implements "start with Windows".
AUTOSTART_VALUE = "Lutin"

#: Key for the shared-memory segment that enforces a single running instance.
INSTANCE_KEY = "Lutin-single-instance"
