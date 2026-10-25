"""Fachadas dos amplificadores: tecido (grille), marca, painel, knobs e detalhes do painel.

Tudo é desenhado com QPainter (sem imagens). As marcas aparecem só como texto, em fontes
comuns, para identificar o estilo do equipamento — não são os logotipos oficiais.
"""
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

TRADEMARK_NOTICE = ("{brand} é marca registrada de seu respectivo titular. O AmpSim não é afiliado "
                    "nem endossado; o nome só identifica o estilo de timbre.")


@dataclass(frozen=True)
class Skin:
    tolex: str            # revestimento da caixa
    grille: str           # tecido frontal
    grille_line: str      # trama do tecido
    pattern: str          # "weave", "basket", "diamond", "plate", "mesh"
    panel_top: str        # painel de controles (gradiente)
    panel_bottom: str
    text: str             # serigrafia do painel
    dim: str              # valores dos knobs
    knob_cap: str
    knob_ring: str
    accent: str
    pointer: str
    logo_color: str
    logo_font: str
    logo_italic: bool
    logo_upper: bool
    piping: str = ""      # friso entre grille e painel
    stripe: str = ""      # faixa colorida no painel
    knob_style: str = "arc"   # tophat, skirt, chicken, chrome ou arc
    knob_skirt: str = "#111111"
    upper: bool = False   # rótulos em maiúsculas, como serigrafia de amp
    jewel: str = ""       # cor da luz piloto ("" = sem detalhes de painel)
    logo_plate: bool = False


SKINS = {
    # Fender blackface: tecido prata, painel preto, knobs pretos com saia numerada, luz vermelha
    "blackface": Skin("#151515", "#bdb7a6", "#9d978a", "weave", "#1c1c1c", "#0d0d0d",
                      "#f2f2f2", "#a8a8a8", "#151515", "#4a4a4a", "#e9e9e9", "#ffffff",
                      "#f4f4f4", "Brush Script MT", True, False,
                      knob_style="skirt", knob_skirt="#202020", upper=True, jewel="#e0262e"),
    # Marshall Plexi: painel dourado, tecido bege, knobs pretos com tampa dourada
    "plexi": Skin("#1a1a1a", "#d8caa4", "#b9a77c", "basket", "#ecd078", "#b38a2e",
                  "#1b1408", "#4a3b17", "#d9b44a", "#5a4413", "#2a2008", "#f3e9c8",
                  "#ffffff", "Brush Script MT", True, False, piping="#f2ead2",
                  knob_style="tophat", knob_skirt="#141414", upper=True, jewel="#e0262e"),
    # Marshall JCM800: tecido preto com friso branco, painel dourado, knobs top hat
    "jcm800": Skin("#141414", "#232323", "#3a3a3a", "mesh", "#e6c766", "#a98426",
                   "#1b1408", "#4a3b17", "#d4af37", "#5a4413", "#141414", "#f3e9c8",
                   "#ffffff", "Brush Script MT", True, False, piping="#e8e8e8",
                   knob_style="tophat", knob_skirt="#121212", upper=True, jewel="#e0262e"),
    # Mesa Rectifier: chapa xadrez, painel cromado, knobs pretos serrilhados
    "recto": Skin("#0e0e0e", "#262626", "#4a4a4a", "plate", "#e3e6e9", "#8f959b",
                  "#121212", "#3d3d3d", "#2a2a2a", "#5f646a", "#c0392b", "#f2f2f2",
                  "#c9cdd2", "Arial Black", True, False,
                  knob_style="chrome", knob_skirt="#151515", upper=True, jewel="#2ecc71",
                  logo_plate=True),
    # Mesa Mark: painel preto com serigrafia branca
    "mark": Skin("#111111", "#1c1c1c", "#2e2e2e", "weave", "#1b1b1b", "#0c0c0c",
                 "#f0f0f0", "#9a9a9a", "#2a2a2a", "#4a4a4a", "#c0392b", "#f2f2f2",
                 "#e8e8e8", "Arial Black", True, False,
                 knob_style="chrome", knob_skirt="#141414", upper=True, jewel="#2ecc71",
                 logo_plate=True),
    # Ampeg SVT: tecido preto, painel prata com faixa azul
    "svt": Skin("#121212", "#202020", "#383838", "mesh", "#d9dde0", "#a5abb0",
                "#0e1c33", "#3a4a63", "#2a2a2a", "#6c7680", "#1f4e9c", "#ffffff",
                "#e6ebf2", "Georgia", True, False, stripe="#1f4e9c",
                knob_style="skirt", knob_skirt="#1a1a1a", upper=True, jewel="#3b82f6",
                logo_plate=True),
    # pré de baixo moderno (genérico)
    "bassdrive": Skin("#0f1012", "#16181b", "#25282d", "mesh", "#2c3036", "#1a1d21",
                      "#e8ecef", "#8b939c", "#0c0d0f", "#3a3f46", "#39d98a", "#39d98a",
                      "#39d98a", "Segoe UI Black", False, True, jewel="#39d98a", logo_plate=True),
    # Vox AC30: tecido marrom em losangos, painel cobre, knobs "chicken head" creme
    "ac": Skin("#1d1714", "#5d3f26", "#c79a52", "diamond", "#c98a4b", "#8a5426",
               "#fff3dc", "#f0d9b5", "#efe6d2", "#5a3a1c", "#f6e7c9", "#3a2a1a",
               "#e2c27a", "Georgia", False, True,
               knob_style="chicken", upper=True, jewel="#e0262e", logo_plate=True),
    # Orange: caixa laranja, tecido bege, painel branco com serigrafia preta
    "orange": Skin("#e8731c", "#cdbb92", "#a8966e", "basket", "#f4f1ea", "#d6d1c4",
                   "#151515", "#555555", "#1a1a1a", "#777777", "#e8731c", "#f4f1ea",
                   "#e8731c", "Arial Black", False, True,
                   knob_style="skirt", knob_skirt="#141414", upper=True, jewel="#e8731c",
                   logo_plate=True),
    # EVH 5150 / Peavey: preto com detalhes vermelhos
    "evh": Skin("#0d0d0d", "#1a1a1a", "#2c2c2c", "mesh", "#1e1e1e", "#0a0a0a",
                "#f1f1f1", "#9c9c9c", "#1e1e1e", "#4a4a4a", "#d0202a", "#f1f1f1",
                "#e8e8e8", "Impact", False, True,
                knob_style="chrome", knob_skirt="#111111", upper=True, jewel="#d0202a",
                logo_plate=True),
    # Soldano: painel cromado espelhado, knobs pretos
    "soldano": Skin("#0e0e0e", "#1d1d1d", "#333333", "mesh", "#f1f3f5", "#9aa0a6",
                    "#111111", "#444444", "#1c1c1c", "#6a6f75", "#b8860b", "#f5f5f5",
                    "#dcdfe3", "Arial Black", False, True,
                    knob_style="chrome", knob_skirt="#121212", upper=True, jewel="#e0262e",
                    logo_plate=True),
    # fontes de amp que não são modelos internos
    "nam": Skin("#101317", "#192028", "#27313c", "mesh", "#2a323c", "#1a1f26",
                "#e6edf3", "#8b98a5", "#0f1215", "#3a4450", "#4fb3ff", "#4fb3ff",
                "#8fd6ff", "Segoe UI Semibold", False, False, logo_plate=True),
    "vst": Skin("#121016", "#1d1925", "#2d2738", "mesh", "#2d2836", "#1c1923",
                "#ece6f5", "#9a90aa", "#100e14", "#433a52", "#b48cff", "#b48cff",
                "#cdb3ff", "Segoe UI Semibold", False, False, logo_plate=True),
    "di": Skin("#16181c", "#1c1f24", "#262a30", "mesh", "#23262c", "#1a1c20",
               "#d8dae0", "#7d828d", "#2f333c", "#3a3e48", "#e8a33d", "#d8dae0",
               "#9aa0aa", "Segoe UI Semibold", False, False, logo_plate=True),
}

# palavra no nome da captura -> (fachada, marca exibida)
CAPTURE_BRANDS = (
    (("marshall", "jcm", "plexi"), "jcm800", "Marshall"),
    (("rectifier", "recto"), "recto", "Mesa/Boogie"),
    (("mesa", "boogie", "mark"), "mark", "Mesa/Boogie"),
    (("fender", "twin", "deluxe", "bassman", "princeton"), "blackface", "Fender"),
    (("vox", "ac15", "ac30"), "ac", "Vox"),
    (("orange", "rockerverb"), "orange", "Orange"),
    (("5150", "evh", "peavey"), "evh", "EVH"),
    (("soldano", "slo"), "soldano", "Soldano"),
    (("ampeg", "svt"), "svt", "Ampeg"),
    (("tech21", "sansamp", "dug"), "bassdrive", "Tech 21"),
)


def capture_face(name):
    """(fachada, marca, modelo) para uma captura NAM, pelo nome do arquivo."""
    low = name.lower()
    for words, skin, brand in CAPTURE_BRANDS:
        if any(w in low for w in words):
            model = name
            for prefix in (brand, brand.replace(" ", ""), "Mesa Boogie", "Baixo -"):
                if model.lower().startswith(prefix.lower()):
                    model = model[len(prefix):].strip(" -")
            return skin, brand, model or name
    return "nam", name, "captura NAM"


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


def _jack(qp, c, label, s):
    qp.setPen(QPen(QColor(0, 0, 0, 160), 1))
    qp.setBrush(QColor("#c9ced3"))
    qp.drawEllipse(c, 9, 9)
    qp.setBrush(QColor("#0c0c0c"))
    qp.drawEllipse(c, 4.5, 4.5)
    _label(qp, QRectF(c.x() - 30, c.y() + 11, 60, 12), label, s)


def _toggle(qp, c, label, s, up=True):
    qp.setPen(QPen(QColor(0, 0, 0, 160), 1))
    qp.setBrush(QColor("#d9dde1"))
    qp.drawEllipse(c, 6, 6)
    qp.setPen(QPen(QColor("#eceff1"), 3, Qt.SolidLine, Qt.RoundCap))
    qp.drawLine(c, QPointF(c.x(), c.y() + (-13 if up else 13)))
    _label(qp, QRectF(c.x() - 30, c.y() + 15, 60, 12), label, s)


def _label(qp, rect, text, s):
    f = QFont("Segoe UI")
    f.setPixelSize(9)
    f.setBold(True)
    qp.setFont(f)
    qp.setPen(QColor(s.text))
    qp.drawText(rect, Qt.AlignCenter, text)


def paint_face(widget, skin_key, logo, grille_rect, model_label="", notice=""):
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
    f.setPixelSize(int(g.height() * (0.62 if s.logo_italic and "Script" in s.logo_font else 0.42)))
    f.setItalic(s.logo_italic)
    f.setBold("Script" not in s.logo_font)
    if s.logo_upper:
        f.setLetterSpacing(QFont.PercentageSpacing, 112)
    qp.setFont(f)
    text = logo.upper() if s.logo_upper else logo
    if s.logo_plate:
        tw = qp.fontMetrics().horizontalAdvance(text) + 60
        plate = QRectF(g.center().x() - tw / 2, g.top() + 6, tw, g.height() - 12)
        qp.setPen(QPen(QColor(0, 0, 0, 200), 1))
        qp.setBrush(QColor(0, 0, 0, 165))
        qp.drawRoundedRect(plate, 4, 4)
    qp.setPen(QColor(0, 0, 0, 170))
    qp.drawText(g.translated(2, 2), Qt.AlignCenter, text)
    qp.setPen(QColor(s.logo_color))
    qp.drawText(g, Qt.AlignCenter, text)

    bottom_gap = 20 if notice else 6          # faixa do aviso de marca, sobre o revestimento
    panel = QRectF(full.left() + 6, g.bottom() + 6, full.width() - 12,
                   full.bottom() - g.bottom() - 6 - bottom_gap)
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

    if s.jewel:
        # entradas à esquerda; luz piloto e chaves à direita, como no painel real
        cy = panel.top() + panel.height() * 0.42
        _jack(qp, QPointF(panel.left() + 34, cy), "HIGH", s)
        _jack(qp, QPointF(panel.left() + 84, cy), "LOW", s)
        jx = panel.right() - 150
        glow = QColor(s.jewel)
        glow.setAlpha(90)
        qp.setPen(Qt.NoPen)
        qp.setBrush(glow)
        qp.drawEllipse(QPointF(jx, cy), 13, 13)
        qp.setBrush(QColor(s.jewel))
        qp.setPen(QPen(QColor("#d9dde1"), 2))
        qp.drawEllipse(QPointF(jx, cy), 8, 8)
        _label(qp, QRectF(jx - 30, cy + 11, 60, 12), "", s)
        _toggle(qp, QPointF(panel.right() - 95, cy), "STANDBY", s)
        _toggle(qp, QPointF(panel.right() - 45, cy), "POWER", s)

    if model_label:
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 110)
        qp.setFont(f)
        qp.setPen(QColor(s.text))
        qp.drawText(QRectF(panel.left() + 12, panel.top() + 4, panel.width() / 2, 16),
                    Qt.AlignLeft | Qt.AlignVCenter, model_label.upper() if s.upper else model_label)
    if notice:
        f = QFont("Segoe UI")
        f.setPixelSize(10)
        qp.setFont(f)
        qp.setPen(QColor(200, 204, 212, 150))
        qp.drawText(QRectF(panel.left() + 6, panel.bottom() + 3, panel.width() - 12, 14),
                    Qt.AlignRight | Qt.AlignVCenter, notice)
    qp.end()
