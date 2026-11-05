"""Chat transcript: scrolling list of message bubbles.

Two decisions matter here:

* bubbles are capped (:attr:`ChatView.DEFAULT_MAX_BUBBLES`) so a long-running session
  cannot grow the widget tree without bound;
* labels use **plain text**, so Qt never parses markup - cheaper, and it removes a whole
  injection class (Hindi text containing ``<`` is simply text).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from shraddha.ui.theme import BUBBLE_MAX_WIDTH_RATIO, BUBBLE_ROLES, bubble_style

#: Placeholder shown while a streamed answer has not produced its first chunk yet.
STREAM_PLACEHOLDER = "सोच रही हूँ…"


class MessageBubble(QFrame):
    """One chat message. Holds text only; styling comes from the role."""

    def __init__(self, text: str, role: str = "assistant", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if role not in BUBBLE_ROLES:
            raise ValueError(f"unknown message role {role!r}; expected one of {BUBBLE_ROLES}")

        self._role = role
        self.setObjectName(f"bubble_{role}")
        self.setStyleSheet(bubble_style(role))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        self._label = QLabel(text, self)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 9)
        layout.setSpacing(0)
        layout.addWidget(self._label)

    @property
    def text(self) -> str:
        return self._label.text()

    @property
    def role(self) -> str:
        return self._role

    def set_text(self, text: str) -> None:
        """Replace the bubble text (used by streaming)."""
        self._label.setText(text)

    def append_text(self, chunk: str) -> str:
        """Append a chunk and return the whole message."""
        updated = f"{self._label.text()}{chunk}"
        self._label.setText(updated)
        return updated

    def apply_max_width(self, chat_width: int) -> None:
        """Constrain wrapping to a fraction of the transcript width."""
        self._label.setMaximumWidth(max(160, int(chat_width * BUBBLE_MAX_WIDTH_RATIO)))


class ChatView(QWidget):
    """Scrollable transcript. Add messages, read them back, clear them."""

    DEFAULT_MAX_BUBBLES = 200
    SPACING = 9

    def __init__(
        self, max_bubbles: int = DEFAULT_MAX_BUBBLES, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._max_bubbles = max(1, max_bubbles)
        self._bubbles: list[MessageBubble] = []
        self._stream: MessageBubble | None = None
        self._stream_placeholder = False

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("ChatScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._body = QWidget()
        self._body.setObjectName("ChatBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(2, 4, 2, 6)
        self._layout.setSpacing(self.SPACING)
        self._layout.addStretch(1)
        self._scroll.setWidget(self._body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

    # ------------------------------------------------------------------ public
    def add_message(self, text: str, role: str = "assistant") -> MessageBubble:
        """Append one message and keep the newest row visible."""
        bubble = MessageBubble(text, role, self._body)
        bubble.apply_max_width(self._scroll.viewport().width())

        alignment = {
            "user": Qt.AlignmentFlag.AlignRight,
            "assistant": Qt.AlignmentFlag.AlignLeft,
            "system": Qt.AlignmentFlag.AlignHCenter,
        }[role]
        # Insert before the trailing stretch so messages stack from the top.
        self._layout.insertWidget(self._layout.count() - 1, bubble, 0, alignment)
        self._bubbles.append(bubble)
        self._trim()
        self._scroll_to_bottom()
        return bubble

    # ---------------------------------------------------------------- streaming
    @property
    def is_streaming(self) -> bool:
        return self._stream is not None

    @property
    def stream_text(self) -> str:
        return "" if self._stream is None else self._stream.text

    def begin_stream(
        self, role: str = "assistant", placeholder: str = STREAM_PLACEHOLDER
    ) -> MessageBubble:
        """Open a bubble that subsequent chunks are appended to."""
        if self._stream is not None:  # never leave two bubbles streaming
            self.finish_stream()
        bubble = self.add_message(placeholder, role)
        self._stream = bubble
        self._stream_placeholder = bool(placeholder)
        return bubble

    def append_chunk(self, chunk: str) -> str:
        """Append streamed text; returns the message so far."""
        bubble = self._stream
        if bubble is None:
            bubble = self.begin_stream(placeholder="")
        if self._stream_placeholder:
            bubble.set_text(chunk)
            self._stream_placeholder = False
        else:
            bubble.append_text(chunk)
        self._scroll_to_bottom()
        return bubble.text

    def finish_stream(self) -> str:
        """Close the streaming bubble and return its final text."""
        bubble, self._stream = self._stream, None
        self._stream_placeholder = False
        return "" if bubble is None else bubble.text

    def cancel_stream(self, suffix: str = " …") -> str:
        """Close a stream early, marking it as interrupted."""
        bubble, self._stream = self._stream, None
        if bubble is None:
            return ""
        self._stream_placeholder = False
        if suffix and bubble.text:
            bubble.append_text(suffix)
        return bubble.text

    def clear(self) -> None:
        for bubble in self._bubbles:
            self._layout.removeWidget(bubble)
            bubble.setParent(None)
            bubble.deleteLater()
        self._bubbles.clear()
        self._stream = None
        self._stream_placeholder = False

    @property
    def messages(self) -> list[tuple[str, str]]:
        """``(role, text)`` pairs, oldest first - handy for tests and for persisting."""
        return [(bubble.role, bubble.text) for bubble in self._bubbles]

    @property
    def count(self) -> int:
        return len(self._bubbles)

    def last_message(self) -> tuple[str, str] | None:
        return self.messages[-1] if self._bubbles else None

    # ----------------------------------------------------------------- private
    def _trim(self) -> None:
        overflow = len(self._bubbles) - self._max_bubbles
        for _ in range(max(0, overflow)):
            oldest = self._bubbles.pop(0)
            if oldest is self._stream:
                self._stream = None
                self._stream_placeholder = False
            self._layout.removeWidget(oldest)
            oldest.setParent(None)
            oldest.deleteLater()

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        # Defer so the layout has the new size before we jump to the end.
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def resizeEvent(self, event) -> None:
        width = self._scroll.viewport().width()
        for bubble in self._bubbles:
            bubble.apply_max_width(width)
        super().resizeEvent(event)
