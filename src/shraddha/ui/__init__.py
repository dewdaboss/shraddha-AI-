"""Qt user interface for SHRADDHA AI.

Importing this package stays cheap: Qt is imported by the individual modules, and those
are imported only when the UI actually starts. The CLI, the doctor report and the storage
layer never pay for Qt.

Run the interface with::

    python -m shraddha --ui
    python -m shraddha.ui
"""

from __future__ import annotations

__all__: list[str] = []
