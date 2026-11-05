"""Small custom widgets: status dot, microphone button, icon button.

Custom painting is used instead of stylesheets where animation is involved: a
stylesheet change triggers a full re-polish of the widget tree, while ``update()`` on a
40x40 widget repaints 1600 pixels. On a low-power laptop that difference is visible.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QPushButton, QSizePolicy, QWidget

from shraddha.ui.icons import close_pixmap, mic_pixmap, send_pixmap, stop_pixmap
from shraddha.ui.theme import ANIM_PULSE_MS, PALETTE


class StatusDot(QWidget):
    """Tiny state indicator: idle, listening or unavailable."""

    STATES = ("idle", "listening", "unavailable")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(12, 12))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._state = "idle"

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        if state not in self.STATES:
            raise ValueError(f"unknown dot state {state!r}")
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        centre = QPointF(self.width() / 2, self.height() / 2)
        colour = {
            "idle": PALETTE.neon_dim,
            "listening": PALETTE.neon,
            "unavailable": PALETTE.text_faint,
        }[self._state]

        halo = QColor(colour)
        halo.setAlpha(60)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(centre, 5.5, 5.5)

        painter.setBrush(QColor(colour))
        painter.drawEllipse(centre, 3.0, 3.0)
        painter.end()


class MicButton(QAbstractButton):
    """Checkable microphone button with a cheap pulse ring while listening.

    The animation only runs while checked, so an idle assistant burns no CPU on it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(42, 42))
        self.setToolTip("हिन्दी आवाज़ से बोलिए (Phase 2)")
        self._pulse = 0.0
        self._hovered = False
        self._icon = mic_pixmap(22, PALETTE.text_dim)

        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(ANIM_PULSE_MS)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._on_pulse)
        self.toggled.connect(self._on_toggled)

    # ---- state ---------------------------------------------------------
    def _on_toggled(self, checked: bool) -> None:
        self._icon = stop_pixmap(18, PALETTE.neon) if checked else mic_pixmap(22, PALETTE.text_dim)
        if checked:
            self._animation.start()
        else:
            self._animation.stop()
            self._pulse = 0.0
        self.update()

    def _on_pulse(self, value: object) -> None:
        try:
            self._pulse = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self._pulse = 0.0
        self.update()

    @property
    def is_animating(self) -> bool:
        return self._animation.state() == QVariantAnimation.State.Running

    # ---- events --------------------------------------------------------
    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        checked = self.isChecked()

        if checked:
            ring = QColor(PALETTE.neon)
            ring.setAlpha(int(70 * (1.0 - self._pulse)))
            painter.setPen(Qt.PenStyle.NoPen)
            grow = 1.5 + 4.0 * self._pulse
            painter.setBrush(ring)
            painter.drawEllipse(rect.adjusted(-grow, -grow, grow, grow))

        background = QColor(
            PALETTE.neon_faint if (checked or self._hovered) else PALETTE.surface_raised
        )
        border = QColor(PALETTE.neon if checked else PALETTE.border)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 12, 12)

        icon = self._icon
        painter.drawPixmap(
            int((self.width() - icon.width()) / 2),
            int((self.height() - icon.height()) / 2),
            icon,
        )
        painter.end()

    def sizeHint(self) -> QSize:
        return QSize(42, 42)


class IconButton(QPushButton):
    """Flat, transparent button holding a painted icon."""

    def __init__(
        self,
        kind: str = "close",
        tooltip: str = "",
        size: int = 30,
        parent: QWidget | None = None,
        object_name: str = "IconButton",
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(size, size))
        self.setFlat(True)
        self._kind = kind
        self._refresh()
        if tooltip:
            self.setToolTip(tooltip)

    def _refresh(self) -> None:
        painter_map = {
            "close": close_pixmap(16, PALETTE.text_dim),
            "send": send_pixmap(20, PALETTE.background),
        }
        pixmap = painter_map.get(self._kind)
        if pixmap is not None:
            from PySide6.QtGui import QIcon

            self.setIcon(QIcon(pixmap))
            self.setIconSize(pixmap.size())
