"""Icons drawn at runtime with QPainter.

No image files in the repository: a 16x16 PNG cannot be HiDPI-aware, costs a binary
blob in git, and needs a licence. Geometry is cheaper, sharper at every DPI, and
recolours with the theme for free.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from shraddha.ui.theme import PALETTE


def _canvas(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    return pixmap, painter


def _pen(colour: str, width: float) -> QPen:
    pen = QPen(QColor(colour))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def app_pixmap(size: int = 256, listening: bool = False) -> QPixmap:
    """The mark: a neon ring around a solid core, like a listening aperture."""
    pixmap, painter = _canvas(size)
    scale = size / 100.0

    glow = QColor(PALETTE.neon)
    glow.setAlpha(46)
    painter.setPen(QPen(glow, 7.0 * scale))
    painter.drawEllipse(QPointF(size / 2, size / 2), 34 * scale, 34 * scale)

    accent = QColor(PALETTE.neon if listening else PALETTE.neon_dim)
    painter.setPen(_pen(accent.name(), 5.0 * scale))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(size / 2, size / 2), 34 * scale, 34 * scale)

    core = QColor(PALETTE.neon if listening else PALETTE.neon_dim)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(core)
    painter.drawEllipse(QPointF(size / 2, size / 2), 12 * scale, 12 * scale)

    painter.end()
    return pixmap


def app_icon(size: int = 256) -> QIcon:
    """Window and executable icon."""
    icon = QIcon()
    for variant in sorted({16, 24, 32, 48, 64, 128, 256, size}):
        icon.addPixmap(app_pixmap(variant))
    return icon


def mic_pixmap(size: int = 22, colour: str | None = None) -> QPixmap:
    """Classic microphone: capsule, cradle arc, stand."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(colour or PALETTE.text, max(1.6, size * 0.085)))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    capsule = QRectF(size * 0.36, size * 0.14, size * 0.28, size * 0.42)
    painter.drawRoundedRect(capsule, size * 0.14, size * 0.14)

    cradle = QRectF(size * 0.22, size * 0.30, size * 0.56, size * 0.40)
    painter.drawArc(cradle, 180 * 16, 180 * 16)

    painter.drawLine(QPointF(size * 0.5, size * 0.70), QPointF(size * 0.5, size * 0.86))
    painter.drawLine(QPointF(size * 0.34, size * 0.86), QPointF(size * 0.66, size * 0.86))

    painter.end()
    return pixmap


def mic_off_pixmap(size: int = 22, colour: str | None = None) -> QPixmap:
    """Microphone with a slash: muted."""
    pixmap = mic_pixmap(size, colour)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(_pen(colour or PALETTE.danger, max(1.6, size * 0.085)))
    painter.drawLine(QPointF(size * 0.18, size * 0.18), QPointF(size * 0.82, size * 0.82))
    painter.end()
    return pixmap


def send_pixmap(size: int = 20, colour: str | None = None) -> QPixmap:
    """Paper plane, pointing right."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(colour or PALETTE.background, size * 0.10))
    path = QPainterPath()
    path.moveTo(size * 0.16, size * 0.22)
    path.lineTo(size * 0.86, size * 0.50)
    path.lineTo(size * 0.16, size * 0.78)
    path.lineTo(size * 0.30, size * 0.50)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return pixmap


def close_pixmap(size: int = 16, colour: str | None = None) -> QPixmap:
    """Two crossing strokes."""
    pixmap, painter = _canvas(size)
    pen = _pen(colour or PALETTE.text_dim, max(1.4, size * 0.11))
    painter.setPen(pen)
    inset = size * 0.28
    painter.drawLine(QPointF(inset, inset), QPointF(size - inset, size - inset))
    painter.drawLine(QPointF(size - inset, inset), QPointF(inset, size - inset))
    painter.end()
    return pixmap


def stop_pixmap(size: int = 18, colour: str | None = None) -> QPixmap:
    """Rounded square: stop listening."""
    pixmap, painter = _canvas(size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colour or PALETTE.neon))
    painter.drawRoundedRect(
        QRectF(size * 0.30, size * 0.30, size * 0.40, size * 0.40), size * 0.08, size * 0.08
    )
    painter.end()
    return pixmap
