"""Widgets desenhados à mão: knob, medidor de nível, botão LED e teclado de piano."""
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

BG = QColor("#16181d")
PANEL = QColor("#22252c")
TEXT = QColor("#d8dae0")
DIM = QColor("#7d828d")


def fmt_value(p, v):
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


class Knob(QWidget):
    """Arraste vertical (Shift = fino), roda do mouse, duplo-clique volta ao padrão."""

    valueChanged = Signal(float)

    def __init__(self, param, accent="#e8a33d", parent=None):
        super().__init__(parent)
        self.p = param
        self.accent = QColor(accent)
        self._value = param.default
        self._drag = None
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(66, 84)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(f"{param.label}\nArraste para cima/baixo (Shift = ajuste fino)\n"
                        "Roda do mouse ajusta · duplo-clique restaura o padrão")

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

    def wheelEvent(self, e):
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
        r = 20.0
        c = QPointF(w / 2, 26)
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        qp.setPen(QPen(QColor("#3a3e48"), 4, Qt.SolidLine, Qt.RoundCap))
        qp.drawArc(rect, 225 * 16, -270 * 16)
        t = self._to_norm(self._value)
        qp.setPen(QPen(self.accent, 4, Qt.SolidLine, Qt.RoundCap))
        if self.p.lo < 0 < self.p.hi and not self.p.log:      # bipolar: arco a partir do centro
            t0 = self._to_norm(0.0)
            qp.drawArc(rect, int((225 - 270 * t0) * 16), int(-270 * (t - t0) * 16))
        else:
            qp.drawArc(rect, 225 * 16, int(-270 * t * 16))
        qp.setPen(Qt.NoPen)
        qp.setBrush(QColor("#2f333c"))
        qp.drawEllipse(c, r - 6, r - 6)
        ang = math.radians(225 - 270 * t)
        qp.setPen(QPen(TEXT, 2.5, Qt.SolidLine, Qt.RoundCap))
        qp.drawLine(c, QPointF(c.x() + (r - 8) * math.cos(ang), c.y() - (r - 8) * math.sin(ang)))
        f = QFont(self.font())
        f.setPointSizeF(8)
        qp.setFont(f)
        qp.setPen(TEXT)
        qp.drawText(QRectF(0, 50, w, 16), Qt.AlignCenter, self.p.label)
        qp.setPen(DIM)
        qp.drawText(QRectF(0, 65, w, 16), Qt.AlignCenter, fmt_value(self.p, self._value))


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
    """Medidor de pico vertical em dB com retenção (decai suavemente)."""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        qp.fillRect(0, 0, w, h, QColor("#0e0f12"))
        fill = int((h - 4) * self.level)
        color = QColor("#4cc26a") if self.level < 0.85 else QColor("#e6c23a")
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
        keys = self._geometry()
        hl = QColor("#7c9cff")
        for n, (r, white) in keys.items():
            if white:
                qp.setPen(QPen(QColor("#555"), 1))
                qp.setBrush(hl if n in self.active else QColor("#ececec"))
                qp.drawRect(r)
                if n % 12 == 0:
                    qp.setPen(QColor("#666"))
                    qp.drawText(r.adjusted(0, 0, 0, -4), Qt.AlignHCenter | Qt.AlignBottom, f"C{n // 12 - 1}")
        if self.marker_low is not None:
            lo, hi = self.marker_low, self.marker_low + 16
            xs = [r.left() for n, (r, w) in keys.items() if w and lo <= n <= hi]
            xe = [r.right() for n, (r, w) in keys.items() if w and lo <= n <= hi]
            if xs:
                qp.fillRect(QRectF(min(xs), self.height() - 5, max(xe) - min(xs), 5), QColor("#e8a33d"))
        for n, (r, white) in keys.items():
            if not white:
                qp.setPen(QPen(QColor("#111"), 1))
                qp.setBrush(hl.darker(130) if n in self.active else QColor("#1b1b1f"))
                qp.drawRect(r)
