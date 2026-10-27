"""Ícones desenhados em código (sem arquivos de imagem): instrumentos em traço e, para os
genéricos, os glifos da fonte de ícones do Windows (Segoe Fluent Icons / Segoe MDL2 Assets).
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap

GLYPHS = {
    "gear": "", "folder": "", "search": "", "menu": "", "save": "",
    "left": "", "right": "", "down": "", "up": "", "play": "",
    "stop": "", "upload": "", "download": "", "share": "", "copy": "",
    "delete": "", "add": "", "refresh": "", "volume": "", "eq": "",
    "power": "", "info": "", "music": "", "close": "", "check": "",
    "tap": "", "panic": "", "file": "", "globe": "",
}
_FAMILY = None
_cache = {}


def _icon_family():
    global _FAMILY
    if _FAMILY is None:
        fams = set(QFontDatabase.families())
        _FAMILY = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    return _FAMILY


def _pen(color, w):
    p = QPen(QColor(color), w)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _guitar(qp, s, color, bass=False):
    """Violão/guitarra inclinado: corpo de duas curvas, braço e tarraxas."""
    qp.save()
    qp.translate(s * 0.5, s * 0.5)
    qp.rotate(-45)
    qp.translate(-s * 0.5, -s * 0.5)
    qp.setPen(_pen(color, s * 0.075))
    body = QPainterPath()
    cx, cy = s * 0.5, s * 0.72
    body.addEllipse(QPointF(cx, cy), s * 0.2, s * 0.17)
    body.addEllipse(QPointF(cx, cy - s * 0.2), s * 0.14, s * 0.12)
    qp.setBrush(Qt.NoBrush)
    qp.drawPath(body.simplified())
    top = s * (0.02 if bass else 0.08)
    qp.drawLine(QPointF(cx, cy - s * 0.3), QPointF(cx, top + s * 0.1))
    qp.drawRect(QRectF(cx - s * 0.06, top, s * 0.12, s * 0.12))
    qp.restore()


def _keys(qp, s, color):
    qp.setPen(_pen(color, s * 0.07))
    r = QRectF(s * 0.1, s * 0.2, s * 0.8, s * 0.6)
    qp.drawRoundedRect(r, s * 0.06, s * 0.06)
    for i in range(1, 4):
        x = r.left() + r.width() * i / 4
        qp.drawLine(QPointF(x, r.top() + s * 0.32), QPointF(x, r.bottom()))
    qp.setBrush(QColor(color))
    for i in (1, 2, 3):
        x = r.left() + r.width() * i / 4
        qp.drawRect(QRectF(x - s * 0.05, r.top(), s * 0.1, s * 0.3))


def _pads(qp, s, color):
    qp.setPen(_pen(color, s * 0.07))
    for i in range(2):
        for j in range(2):
            qp.drawRoundedRect(QRectF(s * (0.12 + 0.42 * i), s * (0.12 + 0.42 * j), s * 0.32, s * 0.32),
                               s * 0.06, s * 0.06)


def _mixer(qp, s, color):
    qp.setPen(_pen(color, s * 0.07))
    for i, y in enumerate((0.35, 0.65, 0.45)):
        x = s * (0.22 + 0.28 * i)
        qp.drawLine(QPointF(x, s * 0.12), QPointF(x, s * 0.88))
        qp.setBrush(QColor(color))
        qp.drawRoundedRect(QRectF(x - s * 0.09, s * y - s * 0.05, s * 0.18, s * 0.1), s * 0.03, s * 0.03)


def _midi(qp, s, color):
    qp.setPen(_pen(color, s * 0.07))
    c = QPointF(s * 0.5, s * 0.5)
    qp.drawEllipse(c, s * 0.38, s * 0.38)
    qp.setBrush(QColor(color))
    for a in (180, 135, 90, 45, 0):
        r = math.radians(a + 0)
        qp.drawEllipse(QPointF(c.x() + s * 0.22 * math.cos(r), c.y() - s * 0.08 + s * 0.16 * -math.sin(r) * 0.9),
                       s * 0.035, s * 0.035)
    qp.drawRect(QRectF(s * 0.44, s * 0.78, s * 0.12, s * 0.08))


def _logo(qp, s, color):
    """Barras de forma de onda (logo do AmpSim)."""
    qp.setPen(_pen(color, s * 0.075))
    hs = (0.18, 0.42, 0.7, 0.48, 0.86, 0.56, 0.32, 0.62, 0.24)
    n = len(hs)
    for i, h in enumerate(hs):
        x = s * (0.08 + 0.84 * i / (n - 1))
        qp.drawLine(QPointF(x, s * (0.5 - h / 2)), QPointF(x, s * (0.5 + h / 2)))


DRAWN = {"guitar": _guitar, "bass": lambda qp, s, c: _guitar(qp, s, c, bass=True), "keys": _keys,
         "pads": _pads, "mixer": _mixer, "midi": _midi, "logo": _logo}


def pixmap(name, color="#e6edf8", size=20, dpr=2.0):
    key = (name, color, size, dpr)
    pm = _cache.get(key)
    if pm is not None:
        return pm
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    if name in DRAWN:
        DRAWN[name](qp, size, color)
    else:
        f = QFont(_icon_family())
        f.setPixelSize(int(size * 0.8))
        qp.setFont(f)
        qp.setPen(QColor(color))
        qp.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, GLYPHS.get(name, "?"))
    qp.end()
    _cache[key] = pm
    return pm


def icon(name, color="#e6edf8", size=20, active="#ffffff"):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, "#5b6a83", size), QIcon.Disabled, QIcon.Off)
    return ic
