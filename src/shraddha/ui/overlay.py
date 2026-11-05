"""The floating assistant window.

Frameless, translucent, always-on-top card: status line, chat transcript, microphone
button and text input. Everything is drawn with QPainter/QSS - no images, no web view,
no QML engine - which is what keeps the idle footprint measurable in tens of megabytes
rather than hundreds.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from shraddha.ui.chat import ChatView
from shraddha.ui.theme import (
    ANIM_HIDE_MS,
    ANIM_SHOW_MS,
    ANIM_SLIDE_PX,
    OVERLAY_HEIGHT,
    OVERLAY_MIN_HEIGHT,
    OVERLAY_MIN_WIDTH,
    OVERLAY_WIDTH,
    PALETTE,
    RADIUS_CARD,
    SCREEN_MARGIN,
    stylesheet,
)
from shraddha.ui.widgets import IconButton, MicButton, StatusDot

_NO_OPACITY_PLATFORMS = frozenset({"minimal", "offscreen"})


def _supports_window_opacity() -> bool:
    """Whether the active Qt platform plugin can animate window opacity."""
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.platformName() not in _NO_OPACITY_PLATFORMS


TITLE = "SHRADDHA"
SUBTITLE = "हिन्दी सहायक · पूर्णतः ऑफ़लाइन"
PLACEHOLDER = "हिन्दी में लिखिए…  (Enter = भेजें)"
DRAG_ZONE_HEIGHT = 62


class AssistantOverlay(QWidget):
    """The assistant card the user talks to."""

    submitted = Signal(str)
    mic_toggled = Signal(bool)
    closed = Signal()

    def __init__(
        self,
        hotkey_label: str = "Ctrl+Alt+S",
        always_on_top: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Overlay")
        self.setWindowTitle("SHRADDHA AI")
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(OVERLAY_MIN_WIDTH, OVERLAY_MIN_HEIGHT)
        self.resize(OVERLAY_WIDTH, OVERLAY_HEIGHT)
        self.setStyleSheet(stylesheet())

        self._drag_origin: QPoint | None = None
        self._user_moved = False
        self._hiding = False

        self._build_ui(hotkey_label)
        self._build_animations()
        self.place_default()

    # ------------------------------------------------------------------- build
    def _build_ui(self, hotkey_label: str) -> None:
        self._dot = StatusDot(self)
        self._title = QLabel(TITLE, self)
        self._title.setObjectName("Title")
        self._subtitle = QLabel(SUBTITLE, self)
        self._subtitle.setObjectName("Subtitle")

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(1)
        title_column.addWidget(self._title)
        title_column.addWidget(self._subtitle)

        self._hint = QLabel(hotkey_label.upper(), self)
        self._hint.setObjectName("Hint")
        self._hint.setToolTip(f"कहीं से भी {hotkey_label} दबाइए")

        self._close = IconButton("close", "बंद कीजिए (Esc)", 30, self)
        self._close.clicked.connect(self._on_close_clicked)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addLayout(title_column)
        header.addStretch(1)
        header.addWidget(self._hint, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._close, 0, Qt.AlignmentFlag.AlignVCenter)

        self._chat = ChatView(parent=self)

        self._mic = MicButton(self)
        self._mic.toggled.connect(self.mic_toggled.emit)

        self._input = QLineEdit(self)
        self._input.setObjectName("Input")
        self._input.setPlaceholderText(PLACEHOLDER)
        self._input.setClearButtonEnabled(False)
        self._input.returnPressed.connect(self._on_submit)
        self._input.textChanged.connect(self._on_text_changed)

        self._send = IconButton("send", "भेजिए (Enter)", 40, self, object_name="SendButton")
        self._send.setEnabled(False)
        self._send.clicked.connect(self._on_submit)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(9)
        input_row.addWidget(self._mic, 0, Qt.AlignmentFlag.AlignVCenter)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send, 0, Qt.AlignmentFlag.AlignVCenter)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 15, 18, 16)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(self._chat, 1)
        root.addLayout(input_row)

    def _build_animations(self) -> None:
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._group = QParallelAnimationGroup(self)
        self._group.addAnimation(self._fade)
        self._group.addAnimation(self._slide)
        self._group.finished.connect(self._on_animation_finished)

    # ------------------------------------------------------------------ public
    @property
    def chat(self) -> ChatView:
        return self._chat

    @property
    def text_input(self) -> QLineEdit:
        return self._input

    @property
    def mic_button(self) -> MicButton:
        return self._mic

    @property
    def status_dot(self) -> StatusDot:
        return self._dot

    def append_message(self, text: str, role: str = "assistant"):
        return self._chat.add_message(text, role)

    def clear_chat(self) -> None:
        self._chat.clear()

    def set_status(self, text: str) -> None:
        self._subtitle.setText(text)

    def set_hint(self, text: str) -> None:
        self._hint.setText(text.upper())

    def set_listening(self, listening: bool) -> None:
        """Reflect recognition state without emitting ``mic_toggled`` again."""
        self._mic.blockSignals(True)
        self._mic.setChecked(listening)
        self._mic.blockSignals(False)
        self._dot.set_state("listening" if listening else "idle")
        self.set_status("सुन रही हूँ…" if listening else SUBTITLE)

    def submit_text(self, text: str) -> None:
        """Programmatic equivalent of typing and pressing Enter (used by tests)."""
        self._input.setText(text)
        self._on_submit()

    def place_default(self) -> None:
        """Bottom-centre of the active screen, unless the user moved the window."""
        if self._user_moved:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:  # headless test platform without a screen
            return
        area = screen.availableGeometry()
        x = area.center().x() - self.width() // 2
        y = area.bottom() - self.height() - SCREEN_MARGIN
        self.move(max(area.left() + 8, x), max(area.top() + 8, y))

    def show_overlay(self) -> None:
        if self.isVisible():
            self.raise_()
            self.activateWindow()
            self.focus_input()
            return
        self._hiding = False
        self.place_default()
        target = self.pos()
        self.move(target + QPoint(0, ANIM_SLIDE_PX))
        self.setWindowOpacity(0.0)
        self.show()
        self._animate(self.pos(), target, 0.0, 1.0, ANIM_SHOW_MS)
        self.raise_()
        self.activateWindow()
        self.focus_input()

    def hide_overlay(self) -> None:
        if not self.isVisible() or self._hiding:
            return
        self._hiding = True
        target = self.pos() + QPoint(0, ANIM_SLIDE_PX)
        self._animate(self.pos(), target, self.windowOpacity(), 0.0, ANIM_HIDE_MS)

    def toggle(self) -> None:
        if self.isVisible() and not self._hiding:
            self.hide_overlay()
        else:
            self.show_overlay()

    def focus_input(self) -> None:
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    # ---------------------------------------------------------------- internals
    def _animate(
        self, start_pos: QPoint, end_pos: QPoint, start_opacity: float, end_opacity: float, ms: int
    ) -> None:
        self._group.stop()
        self._slide.setDuration(ms)
        self._slide.setStartValue(start_pos)
        self._slide.setEndValue(end_pos)
        self._fade.setDuration(ms)
        self._fade.setStartValue(start_opacity)
        self._fade.setEndValue(end_opacity)

        if _supports_window_opacity():
            self._group.start()
        else:
            # Headless diagnostic platforms (offscreen/minimal) cannot fade windows;
            # jump straight to the end state instead of emitting a warning per frame.
            self.setWindowOpacity(end_opacity)
            self.move(end_pos)
            if end_opacity <= 0.0:
                self._on_animation_finished()

    def _on_animation_finished(self) -> None:
        if not self._hiding:
            return
        self._hiding = False
        self.hide()
        self.setWindowOpacity(1.0)
        self.closed.emit()

    def _on_close_clicked(self) -> None:
        self.hide_overlay()

    def _on_text_changed(self, text: str) -> None:
        self._send.setEnabled(bool(text.strip()))

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.submitted.emit(text)

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS_CARD, RADIUS_CARD)

        fill = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
        fill.setColorAt(0.0, QColor("#0B120E"))
        fill.setColorAt(1.0, QColor(PALETTE.background))
        painter.fillPath(path, fill)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 255, 156, 58), 1.0))
        painter.drawPath(path)

        # A single faint accent across the top edge: enough to read as "premium",
        # cheap enough to be one extra drawPath.
        accent = QLinearGradient(QPointF(0, 0), QPointF(self.width(), 0))
        accent.setColorAt(0.0, QColor(0, 255, 156, 0))
        accent.setColorAt(0.5, QColor(0, 255, 156, 110))
        accent.setColorAt(1.0, QColor(0, 255, 156, 0))
        painter.setPen(QPen(accent, 1.2))
        top = rect.adjusted(RADIUS_CARD, 1.0, -RADIUS_CARD, 0)
        painter.drawLine(QPointF(top.left(), top.top()), QPointF(top.right(), top.top()))
        painter.end()

    # ------------------------------------------------------------------- events
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_overlay()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= DRAG_ZONE_HEIGHT:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            self._user_moved = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        # Closing the card must not quit the assistant: it lives in the tray.
        self.hide()
        event.ignore()
        self.closed.emit()
