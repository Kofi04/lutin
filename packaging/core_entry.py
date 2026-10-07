"""The frozen core's entry point.

PyInstaller runs a script, not a package: `wizard/__main__.py` uses a relative
import and cannot be that script. This one imports the package by name.
"""

import sys

from wizard.app import main

if __name__ == "__main__":
    sys.exit(main())
