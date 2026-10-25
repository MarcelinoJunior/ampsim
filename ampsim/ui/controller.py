"""Instrumento/controlador desenhado na tela: M-VAVE SMK-25, Yamaha PSR-E473 ou Roland VR-730.

Mostra o que acontece no aparelho real (pads acendem, teclas e knobs se mexem) e também pode
ser tocado com o mouse. Botão direito em pad/knob/botão/tecla abre a escolha de som ou função.
No modo "mapear", o elemento esperado pisca em amarelo.

Cada modelo descreve sua geometria em coordenadas virtuais próprias; o desenho é escalado
para caber no widget mantendo a proporção.
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..instruments import BUTTONS, PAD_COUNT, note_name

WHITE_STEPS = (0, 2, 4, 5, 7, 9, 11)

BUTTON_SHORT = {"Nenhuma": "—", "Timbre anterior": "◀ timbre", "Próximo timbre": "timbre ▶",
                "Preset de pads anterior": "◀ pads", "Próximo preset de pads": "pads ▶",
                "Liga/desliga camada 2": "camada 2", "Parar pad contínuo": "para pad",
                "Banco de pads A/B (tela)": "banco A/B", "Pânico (soltar notas)": "pânico"}


def _r(x, y, w, h):
    return QRectF(x, y, w, h)


# ------------------------------------------------------------------ modelos
def _smk25():
    return dict(
        name="M-VAVE SMK-25", size=(1000, 430), body=("#f4f5f7", "#dfe2e6"), outline="#b9bec5",
        dark=False, wood=False,
        display=dict(rect=_r(150, 30, 248, 72), bg="#0b0f0d", fg="#ff5a4f", fg2="#ffb0a8",
                     font="Consolas"),
        knobs=[(i, QPointF(190 + (i % 4) * 78, 150 + (i // 4) * 88), 24) for i in range(8)],
        buttons=[(i, _r(410 + (i % 4) * 44, 34 + (i // 4) * 40, 40, 32), BUTTONS[i]) for i in range(8)],
        pads=[(i, _r(590 + (i % 4) * 100, 34 + (i // 4) * 112, 88, 100)) for i in range(8)],
        pad_style="smk", pad_caption=QPointF(590, 2),
        keys=(_r(20, 292, 960, 128), 48, 25),
        strips=[(_r(30, 32, 46, 200), "PITCH"), (_r(84, 32, 46, 200), "MOD")],
        oct=[(-1, _r(30, 248, 46, 22), "OCT−"), (1, _r(84, 248, 46, 22), "OCT+")],
        texts=[(_r(590, 256, 390, 28), "SMK-25", 22, True, "#2b2f35", Qt.AlignRight)],
    )


def _psr_e473():
    names = ("START", "SYNC", "INTRO", "FILL", "VOICE", "STYLE", "SPLIT", "DUAL")
    return dict(
        name="Yamaha PSR-E473", size=(1400, 480), body=("#2a2b2f", "#161719"), outline="#000000",
        dark=True, wood=False,
        display=dict(rect=_r(560, 36, 250, 128), bg="#a8c8e4", fg="#0f2742", fg2="#24476e",
                     font="Segoe UI"),
        knobs=[(7, QPointF(318, 214), 17), (0, QPointF(420, 170), 21), (1, QPointF(490, 170), 21)],
        knob_names={7: "MASTER VOL.", 0: "KNOB A", 1: "KNOB B"},
        buttons=[(i, _r(930 + (i % 4) * 46, 46 + (i // 4) * 46, 40, 32), names[i]) for i in range(8)],
        pads=[(i, _r(1140 + i * 62, 230, 54, 28)) for i in range(4)],
        pad_style="flat", pad_caption=QPointF(1140, 214),
        keys=(_r(92, 272, 1290, 196), 36, 61),
        wheel=_r(30, 300, 42, 130),
        speakers=[_r(22, 18, 240, 180), _r(1138, 18, 240, 180)],
        dial=(QPointF(872, 104), 38),
        oct=[(-1, _r(300, 120, 52, 22), "TRANS−"), (1, _r(356, 120, 52, 22), "TRANS+")],
        texts=[(_r(560, 6, 250, 26), "YAMAHA", 16, True, "#d9dde1", Qt.AlignCenter),
               (_r(20, 236, 300, 30), "PSR-E473", 20, True, "#d9dde1", Qt.AlignLeft),
               (_r(300, 40, 230, 16), "LIVE CONTROL", 10, True, "#aeb3b9", Qt.AlignCenter)],
    )


def _vr730():
    names = ("LEAKAGE", "PERC", "VIBRATO", "ROTARY", "SPLIT", "LAYER", "SCENE", "WRITE")
    return dict(
        name="Roland VR-730", size=(1500, 440), body=("#1d1d1f", "#0e0e10"), outline="#000000",
        dark=True, wood=True,
        display=dict(rect=_r(660, 40, 230, 108), bg="#1d4f9a", fg="#ffffff", fg2="#bcd3f5",
                     font="Segoe UI"),
        knobs=[(i, QPointF(72 + (i % 4) * 68, 66 + (i // 4) * 88), 18) for i in range(8)],
        buttons=[(i, _r(1000 + (i % 4) * 52, 46 + (i // 4) * 50, 46, 34), names[i]) for i in range(8)],
        pads=[(i, _r(1228 + (i % 4) * 60, 46 + (i // 4) * 54, 52, 40)) for i in range(8)],
        pad_style="reg", pad_caption=QPointF(1228, 22),
        keys=(_r(70, 238, 1385, 192), 28, 73),
        drawbars=_r(350, 26, 270, 190),
        dial=(QPointF(950, 96), 40),
        oct=[(-1, _r(30, 238, 34, 22), "−"), (1, _r(30, 266, 34, 22), "+")],
        texts=[(_r(30, 4, 200, 24), "Roland", 18, True, "#e8e8e8", Qt.AlignLeft),
               (_r(660, 160, 230, 24), "V-Combo VR-730", 15, True, "#e8e8e8", Qt.AlignCenter),
               (_r(350, 4, 270, 18), "HARMONIC BARS", 10, True, "#aeb3b9", Qt.AlignCenter)],
    )


MODELS = {"M-VAVE SMK-25": _smk25, "Yamaha PSR-E473": _psr_e473, "Roland VR-730": _vr730}
TRADEMARKS = ("M-VAVE, Yamaha (PSR-E473) e Roland (V-Combo VR-730) são marcas de seus respectivos "
              "titulares. Desenho ilustrativo; o AmpSim não é afiliado nem endossado.")


class ControllerWidget(QWidget):
    padPressed = Signal(int, int)
    keyOn = Signal(int, int)
    keyOff = Signal(int)
    knobMoved = Signal(int, int)
    buttonPressed = Signal(int)
    octaveChanged = Signal(int)
    contextRequested = Signal(str, int, object)      # tipo, índice, posição global (botão direito)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.display = ("", "")
        self.pad_labels = [""] * PAD_COUNT
        self.pad_keys_b = [""] * PAD_COUNT
        self.bank = 0                       # 0 = banco A (bateria), 1 = banco B (pad contínuo)
        self.cont_key = None
        self.knob_labels = [""] * 8
        self.button_labels = [""] * len(BUTTONS)
        self.knob_values = [64] * 8
        self.pad_glow = [0.0] * PAD_COUNT
        self.active = set()
        self.learn_target = None            # ("pads"|"pads_b"|"knobs"|"buttons", índice)
        self._mouse = None
        self._drag = None
        self.set_model("M-VAVE SMK-25")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(33)

    def set_model(self, name):
        self.model_name = name if name in MODELS else "M-VAVE SMK-25"
        self.m = MODELS[self.model_name]()
        self.base_note = self.m["keys"][1]
        self.update()

    # ------------------------------------------------------------------ geometria
    def _transform(self):
        vw, vh = self.m["size"]
        s = min(self.width() / vw, self.height() / vh)
        return s, (self.width() - vw * s) / 2, (self.height() - vh * s) / 2

    def _to_virtual(self, pos):
        s, ox, oy = self._transform()
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def _keys(self):
        """[(nota, retângulo, branca)] das teclas do modelo."""
        rect, _, count = self.m["keys"]
        notes = list(range(self.base_note, self.base_note + count))
        whites = [n for n in notes if n % 12 in WHITE_STEPS]
        ww = rect.width() / len(whites)
        keys = [(n, QRectF(rect.left() + i * ww, rect.top(), ww, rect.height()), True)
                for i, n in enumerate(whites)]
        for i, n in enumerate(whites[:-1]):
            if (n + 1) % 12 in (1, 3, 6, 8, 10) and n + 1 in notes:
                keys.append((n + 1, QRectF(rect.left() + (i + 1) * ww - ww * 0.31, rect.top(),
                                           ww * 0.62, rect.height() * 0.62), False))
        return keys

    # ------------------------------------------------------------------ API
    def flash_pad(self, i):
        self.pad_glow[i % PAD_COUNT] = 1.0
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
        m = self.m
        for i, r in m["pads"]:
            if r.contains(v):
                return ("pad", i)
        for i, c, rad in m["knobs"]:
            if (v.x() - c.x()) ** 2 + (v.y() - c.y()) ** 2 < (rad + 6) ** 2:
                return ("knob", i)
        for i, r, _ in m["buttons"]:
            if r.contains(v):
                return ("button", i)
        for d, r, _ in m.get("oct", []):
            if r.contains(v):
                return ("oct", d)
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
        if e.button() == Qt.RightButton:
            if kind == "pad":
                i += PAD_COUNT * self.bank
            if kind in ("pad", "knob", "button", "key"):
                self.contextRequested.emit(kind, i, e.globalPosition().toPoint())
            return
        if kind == "pad":
            r = dict(self.m["pads"])[i]
            vel = int(60 + 67 * min(max((v.y() - r.top()) / r.height(), 0), 1))
            self.padPressed.emit(i + PAD_COUNT * self.bank, vel)
        elif kind == "knob":
            self._drag = (i, v.y(), self.knob_values[i])
        elif kind == "button":
            self.buttonPressed.emit(i)
        elif kind == "oct":
            count = self.m["keys"][2]
            self.base_note = max(12, min(108 - count, self.base_note + 12 * i))
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

    @staticmethod
    def _font(px, bold=False, family="Segoe UI"):
        f = QFont(family)
        f.setPixelSize(int(px))
        f.setBold(bold)
        return f

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        s, ox, oy = self._transform()
        qp.translate(ox, oy)
        qp.scale(s, s)
        m = self.m
        vw, vh = m["size"]
        dark = m["dark"]
        ink = QColor("#d9dde1") if dark else QColor("#2b2f35")
        sub = QColor("#9aa0a8") if dark else QColor("#555b63")

        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, vw, vh), 16, 16)
        g = QLinearGradient(0, 0, 0, vh)
        g.setColorAt(0, QColor(m["body"][0]))
        g.setColorAt(1, QColor(m["body"][1]))
        qp.fillPath(body, g)
        qp.setPen(QPen(QColor(m["outline"]), 2))
        qp.drawPath(body)
        if m["wood"]:
            for x in (0, vw - 24):
                wg = QLinearGradient(x, 0, x + 24, 0)
                wg.setColorAt(0, QColor("#4a2812"))
                wg.setColorAt(0.5, QColor("#7a4622"))
                wg.setColorAt(1, QColor("#4a2812"))
                qp.fillRect(QRectF(x, 0, 24, vh), wg)

        for r in m.get("speakers", []):                       # alto-falantes (PSR)
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor("#111214"))
            qp.drawRoundedRect(r, 10, 10)
            qp.setBrush(QColor("#2e3034"))
            y = r.top() + 8
            row = 0
            while y < r.bottom() - 4:
                x = r.left() + 8 + (5 if row % 2 else 0)
                while x < r.right() - 4:
                    qp.drawEllipse(QPointF(x, y), 1.8, 1.8)
                    x += 10
                y += 8
                row += 1

        if "drawbars" in m:                                    # drawbars (VR-730)
            r = m["drawbars"]
            colors = ("#7a4622", "#7a4622", "#f2f2f2", "#f2f2f2", "#111111", "#f2f2f2", "#111111",
                      "#111111", "#f2f2f2")
            levels = (8, 8, 8, 0, 0, 0, 0, 0, 0)
            w = r.width() / 9
            for j in range(9):
                x = r.left() + j * w + w / 2
                qp.setPen(QPen(QColor("#050505"), 6))
                qp.drawLine(QPointF(x, r.top() + 10), QPointF(x, r.bottom() - 10))
                hy = r.top() + 12 + (r.height() - 50) * (levels[j] / 8)
                qp.setPen(QPen(QColor("#000"), 1))
                qp.setBrush(QColor(colors[j]))
                qp.drawRoundedRect(QRectF(x - w * 0.36, hy, w * 0.72, 24), 3, 3)

        if "dial" in m:
            c, rad = m["dial"]
            dg = QLinearGradient(c.x(), c.y() - rad, c.x(), c.y() + rad)
            dg.setColorAt(0, QColor("#5a5d63"))
            dg.setColorAt(1, QColor("#1b1c1f"))
            qp.setPen(QPen(QColor("#000"), 1))
            qp.setBrush(dg)
            qp.drawEllipse(c, rad, rad)
            qp.setBrush(QColor("#2b2d31"))
            qp.drawEllipse(c, rad * 0.55, rad * 0.55)

        if "wheel" in m:                                       # pitch bend (PSR)
            r = m["wheel"]
            qp.setPen(QPen(QColor("#000"), 1))
            qp.setBrush(QColor("#0d0d0f"))
            qp.drawRoundedRect(r, 6, 6)
            qp.setBrush(QColor("#3a3c40"))
            qp.drawRoundedRect(r.adjusted(8, 10, -8, -10), 4, 4)
            qp.setFont(self._font(9, True))
            qp.setPen(sub)
            qp.drawText(QRectF(r.left() - 10, r.top() - 16, r.width() + 20, 14), Qt.AlignCenter, "PITCH")

        for r, label in m.get("strips", []):                   # pitch/mod touch (SMK)
            qp.setFont(self._font(10, True))
            qp.setPen(sub)
            qp.drawText(QRectF(r.left() - 6, r.top() - 18, r.width() + 12, 14), Qt.AlignCenter, label)
            qp.setPen(QPen(QColor("#c6cbd1"), 1))
            qp.setBrush(QColor("#ffffff"))
            qp.drawRoundedRect(r, 8, 8)

        for d, r, label in m.get("oct", []):
            qp.setPen(QPen(QColor("#555") if dark else QColor("#b9bec5"), 1))
            qp.setBrush(QColor("#3a3c40") if dark else QColor("#ffffff"))
            qp.drawRoundedRect(r, 4, 4)
            qp.setFont(self._font(10, True))
            qp.setPen(ink)
            qp.drawText(r, Qt.AlignCenter, label)

        for r, text, px, bold, color, align in m.get("texts", []):
            qp.setFont(self._font(px, bold))
            qp.setPen(QColor(color))
            qp.drawText(r, align | Qt.AlignVCenter, text)

        # visor
        d = m["display"]
        lcd = d["rect"]
        qp.setPen(QPen(QColor("#111"), 2))
        qp.setBrush(QColor(d["bg"]))
        qp.drawRoundedRect(lcd, 6, 6)
        qp.setFont(self._font(lcd.height() * 0.24, True, d["font"]))
        qp.setPen(QColor(d["fg"]))
        top = QRectF(lcd.left() + 10, lcd.top() + 6, lcd.width() - 20, lcd.height() * 0.5 - 6)
        qp.drawText(top, Qt.AlignLeft | Qt.AlignVCenter,
                    qp.fontMetrics().elidedText(self.display[0], Qt.ElideRight, int(top.width())))
        qp.setFont(self._font(lcd.height() * 0.18, False, d["font"]))
        qp.setPen(QColor(d["fg2"]))
        bot = QRectF(lcd.left() + 10, lcd.top() + lcd.height() * 0.5, lcd.width() - 20, lcd.height() * 0.5 - 6)
        qp.drawText(bot, Qt.AlignLeft | Qt.AlignVCenter,
                    qp.fontMetrics().elidedText(self.display[1], Qt.ElideRight, int(bot.width())))

        # botões
        for i, r, name in m["buttons"]:
            pen = self._blink("buttons", i) or QPen(QColor("#555") if dark else QColor("#b9bec5"), 1)
            qp.setPen(pen)
            qp.setBrush(QColor("#3a3c40") if dark else (QColor("#dfe8ff") if name == "BT" else QColor("#ffffff")))
            qp.drawRoundedRect(r, 4, 4)
            qp.setFont(self._font(9 if len(name) > 5 else 10, True))
            qp.setPen(ink)
            qp.drawText(r.adjusted(0, 2, 0, -r.height() * 0.45), Qt.AlignCenter, name)
            qp.setFont(self._font(9))
            qp.setPen(QColor("#7fb2ff") if dark else QColor("#2563eb"))
            qp.drawText(r.adjusted(1, r.height() * 0.5, -1, 0), Qt.AlignCenter,
                        BUTTON_SHORT.get(self.button_labels[i], self.button_labels[i][:9]))

        # knobs
        names = m.get("knob_names", {})
        for i, c, rad in m["knobs"]:
            pen = self._blink("knobs", i)
            if pen:
                qp.setPen(pen)
                qp.setBrush(Qt.NoBrush)
                qp.drawEllipse(c, rad + 9, rad + 9)
            kg = QLinearGradient(c.x(), c.y() - rad, c.x(), c.y() + rad)
            kg.setColorAt(0, QColor("#4a4a4a"))
            kg.setColorAt(1, QColor("#0d0d0d"))
            qp.setPen(QPen(QColor("#000"), 1))
            qp.setBrush(kg)
            qp.drawEllipse(c, rad, rad)
            ang = math.radians(225 - 270 * self.knob_values[i] / 127)
            qp.setPen(QPen(QColor("#ffffff"), 2.5, Qt.SolidLine, Qt.RoundCap))
            qp.drawLine(QPointF(c.x() + rad * 0.3 * math.cos(ang), c.y() - rad * 0.3 * math.sin(ang)),
                        QPointF(c.x() + rad * 0.88 * math.cos(ang), c.y() - rad * 0.88 * math.sin(ang)))
            qp.setFont(self._font(9))
            qp.setPen(ink)
            label = names.get(i, "")
            func = self.knob_labels[i] if i < len(self.knob_labels) else ""
            txt = f"{label}\n{func}" if label else func
            qp.drawText(QRectF(c.x() - 46, c.y() + rad + 2, 92, 26), Qt.AlignHCenter | Qt.AlignTop,
                        _short2(txt))

        # pads (banco A = bateria; banco B = tons do pad contínuo)
        cap = m["pad_caption"]
        qp.setFont(self._font(10, True))
        qp.setPen(ink)
        qp.drawText(QRectF(cap.x(), cap.y(), 420, 14), Qt.AlignLeft,
                    "BANCO B — pad contínuo" if self.bank else "BANCO A — bateria")
        style = m["pad_style"]
        for i, r in m["pads"]:
            if self.bank:
                key = self.pad_keys_b[i]
                base = QColor("#ffd27a") if (key == self.cont_key and key != "Parar") else \
                    (QColor("#f3b2b2") if key == "Parar" else QColor("#fde7c0"))
            elif style == "smk":
                base = QColor("#8fe9f0") if i < 4 else QColor("#d7c2ff")
            elif style == "reg":
                base = QColor("#d63a3a") if i % 2 == 0 else QColor("#f2f2f2")
            else:
                base = QColor("#f2f2f2")
            glow = self.pad_glow[i]
            col = QColor(int(base.red() + (255 - base.red()) * glow),
                         int(base.green() + (255 - base.green()) * glow),
                         int(base.blue() + (255 - base.blue()) * glow))
            pg = QLinearGradient(r.topLeft(), r.bottomLeft())
            pg.setColorAt(0, col.lighter(110))
            pg.setColorAt(1, col)
            pen = self._blink("pads_b" if self.bank else "pads", i) or QPen(QColor("#6b7280"), 1)
            qp.setPen(pen)
            qp.setBrush(pg)
            qp.drawRoundedRect(r, 6, 6)
            text = self.pad_keys_b[i] if self.bank else self.pad_labels[i]
            px = min(r.height() * (0.45 if self.bank else 0.22), 30 if self.bank else 11)
            qp.setFont(self._font(px, True))
            qp.setPen(QColor("#2a1d0d") if (self.bank or style != "reg" or i % 2) else QColor("#ffffff"))
            qp.drawText(r.adjusted(3, 2, -3, -2), Qt.AlignCenter | Qt.TextWordWrap,
                        text if self.bank or r.height() > 60 else _short2(text, 12))

        # teclas
        keys = self._keys()
        qp.setFont(self._font(10))
        for note, r, white in keys:
            if white:
                qp.setPen(QPen(QColor("#9aa0a8"), 1))
                qp.setBrush(QColor("#7c9cff") if note in self.active else QColor("#fdfdfd"))
                qp.drawRect(r)
                if note % 12 == 0:
                    qp.setPen(QColor("#777"))
                    qp.drawText(r.adjusted(0, 0, 0, -4), Qt.AlignHCenter | Qt.AlignBottom, note_name(note))
        for note, r, white in keys:
            if not white:
                qp.setPen(QPen(QColor("#000"), 1))
                qp.setBrush(QColor("#5a73cc") if note in self.active else QColor("#18181b"))
                qp.drawRect(r)


def _short2(text, n=18):
    lines = text.split("\n")
    return "\n".join(t if len(t) <= n else t[: n - 1] + "…" for t in lines)
