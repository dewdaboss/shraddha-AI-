"""Allow ``python -m shraddha.ui``."""

from __future__ import annotations

import sys

from shraddha.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
