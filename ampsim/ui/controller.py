"""Controlador MIDI desenhado na tela (layout do M-VAVE SMK-25: 25 teclas, 8 pads, 8 knobs).

Mostra o que acontece no controlador real (pads acendem, teclas e knobs se mexem) e também
pode ser tocado com o mouse. No modo "mapear", o elemento esperado pisca em amarelo.
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..instruments import BUTTONS, DRUM_NAMES, KNOB_COUNT, PAD_COUNT, note_name

VW, VH = 1000.0, 430.0                   # coordenadas virtuais do desenho
WHITE_STEPS = (0, 2, 4, 5, 7, 9, 11)


def _knob_center(i):
    return QPointF(190 + (i % 4) * 78, 150 + (i // 4) * 88)


def _pad_rect(i):
    return QRectF(590 + (i % 4) * 100, 34 + (i // 4) * 112, 88, 100)


class ControllerWidget(QWidget):
    padPressed = Signal(int, int)
    keyOn = Signal(int, int)
    keyOff = Signal(int)
    knobMoved = Signal(int, int)
    buttonPressed = Signal(int)
    octaveChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.base_note = 48                 # primeira tecla (C3) do teclado desenhado
        self.display = ("", "")
        self.pad_labels = [""] * PAD_COUNT
        self.knob_labels = [""] * KNOB_COUNT
        self.button_labels = [""] * len(BUTTONS)
        self.knob_values = [64] * KNOB_COUNT
        self.pad_glow = [0.0] * PAD_COUNT
        self.active = set()
        self.learn_target = None            # ("pads"|"knobs"|"buttons", índice)
        self._mouse = None
        self._drag = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(33)

    # ------------------------------------------------------------------ geometria
    def _transform(self):
        s = min(self.width() / VW, self.height() / VH)
        ox = (self.width() - VW * s) / 2
        oy = (self.height() - VH * s) / 2
        return s, ox, oy

    def _to_virtual(self, pos):
        s, ox, oy = self._transform()
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def _buttons(self):
        # 8 botões em 2 fileiras, entre o visor e os pads
        return [QRectF(410 + (i % 4) * 44, 34 + (i // 4) * 40, 40, 32) for i in range(len(BUTTONS))]

    def _keys(self):
        """[(nota, retângulo, branca)] das 25 teclas."""
        x0, y0, w, h = 20.0, 292.0, 960.0, 128.0
        whites = []
        n = self.base_note
        while len(whites) < 15:
            if n % 12 in WHITE_STEPS:
                whites.append(n)
            n += 1
        ww = w / len(whites)
        keys = [(note, QRectF(x0 + i * ww, y0, ww, h), True) for i, note in enumerate(whites)]
        for i, note in enumerate(whites[:-1]):
            if (note + 1) % 12 in (1, 3, 6, 8, 10):
                keys.append((note + 1, QRectF(x0 + (i + 1) * ww - ww * 0.31, y0, ww * 0.62, h * 0.6), False))
        return keys

    # ------------------------------------------------------------------ API
    def flash_pad(self, i):
        if 0 <= i < PAD_COUNT:
            self.pad_glow[i] = 1.0
            self.update()

    def set_key(self, note, on):
        (self.active.add if on else self.active.discard)(note)
        self.update()

    def set_knob(self, i, value):
        self.knob_values[i] = value
        self.update()

    def _animate(self):
        changed = False
        for i, g in enumerate(self.pad_glow):
            if g > 0:
                self.pad_glow[i] = max(0.0, g - 0.08)
                changed = True
        if self.learn_target is not None or changed:
            self.update()

    # ------------------------------------------------------------------ mouse
    def _hit(self, v):
        for i in range(PAD_COUNT):
            if _pad_rect(i).contains(v):
                return ("pad", i)
        for i in range(KNOB_COUNT):
            c = _knob_center(i)
            if (v.x() - c.x()) ** 2 + (v.y() - c.y()) ** 2 < 30 ** 2:
                return ("knob", i)
        for i, r in enumerate(self._buttons()):
            if r.contains(v):
                return ("button", i)
        if QRectF(30, 248, 46, 22).contains(v):
            return ("oct", -1)
        if QRectF(84, 248, 46, 22).contains(v):
            return ("oct", 1)
        keys = self._keys()
        for note, r, white in keys:
            if not white and r.contains(v):
                return ("key", note)
        for note, r, white in keys:
            if white and r.contains(v):
                return ("key", note)
        return None

    def mousePressEvent(self, e):
        v = self._to_virtual(e.position())
        hit = self._hit(v)
        if hit is None:
            return
        kind, i = hit
        if kind == "pad":
            r = _pad_rect(i)
            vel = int(60 + 67 * min(max((v.y() - r.top()) / r.height(), 0), 1))
            self.padPressed.emit(i, vel)
        elif kind == "knob":
            self._drag = (i, v.y(), self.knob_values[i])
        elif kind == "button":
            self.buttonPressed.emit(i)
        elif kind == "oct":
            self.base_note = max(24, min(84, self.base_note + 12 * i))
            self.octaveChanged.emit(self.base_note)
            self.update()
        elif kind == "key":
            self._mouse = i
            self.keyOn.emit(i, 100)

    def mouseMoveEvent(self, e):
        v = self._to_virtual(e.position())
        if self._drag is not None:
            i, y0, val0 = self._drag
            val = int(min(127, max(0, val0 + (y0 - v.y()) * 1.4)))
            if val != self.knob_values[i]:
                self.knobMoved.emit(i, val)
            return
        if self._mouse is not None:
            hit = self._hit(v)
            if hit and hit[0] == "key" and hit[1] != self._mouse:
                self.keyOff.emit(self._mouse)
                self._mouse = hit[1]
                self.keyOn.emit(self._mouse, 100)

    def mouseReleaseEvent(self, e):
        self._drag = None
        if self._mouse is not None:
            self.keyOff.emit(self._mouse)
            self._mouse = None

    # ------------------------------------------------------------------ desenho
    def _blink(self, kind, i):
        if self.learn_target != (kind, i):
            return None
        a = 0.5 + 0.5 * math.sin(time.monotonic() * 8)
        return QPen(QColor(255, 200, 0, int(120 + 135 * a)), 4)

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        s, ox, oy = self._transform()
        qp.translate(ox, oy)
        qp.scale(s, s)

        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, VW, VH), 18, 18)
        g = QLinearGradient(0, 0, 0, VH)
        g.setColorAt(0, QColor("#f4f5f7"))
        g.setColorAt(1, QColor("#dfe2e6"))
        qp.fillPath(body, g)
        qp.setPen(QPen(QColor("#b9bec5"), 2))
        qp.drawPath(body)

        small = QFont("Segoe UI")
        small.setPixelSize(10)
        small.setBold(True)
        tiny = QFont("Segoe UI")
        tiny.setPixelSize(9)

        # pitch / mod
        qp.setFont(small)
        for x, label in ((30, "PITCH"), (84, "MOD")):
            qp.setPen(QColor("#555b63"))
            qp.drawText(QRectF(x - 6, 14, 58, 14), Qt.AlignCenter, label)
            qp.setPen(QPen(QColor("#c6cbd1"), 1))
            qp.setBrush(QColor("#ffffff"))
            qp.drawRoundedRect(QRectF(x, 32, 46, 200), 8, 8)
        for x, label in ((30, "OCT−"), (84, "OCT+")):
            qp.setPen(QPen(QColor("#b9bec5"), 1))
            qp.setBrush(QColor("#ffffff"))
            qp.drawRoundedRect(QRectF(x, 248, 46, 22), 4, 4)
            qp.setPen(QColor("#333"))
            qp.drawText(QRectF(x, 248, 46, 22), Qt.AlignCenter, label)
        qp.setFont(tiny)
        qp.setPen(QColor("#666"))
        qp.drawText(QRectF(24, 271, 112, 14), Qt.AlignCenter,
                    f"teclas na tela: {note_name(self.base_note)}–{note_name(self.base_note + 24)}")

        # visor (a "tela" do controlador)
        lcd = QRectF(150, 30, 248, 72)
        qp.setPen(QPen(QColor("#111"), 2))
        qp.setBrush(QColor("#0b0f0d"))
        qp.drawRoundedRect(lcd, 6, 6)
        f = QFont("Consolas")
        f.setPixelSize(19)
        f.setBold(True)
        qp.setFont(f)
        qp.setPen(QColor("#ff5a4f"))
        qp.drawText(lcd.adjusted(10, 6, -10, -36), Qt.AlignLeft | Qt.AlignVCenter,
                    _fit(qp, self.display[0], lcd.width() - 20))
        f.setPixelSize(14)
        f.setBold(False)
        qp.setFont(f)
        qp.setPen(QColor("#ffb0a8"))
        qp.drawText(lcd.adjusted(10, 38, -10, -6), Qt.AlignLeft | Qt.AlignVCenter,
                    _fit(qp, self.display[1], lcd.width() - 20))

        # botões
        for i, r in enumerate(self._buttons()):
            pen = self._blink("buttons", i) or QPen(QColor("#b9bec5"), 1)
            qp.setPen(pen)
            qp.setBrush(QColor("#ffffff") if BUTTONS[i] != "BT" else QColor("#dfe8ff"))
            qp.drawRoundedRect(r, 4, 4)
            qp.setFont(small)
            qp.setPen(QColor("#333"))
            qp.drawText(r.adjusted(0, 2, 0, -14), Qt.AlignCenter, BUTTONS[i])
            qp.setFont(tiny)
            qp.setPen(QColor("#2563eb"))
            qp.drawText(r.adjusted(1, 16, -1, 0), Qt.AlignCenter, BUTTON_SHORT.get(self.button_labels[i], _short(self.button_labels[i])))

        # knobs
        for i in range(KNOB_COUNT):
            c = _knob_center(i)
            pen = self._blink("knobs", i)
            if pen:
                qp.setPen(pen)
                qp.setBrush(Qt.NoBrush)
                qp.drawEllipse(c, 33, 33)
            kg = QLinearGradient(c.x(), c.y() - 26, c.x(), c.y() + 26)
            kg.setColorAt(0, QColor("#3a3a3a"))
            kg.setColorAt(1, QColor("#0d0d0d"))
            qp.setPen(QPen(QColor("#000"), 1))
            qp.setBrush(kg)
            qp.drawEllipse(c, 24, 24)
            qp.setPen(QPen(QColor("#2a2a2a"), 1))
            for k in range(18):          # serrilhado
                a = math.radians(k * 20)
                qp.drawLine(QPointF(c.x() + 21 * math.cos(a), c.y() + 21 * math.sin(a)),
                            QPointF(c.x() + 24 * math.cos(a), c.y() + 24 * math.sin(a)))
            ang = math.radians(225 - 270 * self.knob_values[i] / 127)
            qp.setPen(QPen(QColor("#ffffff"), 3, Qt.SolidLine, Qt.RoundCap))
            qp.drawLine(QPointF(c.x() + 8 * math.cos(ang), c.y() - 8 * math.sin(ang)),
                        QPointF(c.x() + 21 * math.cos(ang), c.y() - 21 * math.sin(ang)))
            qp.setFont(tiny)
            qp.setPen(QColor("#2b2f35"))
            qp.drawText(QRectF(c.x() - 40, c.y() + 26, 80, 12), Qt.AlignCenter,
                        _short(self.knob_labels[i], 16))

        # pads
        for i in range(PAD_COUNT):
            r = _pad_rect(i)
            base = QColor("#8fe9f0") if i < 4 else QColor("#d7c2ff")
            glow = self.pad_glow[i]
            col = QColor(base)
            if glow > 0:
                col = QColor(int(base.red() + (255 - base.red()) * glow),
                             int(base.green() + (255 - base.green()) * glow),
                             int(base.blue() + (255 - base.blue()) * glow))
            pg = QLinearGradient(r.topLeft(), r.bottomLeft())
            pg.setColorAt(0, col.lighter(110))
            pg.setColorAt(1, col)
            pen = self._blink("pads", i) or QPen(QColor("#9aa3ad"), 1)
            qp.setPen(pen)
            qp.setBrush(pg)
            qp.drawRoundedRect(r, 8, 8)
            qp.setFont(tiny)
            qp.setPen(QColor("#4b5563"))
            qp.drawText(QRectF(r.left(), r.top() - 13, r.width(), 12), Qt.AlignLeft, f"Pad {i + 1}")
            qp.setFont(small)
            qp.setPen(QColor("#1f2937"))
            qp.drawText(r.adjusted(4, 4, -4, -4), Qt.AlignCenter | Qt.TextWordWrap, self.pad_labels[i])

        # marca do modelo (identificação do aparelho)
        f = QFont("Segoe UI")
        f.setPixelSize(22)
        f.setBold(True)
        qp.setFont(f)
        qp.setPen(QColor("#2b2f35"))
        qp.drawText(QRectF(590, 256, 390, 28), Qt.AlignRight | Qt.AlignVCenter, "SMK-25")

        # teclas
        keys = self._keys()
        for note, r, white in keys:
            if white:
                qp.setPen(QPen(QColor("#9aa0a8"), 1))
                qp.setBrush(QColor("#7c9cff") if note in self.active else QColor("#ffffff"))
                qp.drawRect(r)
                if note % 12 == 0:
                    qp.setFont(tiny)
                    qp.setPen(QColor("#777"))
                    qp.drawText(r.adjusted(0, 0, 0, -4), Qt.AlignHCenter | Qt.AlignBottom, note_name(note))
        for note, r, white in keys:
            if not white:
                qp.setPen(QPen(QColor("#000"), 1))
                qp.setBrush(QColor("#5a73cc") if note in self.active else QColor("#1b1b1f"))
                qp.drawRect(r)


BUTTON_SHORT = {"Nenhuma": "—", "Timbre anterior": "◀ timbre", "Próximo timbre": "timbre ▶",
                "Kit anterior": "◀ kit", "Próximo kit": "kit ▶", "Liga/desliga camada 2": "camada 2",
                "Pânico (soltar notas)": "pânico"}


def _short(text, n=10):
    return text if len(text) <= n else text[: n - 1] + "…"


def _fit(qp, text, width):
    fm = qp.fontMetrics()
    return fm.elidedText(text, Qt.ElideRight, int(width))


def pad_label(note):
    return DRUM_NAMES.get(note, f"Nota {note}")
