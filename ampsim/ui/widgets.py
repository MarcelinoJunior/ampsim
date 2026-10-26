"""Widgets desenhados à mão: knob, medidor de nível, botão LED e teclado de piano."""
import math
import os
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from .theme import ACCENT, C

BG = QColor(C["bg"])
PANEL = QColor(C["card"])
TEXT = QColor(C["text"])
DIM = QColor(C["dim"])


def find_data(combo, data):
    """Como QComboBox.findData, mas funciona com tuplas (o findData do PySide6 não acha tuplas)."""
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            return i
    return -1


def fmt_value(p, v):
    if p.key == "volume" and p.unit == "dB" and v <= p.lo + 0.05:
        return "mudo"
    if p.is_choice:
        return p.choices[int(round(v))]
    if p.unit == "Hz" and v >= 1000:
        return f"{v / 1000:.1f} kHz"
    if p.unit == "ms" and v >= 1000:
        return f"{v / 1000:.2f} s"
    if p.step >= 1.0:
        s = f"{int(round(v))}"
    elif abs(v) >= 100:
        s = f"{v:.0f}"
    elif abs(v) >= 10:
        s = f"{v:.1f}"
    else:
        s = f"{v:.2f}".rstrip("0").rstrip(".") if p.unit else f"{v:.1f}"
    return f"{s} {p.unit}".strip()


# geometria por tamanho: (largura, altura, raio, centro y, y do rótulo, y do valor)
KNOB_SIZES = {
    "big": (100, 112, 30.0, 36, 76, 94),
    "medium": (80, 96, 24.0, 30, 62, 78),
    "normal": (66, 84, 20.0, 26, 50, 65),
    "small": (58, 68, 15.0, 19, 37, 51),
}


class Knob(QWidget):
    """Arraste vertical (Shift = fino), roda do mouse, duplo-clique volta ao padrão.

    size: "normal", "small" (pedais) ou "mini" (uma linha: knob à esquerda, texto à direita).
    """

    valueChanged = Signal(float)

    def __init__(self, param, accent=ACCENT, parent=None, size="normal"):
        super().__init__(parent)
        self.size_mode = size
        self.p = param
        self.accent = QColor(accent)
        self.cap = QColor("#1a2740")
        self.ring = QColor("#1c2a42")
        self.text = TEXT
        self.dim = DIM
        self.pointer = QColor("#ffffff")
        self.style = "arc"            # "arc" (moderno) ou estilos de amp: tophat, skirt, chicken, chrome
        self.skirt = QColor("#111111")
        self.upper = False
        self._value = param.default
        self._drag = None
        self.setFocusPolicy(Qt.NoFocus)
        if size == "mini":
            self.setFixedSize(112, 30)
        else:
            w, h = KNOB_SIZES[size][:2]
            self.setFixedSize(w, h)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(f"{param.label}\nArraste para cima/baixo (Shift = ajuste fino)\n"
                        "Roda do mouse ajusta · duplo-clique restaura o padrão")

    def set_skin(self, accent, cap, ring, text, dim, pointer, style="arc", skirt="#111111", upper=False):
        self.accent, self.cap, self.ring = QColor(accent), QColor(cap), QColor(ring)
        self.text, self.dim, self.pointer = QColor(text), QColor(dim), QColor(pointer)
        self.style, self.skirt, self.upper = style, QColor(skirt), upper
        self.update()

    # mapeamento valor <-> posição 0..1
    def _to_norm(self, v):
        p = self.p
        if p.log and p.lo > 0:
            return math.log(v / p.lo) / math.log(p.hi / p.lo)
        return (v - p.lo) / (p.hi - p.lo)

    def _from_norm(self, t):
        p = self.p
        t = min(max(t, 0.0), 1.0)
        v = p.lo * (p.hi / p.lo) ** t if (p.log and p.lo > 0) else p.lo + (p.hi - p.lo) * t
        if p.step:
            v = round(v / p.step) * p.step
        return v

    def value(self):
        return self._value

    def setValue(self, v, emit=False):
        v = min(max(float(v), self.p.lo), self.p.hi)
        if v != self._value:
            self._value = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position().y(), self._to_norm(self._value))

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        y0, n0 = self._drag
        sens = 0.0015 if e.modifiers() & Qt.ShiftModifier else 0.006
        self.setValue(self._from_norm(n0 + (y0 - e.position().y()) * sens), emit=True)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.setValue(self.p.default, emit=True)

    def enterEvent(self, e):
        self._hover_since = time.monotonic()
        super().enterEvent(e)

    def wheelEvent(self, e):
        # a roda só mexe no knob se o mouse parou nele: rolar a tela passando por cima
        # de um knob não altera o valor sem querer
        if time.monotonic() - getattr(self, "_hover_since", 0.0) < 0.4:
            e.ignore()
            return
        steps = e.angleDelta().y() / 120.0
        if self.p.step:
            self.setValue(self._value + steps * self.p.step, emit=True)
        else:
            fine = 0.005 if e.modifiers() & Qt.ShiftModifier else 0.025
            self.setValue(self._from_norm(self._to_norm(self._value) + steps * fine), emit=True)

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        if self.size_mode == "mini":
            r, c, ly, vy = 11.0, QPointF(14, 15), None, None
        else:
            _, _, r, cy, ly, vy = KNOB_SIZES[self.size_mode]
            c = QPointF(w / 2, cy)
        if self.style != "arc" and self.size_mode == "normal":
            self._paint_amp_knob(qp, c, r)
            return
        thick = max(3.0, r * 0.17)
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        qp.setPen(QPen(self.ring, thick, Qt.SolidLine, Qt.RoundCap))
        qp.drawArc(rect, 225 * 16, -270 * 16)
        t = self._to_norm(self._value)
        if self.p.lo < 0 < self.p.hi and not self.p.log:      # bipolar: arco a partir do centro
            t0 = self._to_norm(0.0)
            start, span = int((225 - 270 * t0) * 16), int(-270 * (t - t0) * 16)
        else:
            start, span = 225 * 16, int(-270 * t * 16)
        if r >= 22:                                            # brilho em volta do arco
            glow = QColor(self.accent)
            glow.setAlpha(55)
            qp.setPen(QPen(glow, thick * 2.2, Qt.SolidLine, Qt.RoundCap))
            qp.drawArc(rect, start, span)
        qp.setPen(QPen(self.accent, thick, Qt.SolidLine, Qt.RoundCap))
        qp.drawArc(rect, start, span)
        inner = r - thick * 1.25
        cg = QRadialGradient(c.x() - inner * 0.35, c.y() - inner * 0.45, inner * 1.6)
        cg.setColorAt(0, self.cap.lighter(150))
        cg.setColorAt(1, self.cap.darker(160))
        qp.setPen(QPen(QColor(0, 0, 0, 120), 1))
        qp.setBrush(cg)
        qp.drawEllipse(c, inner, inner)
        ang = math.radians(225 - 270 * t)
        qp.setPen(QPen(self.pointer, max(2.0, r * 0.08), Qt.SolidLine, Qt.RoundCap))
        qp.drawLine(QPointF(c.x() + inner * 0.3 * math.cos(ang), c.y() - inner * 0.3 * math.sin(ang)),
                    QPointF(c.x() + inner * 0.82 * math.cos(ang), c.y() - inner * 0.82 * math.sin(ang)))
        f = QFont(self.font())
        big = self.size_mode in ("big", "medium")
        f.setPointSizeF({"big": 11.0, "medium": 9.5, "normal": 8.0}.get(self.size_mode, 7.5))
        f.setBold(big)
        qp.setFont(f)
        if self.size_mode == "mini":
            f.setBold(False)
            qp.setFont(f)
            qp.setPen(self.text)
            qp.drawText(QRectF(30, 0, w - 30, 15), Qt.AlignLeft | Qt.AlignVCenter, self.p.label)
            qp.setPen(self.dim)
            qp.drawText(QRectF(30, 14, w - 30, 15), Qt.AlignLeft | Qt.AlignVCenter,
                        fmt_value(self.p, self._value))
            return
        lh = 18 if big else 15
        qp.setPen(self.text)
        qp.drawText(QRectF(0, ly, w, lh), Qt.AlignCenter, self.p.label)
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - (1.0 if big else 0))
        qp.setFont(f)
        qp.setPen(self.dim)
        qp.drawText(QRectF(0, vy, w, lh), Qt.AlignCenter, fmt_value(self.p, self._value))

    def _paint_amp_knob(self, qp, c, r):
        """Knobs no estilo dos amplificadores reais: escala 0-10 em volta e ponteiro."""
        t = self._to_norm(self._value)
        w = self.width()
        # escala impressa no painel (11 marcas, 0 a 10)
        qp.setPen(QPen(self.text, 1.2))
        for i in range(11):
            a = math.radians(225 - 27 * i)
            r1, r2 = r + 1.5, r + (5 if i % 5 == 0 else 3.5)
            qp.drawLine(QPointF(c.x() + r1 * math.cos(a), c.y() - r1 * math.sin(a)),
                        QPointF(c.x() + r2 * math.cos(a), c.y() - r2 * math.sin(a)))
        ang = math.radians(225 - 270 * t)
        ca, sa = math.cos(ang), -math.sin(ang)
        st = self.style
        if st == "chicken":
            # base redonda + ponteiro alongado (estilo "chicken head" dos Vox)
            qp.setPen(QPen(QColor(0, 0, 0, 140), 1))
            qp.setBrush(self.cap)
            qp.drawEllipse(c, r * 0.55, r * 0.55)
            perp = (-sa, ca)
            tip = QPointF(c.x() + ca * (r - 1), c.y() + sa * (r - 1))
            back = QPointF(c.x() - ca * r * 0.65, c.y() - sa * r * 0.65)
            wdt = r * 0.32
            poly = QPolygonF([QPointF(tip.x() + perp[0] * 2, tip.y() + perp[1] * 2),
                              QPointF(back.x() + perp[0] * wdt, back.y() + perp[1] * wdt),
                              QPointF(back.x() - perp[0] * wdt, back.y() - perp[1] * wdt),
                              QPointF(tip.x() - perp[0] * 2, tip.y() - perp[1] * 2)])
            qp.drawPolygon(poly)
            qp.setPen(QPen(self.pointer, 2, Qt.SolidLine, Qt.RoundCap))
            qp.drawLine(c, tip)
        else:
            # saia (skirt) + tampa; tophat = tampa dourada dos Marshall
            grad = QRadialGradient(c.x() - r * 0.3, c.y() - r * 0.3, r * 1.4)
            grad.setColorAt(0, self.skirt.lighter(170))
            grad.setColorAt(1, self.skirt)
            qp.setPen(QPen(QColor(0, 0, 0, 180), 1))
            qp.setBrush(grad)
            qp.drawEllipse(c, r, r)
            if st == "chrome":       # serrilhado na borda
                qp.setPen(QPen(QColor(255, 255, 255, 40), 1))
                for i in range(24):
                    a = math.radians(i * 15)
                    qp.drawLine(QPointF(c.x() + (r - 3) * math.cos(a), c.y() + (r - 3) * math.sin(a)),
                                QPointF(c.x() + r * math.cos(a), c.y() + r * math.sin(a)))
            cap_r = r * (0.62 if st == "tophat" else 0.72)
            cg = QRadialGradient(c.x() - cap_r * 0.4, c.y() - cap_r * 0.4, cap_r * 1.6)
            cg.setColorAt(0, self.cap.lighter(160))
            cg.setColorAt(1, self.cap.darker(120))
            qp.setBrush(cg)
            qp.drawEllipse(c, cap_r, cap_r)
            qp.setPen(QPen(self.pointer, 2.2, Qt.SolidLine, Qt.RoundCap))
            start = cap_r * (1.0 if st == "tophat" else 0.25)
            qp.drawLine(QPointF(c.x() + ca * start, c.y() + sa * start),
                        QPointF(c.x() + ca * (r - 2), c.y() + sa * (r - 2)))
        f = QFont(self.font())
        f.setPointSizeF(7.5 if self.upper else 8)
        f.setBold(self.upper)
        f.setLetterSpacing(QFont.PercentageSpacing, 108 if self.upper else 100)
        qp.setFont(f)
        _, _, _, _, ly, vy = KNOB_SIZES[self.size_mode]
        qp.setPen(self.text)
        label = self.p.label.upper() if self.upper else self.p.label
        qp.drawText(QRectF(0, ly, w, 15), Qt.AlignCenter, label)
        f.setBold(False)
        qp.setFont(f)
        qp.setPen(self.dim)
        qp.drawText(QRectF(0, vy, w, 15), Qt.AlignCenter, fmt_value(self.p, self._value))


class LedButton(QAbstractButton):
    """Botão liga/desliga com LED, estilo pedal."""

    def __init__(self, accent="#e8a33d", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.accent = QColor(accent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QSize(22, 22)

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(QPen(QColor("#111"), 1.5))
        qp.setBrush(self.accent if self.isChecked() else QColor("#3a3e48"))
        qp.drawEllipse(QRectF(3, 3, 16, 16))


class Meter(QWidget):
    """Medidor de pico em dB com retenção (decai suavemente). Vertical ou horizontal."""

    def __init__(self, parent=None, horizontal=False):
        super().__init__(parent)
        self.horizontal = horizontal
        if horizontal:
            self.setFixedSize(90, 6)
        else:
            self.setFixedWidth(10)
            self.setMinimumHeight(60)
        self.level = 0.0
        self.clip_hold = 0

    def push(self, peak):
        db = 20 * math.log10(peak) if peak > 1e-6 else -120
        t = min(max((db + 60) / 60, 0.0), 1.0)
        self.level = max(t, self.level - 0.03)
        if peak >= 0.99:
            self.clip_hold = 30
        elif self.clip_hold:
            self.clip_hold -= 1
        self.update()

    def paintEvent(self, _):
        qp = QPainter(self)
        h, w = self.height(), self.width()
        qp.fillRect(0, 0, w, h, QColor("#08101b"))
        color = QColor(C["green"]) if self.level < 0.85 else QColor(C["yellow"])
        if self.horizontal:
            fill = int((w - 6) * self.level)
            qp.fillRect(0, 1, fill, h - 2, color)
            if self.clip_hold:
                qp.fillRect(w - 5, 0, 5, h, QColor("#e5484d"))
            return
        fill = int((h - 4) * self.level)
        qp.fillRect(1, h - fill, w - 2, fill, color)
        if self.clip_hold:
            qp.fillRect(0, 0, w, 4, QColor("#e5484d"))


class PianoWidget(QWidget):
    """Teclado clicável. Emite noteOn/noteOff; destaca notas tocadas por qualquer fonte."""

    noteOn = Signal(int, int)
    noteOff = Signal(int)

    WHITE = (0, 2, 4, 5, 7, 9, 11)

    def __init__(self, low=36, high=96, parent=None):
        super().__init__(parent)
        self.low, self.high = low, high
        self.active = set()
        self.marker_low = None          # faixa coberta pelo teclado do PC
        self.split_note = None          # teclado dividido: 1ª nota da mão direita
        self.zone_names = ("", "")      # timbre da mão esquerda e da direita
        self._mouse_note = None
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.NoFocus)

    def set_active(self, note, on):
        (self.active.add if on else self.active.discard)(note)
        self.update()

    def clear(self):
        self.active.clear()
        self.update()

    def _whites(self):
        return [n for n in range(self.low, self.high + 1) if n % 12 in self.WHITE]

    def _geometry(self):
        whites = self._whites()
        ww = self.width() / len(whites)
        keys = {}
        for i, n in enumerate(whites):
            keys[n] = (QRectF(i * ww, 0, ww, self.height()), True)
        bw, bh = ww * 0.62, self.height() * 0.6
        for i, n in enumerate(whites):
            b = n + 1
            if b % 12 in (1, 3, 6, 8, 10) and b <= self.high:
                keys[b] = (QRectF((i + 1) * ww - bw / 2, 0, bw, bh), False)
        return keys

    def _note_at(self, pos):
        keys = self._geometry()
        for n, (r, white) in keys.items():
            if not white and r.contains(pos):
                return n, pos.y() / r.height()
        for n, (r, white) in keys.items():
            if white and r.contains(pos):
                return n, pos.y() / r.height()
        return None, 0.0

    def _vel(self, frac):
        return int(40 + 87 * min(max(frac, 0.0), 1.0))     # mais embaixo na tecla = mais forte

    def mousePressEvent(self, e):
        n, frac = self._note_at(e.position())
        if n is not None:
            self._mouse_note = n
            self.noteOn.emit(n, self._vel(frac))

    def mouseMoveEvent(self, e):
        if self._mouse_note is None:
            return
        n, frac = self._note_at(e.position())
        if n is not None and n != self._mouse_note:
            self.noteOff.emit(self._mouse_note)
            self._mouse_note = n
            self.noteOn.emit(n, self._vel(frac))

    def mouseReleaseEvent(self, e):
        if self._mouse_note is not None:
            self.noteOff.emit(self._mouse_note)
            self._mouse_note = None

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        keys = self._geometry()
        h = self.height()
        f = QFont(self.font())
        f.setPointSizeF(8)
        qp.setFont(f)
        for n, (r, white) in keys.items():
            if not white:
                continue
            k = r.adjusted(1, 0, -1, 0)
            g = QLinearGradient(k.topLeft(), k.bottomLeft())
            if n in self.active:
                g.setColorAt(0, QColor("#8fb7ff"))
                g.setColorAt(1, QColor(ACCENT))
            elif self.split_note is not None and n < self.split_note:
                g.setColorAt(0, QColor("#d9e2f1"))
                g.setColorAt(1, QColor("#b9c8e2"))
            else:
                g.setColorAt(0, QColor("#e9edf3"))
                g.setColorAt(0.85, QColor("#ffffff"))
                g.setColorAt(1, QColor("#d6dbe4"))
            path = QPainterPath()
            path.addRoundedRect(k, 3, 3)
            qp.fillPath(path, g)
            qp.setPen(QPen(QColor("#7d8798"), 0.8))
            qp.drawPath(path)
            if n % 12 == 0:
                qp.setPen(QColor("#56627a"))
                qp.drawText(k.adjusted(0, 0, 0, -5), Qt.AlignHCenter | Qt.AlignBottom, f"C{n // 12 - 1}")
        if self.marker_low is not None:
            lo, hi = self.marker_low, self.marker_low + 16
            xs = [r.left() for n, (r, w) in keys.items() if w and lo <= n <= hi]
            xe = [r.right() for n, (r, w) in keys.items() if w and lo <= n <= hi]
            if xs:
                qp.fillRect(QRectF(min(xs) + 1, h - 4, max(xe) - min(xs) - 2, 4), QColor(C["yellow"]))
        for n, (r, white) in keys.items():
            if white:
                continue
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            if n in self.active:
                g.setColorAt(0, QColor("#5b8cff"))
                g.setColorAt(1, QColor("#1f4fb8"))
            else:
                g.setColorAt(0, QColor("#2a2f3a"))
                g.setColorAt(0.8, QColor("#090b10"))
                g.setColorAt(1, QColor("#2d3340"))
            path = QPainterPath()
            path.addRoundedRect(r, 2.5, 2.5)
            qp.fillPath(path, g)
            qp.setPen(QPen(QColor("#000000"), 1))
            qp.drawPath(path)
        if self.split_note is not None:
            xs = [r.left() for n, (r, w) in keys.items() if w and n >= self.split_note]
            if xs:
                x = min(xs)
                qp.setPen(QPen(QColor(C["yellow"]), 3))
                qp.drawLine(QPointF(x, 0), QPointF(x, h))
                f.setBold(True)
                qp.setFont(f)
                for text, rect, col in (("◀ " + self.zone_names[0], QRectF(x - 220, h * 0.68, 210, 18), "#c98a1d"),
                                        (self.zone_names[1] + " ▶", QRectF(x + 10, h * 0.68, 210, 18), ACCENT)):
                    if len(text) < 4:
                        continue
                    w = min(rect.width(), qp.fontMetrics().horizontalAdvance(text) + 16)
                    pill = QRectF(rect.right() - w if text.startswith("◀") else rect.left(), rect.top(), w, 18)
                    pp = QPainterPath()
                    pp.addRoundedRect(pill, 9, 9)
                    qp.fillPath(pp, QColor(col))
                    qp.setPen(QColor("#ffffff"))
                    qp.drawText(pill, Qt.AlignCenter, qp.fontMetrics().elidedText(text, Qt.ElideRight, int(w - 8)))


class ToggleSwitch(QAbstractButton):
    """Chave liga/desliga (estilo celular)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(40, 22)

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        qp.setPen(Qt.NoPen)
        qp.setBrush(QColor(ACCENT) if on else QColor(C["border2"]))
        qp.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - d - 3 if on else r.left() + 3
        qp.setBrush(QColor("#ffffff"))
        qp.drawEllipse(QRectF(x, r.top() + 3, d, d))


# paletas das miniaturas (por categoria de timbre)
ART = {
    "Pianos": ("#1b3d8f", "#4f8cff", "#0b1f4d"), "Pads e cordas": ("#1a2f6e", "#7aa5ff", "#0a1435"),
    "Órgãos": ("#3a1f6e", "#a07bff", "#170b35"), "Baixos": ("#0f4250", "#3fd0c9", "#062028"),
    "Guitarras e violões": ("#5a2a10", "#ffae5c", "#2a1206"), "Synth AmpSim": ("#3b1450", "#ff6bd5", "#1a0624"),
    "guitar": ("#5a2a10", "#ffae5c", "#2a1206"), "bass": ("#0f4250", "#3fd0c9", "#062028"),
}


# fotos dos timbres (assets/timbres, licenças em CREDITS.md)
PHOTO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "assets", "timbres")
# uma imagem por timbre (fotos do Wikimedia Commons; as "synth-*" são geradas por tools/gerar_artes_synth.py)
PHOTO_BY_NAME = {
    "Piano de Cauda": "piano-cauda", "Piano Brilhante": "piano-brilhante", "Piano Elétrico (CP)": "piano-cp",
    "Piano Honky-tonk": "honky-tonk", "Piano de Armário (Upright)": "piano-upright",
    "Piano de Cauda YDP": "piano-ydp", "Piano de Cauda Salamander": "piano-salamander", "Rhodes": "rhodes", "Rhodes com Chorus": "rhodes-chorus",
    "Piano FM (DX)": "piano-fm", "Piano FM com Chorus": "piano-fm-chorus", "Clavinet": "clavinet",
    "Órgão Hammond": "orgao-hammond", "Órgão Percussivo": "orgao-percussivo", "Órgão Rock": "orgao-rock",
    "Órgão de Tubos": "orgao-tubos", "Órgão de Tubos 2": "orgao-tubos-2",
    "Pad Quente": "pad-quente", "Pad Halo": "pad-halo", "Pad Polysynth": "pad-polysynth",
    "Pad Atmosfera": "pad-atmosfera", "Pad Vozes": "pad-vozes", "Pad Cristal": "pad-cristal",
    "Pad Sweep": "pad-sweep", "Pad Vidro": "pad-vidro", "Pad Chuva de Gelo": "pad-chuva-gelo", "Coral": "coral",
    "Cordas Lentas": "cordas-lentas", "Cordas": "cordas", "Cordas Synth": "cordas-synth",
    "Pad Orquestra": "pad-orquestra", "Pad Órgão": "pad-orgao",
    "Baixo Finger": "baixo-finger", "Baixo Palheta": "baixo-palheta", "Baixo Fretless": "baixo-fretless",
    "Baixo Acústico": "baixo-acustico", "Baixo Synth": "baixo-synth", "Baixo Synth 101": "baixo-101",
    "Baixo FM": "baixo-fm",
    "Violão Nylon": "violao-nylon", "Violão Aço": "violao-aco", "Violão 12 Cordas": "violao-12",
    "Guitarra Limpa": "guitarra-limpa", "Guitarra com Chorus": "guitarra-chorus", "Guitarra Jazz": "guitarra-jazz",
    "Guitarra Overdrive": "guitarra-overdrive", "Guitarra Distorcida": "guitarra-distorcida",
    "Celesta": "celesta", "Sinos": "sinos-tubulares", "Caixinha de Música": "caixinha", "Vibrafone": "vibrafone",
    "Marimba": "marimba", "Kalimba": "kalimba", "Synth Lead": "synth-lead",
    "Baixo Pulsante (AmpSim)": "synth-baixo-pulsante", "Pad Quente (AmpSim)": "synth-pad-quente",
    "Pad Escuro (AmpSim)": "synth-pad-escuro", "Cordas (AmpSim)": "synth-cordas",
    "Saw Brilhante (AmpSim)": "synth-saw-brilhante", "Órgão (AmpSim)": "synth-orgao",
    "Sino Suave (AmpSim)": "synth-sino-suave",
}
# timbre sem foto própria (ex.: um novo): a da categoria
PHOTO_BY_CAT = {"Pianos": "piano-cauda", "Pianos elétricos": "rhodes", "Órgãos": "orgao-hammond",
                "Pads e cordas": "pad-atmosfera", "Baixos": "baixo-finger", "Violões e guitarras": "guitarra-chorus",
                "Sinos e outros": "vibrafone", "Synth AmpSim": "synth-saw-brilhante", "guitar": "guitarra-chorus",
                "bass": "baixo-finger"}
_photos = {}


def photo_for(cat, name=""):
    """Nome da foto (sem extensão) do timbre; sem foto própria, a da categoria."""
    return PHOTO_BY_NAME.get(name) or PHOTO_BY_CAT.get(cat, "pad-atmosfera")


def _photo(name):
    if name not in _photos:
        pm = QPixmap(os.path.join(PHOTO_DIR, name + ".jpg"))
        _photos[name] = None if pm.isNull() else pm
    return _photos[name]


class ArtTile(QWidget):
    """Miniatura do timbre: foto do instrumento (ou, sem a foto, céu + montanhas nas cores da categoria)."""

    def __init__(self, size=96, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.palette_key = "Pads e cordas"
        self.photo = "pad"

    def set_kind(self, key, name=""):
        photo = photo_for(key, name)
        if key != self.palette_key or photo != self.photo:
            self.palette_key = key
            self.photo = photo
            self.update()

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 10, 10)
        qp.setClipPath(clip)
        pm = _photo(self.photo)
        if pm is not None:
            qp.drawPixmap(r, pm, QRectF(pm.rect()))
            return
        top, light, deep = (QColor(c) for c in ART.get(self.palette_key, ART["Pads e cordas"]))
        sky = QLinearGradient(r.topLeft(), r.bottomLeft())
        sky.setColorAt(0, top)
        sky.setColorAt(0.55, light)
        sky.setColorAt(1, deep)
        qp.fillRect(r, sky)
        w, h = r.width(), r.height()
        for k, (alpha, base, amp) in enumerate(((90, 0.62, 0.22), (170, 0.74, 0.16), (255, 0.86, 0.1))):
            path = QPainterPath(QPointF(0, h))
            for i in range(9):
                x = w * i / 8
                y = h * (base - amp * abs(math.sin(i * 1.3 + k * 2.1)))
                path.lineTo(x, y)
            path.lineTo(w, h)
            col = QColor(deep)
            col.setAlpha(alpha)
            qp.fillPath(path, col)
