"""Allow ``python -m shraddha``."""

from __future__ import annotations

import sys

from shraddha.cli import main

if __name__ == "__main__":
    sys.exit(main())
