"""Fachadas dos amplificadores: tecido da caixa (grille), logo e painel de controles.

Tudo é desenhado com QPainter (sem imagens), inspirado na estética de cada amp clássico,
sem reproduzir marcas ou logotipos.
"""
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen


@dataclass(frozen=True)
class Skin:
    tolex: str            # revestimento da caixa
    grille: str           # tecido frontal
    grille_line: str      # trama do tecido
    pattern: str          # "weave", "basket", "diamond", "plate", "mesh"
    panel_top: str        # painel de controles (gradiente)
    panel_bottom: str
    text: str             # rótulos dos knobs
    dim: str              # valores dos knobs
    knob_cap: str
    knob_ring: str
    accent: str
    pointer: str
    logo_color: str
    logo_font: str
    logo_italic: bool
    logo_upper: bool
    piping: str = ""      # friso entre grille e painel (ex.: branco no JCM800)
    stripe: str = ""      # faixa colorida no painel (ex.: azul no SVT)


SKINS = {
    "blackface": Skin("#151515", "#bdb7a6", "#9d978a", "weave", "#1c1c1c", "#0d0d0d",
                      "#f0f0f0", "#a8a8a8", "#111111", "#4a4a4a", "#e9e9e9", "#ffffff",
                      "#f4f4f4", "Brush Script MT", True, False),
    "plexi": Skin("#1a1a1a", "#d8caa4", "#b9a77c", "basket", "#ecd078", "#b38a2e",
                  "#1b1408", "#4a3b17", "#d9b44a", "#5a4413", "#2a2008", "#1b1408",
                  "#f6f1e3", "Brush Script MT", True, False, piping="#f2ead2"),
    "jcm800": Skin("#141414", "#232323", "#3a3a3a", "mesh", "#e6c766", "#a98426",
                   "#1b1408", "#4a3b17", "#141414", "#5a4413", "#141414", "#e6c766",
                   "#ffffff", "Brush Script MT", True, False, piping="#e8e8e8"),
    "recto": Skin("#0e0e0e", "#262626", "#4a4a4a", "plate", "#e3e6e9", "#8f959b",
                  "#121212", "#3d3d3d", "#121212", "#5f646a", "#c0392b", "#f2f2f2",
                  "#c9cdd2", "Arial Black", False, True),
    "svt": Skin("#121212", "#202020", "#383838", "mesh", "#d9dde0", "#a5abb0",
                "#0e1c33", "#3a4a63", "#151515", "#6c7680", "#1f4e9c", "#ffffff",
                "#e6ebf2", "Arial Black", False, True, stripe="#1f4e9c"),
    "bassdrive": Skin("#0f1012", "#16181b", "#25282d", "mesh", "#2c3036", "#1a1d21",
                      "#e8ecef", "#8b939c", "#0c0d0f", "#3a3f46", "#39d98a", "#39d98a",
                      "#39d98a", "Segoe UI Black", False, True),
    "ac": Skin("#1d1714", "#5d3f26", "#c79a52", "diamond", "#c98a4b", "#8a5426",
               "#fff3dc", "#f0d9b5", "#efe6d2", "#5a3a1c", "#f6e7c9", "#3a2a1a",
               "#e2c27a", "Georgia", False, True),
}


def _draw_grille(qp, r, s):
    qp.fillRect(r, QColor(s.grille))
    qp.save()
    qp.setClipRect(r)
    pen = QPen(QColor(s.grille_line), 1)
    qp.setPen(pen)
    step = 6
    if s.pattern in ("weave", "mesh"):
        y = r.top()
        while y < r.bottom():
            qp.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            y += step if s.pattern == "weave" else 3
        if s.pattern == "weave":
            x = r.left()
            while x < r.right():
                qp.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                x += step
    elif s.pattern == "basket":
        x = r.left()
        while x < r.right() + r.height():
            qp.drawLine(QPointF(x, r.top()), QPointF(x - r.height(), r.bottom()))
            qp.drawLine(QPointF(x - r.height(), r.top()), QPointF(x, r.bottom()))
            x += 5
    elif s.pattern == "diamond":
        pen.setWidthF(1.6)
        qp.setPen(pen)
        w = 22
        x = r.left() - w
        while x < r.right() + w:
            qp.drawLine(QPointF(x, r.top()), QPointF(x + r.height(), r.bottom()))
            qp.drawLine(QPointF(x + r.height(), r.top()), QPointF(x, r.bottom()))
            x += w
    elif s.pattern == "plate":
        y = r.top()
        row = 0
        while y < r.bottom():
            x = r.left() + (6 if row % 2 else 0)
            while x < r.right():
                qp.drawLine(QPointF(x, y + 4), QPointF(x + 6, y))
                x += 12
            y += 6
            row += 1
    qp.restore()


def paint_face(widget, skin_key, logo, grille_rect):
    """Desenha a fachada inteira no fundo do painel do amp."""
    s = SKINS[skin_key]
    qp = QPainter(widget)
    qp.setRenderHint(QPainter.Antialiasing)
    full = QRectF(widget.rect()).adjusted(1, 1, -1, -1)
    path = QPainterPath()
    path.addRoundedRect(full, 10, 10)
    qp.fillPath(path, QColor(s.tolex))
    qp.setPen(QPen(QColor("#000000"), 1.5))
    qp.drawPath(path)

    g = QRectF(grille_rect)
    _draw_grille(qp, g, s)
    qp.setPen(QPen(QColor(0, 0, 0, 120), 2))
    qp.drawRect(g)

    f = QFont(s.logo_font)
    f.setPixelSize(int(g.height() * (0.5 if s.logo_italic else 0.36)))
    f.setItalic(s.logo_italic)
    f.setBold(not s.logo_italic)
    qp.setFont(f)
    text = logo.upper() if s.logo_upper else logo
    plate = QRectF(g.center().x() - g.width() * 0.32, g.center().y() - g.height() * 0.32,
                   g.width() * 0.64, g.height() * 0.64)
    if not s.logo_italic:         # logos em bloco ficam numa plaqueta escura
        qp.setPen(Qt.NoPen)
        qp.setBrush(QColor(0, 0, 0, 150))
        qp.drawRoundedRect(plate, 4, 4)
    qp.setPen(QColor(0, 0, 0, 160))
    qp.drawText(g.translated(2, 2), Qt.AlignCenter, text)
    qp.setPen(QColor(s.logo_color))
    qp.drawText(g, Qt.AlignCenter, text)

    panel = QRectF(full.left() + 6, g.bottom() + 6, full.width() - 12, full.bottom() - g.bottom() - 12)
    if s.piping:
        qp.setPen(QPen(QColor(s.piping), 2))
        qp.drawLine(QPointF(full.left() + 4, g.bottom() + 3), QPointF(full.right() - 4, g.bottom() + 3))
    grad = QLinearGradient(panel.topLeft(), panel.bottomLeft())
    grad.setColorAt(0, QColor(s.panel_top))
    grad.setColorAt(1, QColor(s.panel_bottom))
    qp.setPen(QPen(QColor(0, 0, 0, 140), 1))
    qp.setBrush(QBrush(grad))
    qp.drawRoundedRect(panel, 5, 5)
    if s.stripe:
        qp.fillRect(QRectF(panel.left(), panel.bottom() - 8, panel.width(), 5), QColor(s.stripe))
    qp.end()
