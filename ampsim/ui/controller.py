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
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..instruments import BUTTONS, PAD_COUNT, note_name

WHITE_STEPS = (0, 2, 4, 5, 7, 9, 11)

BUTTON_SHORT = {"Nenhuma": "—", "Tap tempo (BPM)": "tap", "Timbre anterior": "◀ timbre", "Próximo timbre": "timbre ▶",
                "Preset de pads anterior": "◀ pads", "Próximo preset de pads": "pads ▶",
                "Liga/desliga camada 2": "camada 2", "Parar pad contínuo": "para pad",
                "Banco de pads A/B (tela)": "banco A/B", "Pânico (soltar notas)": "pânico",
                "Rotação lenta/rápida": "rotação", "Rotação liga/desliga": "rot. on", "Delay liga/desliga": "delay",
                "Drive liga/desliga": "drive", "Sustain (segurar)": "sustain", "Oitava −": "oit −",
                "Oitava +": "oit +"}


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
        texts=[(_r(590, 254, 230, 32), "M-VAVE", 27, True, "#1d2024", Qt.AlignLeft, "Arial Black", 104),
               (_r(780, 256, 200, 28), "SMK-25", 22, False, "#2b2f35", Qt.AlignRight, "Segoe UI", 100)],
    )


def _psr_e473():
    names = ("START", "SYNC", "INTRO", "FILL", "VOICE", "STYLE", "SPLIT", "DUAL")
    return dict(
        name="Yamaha PSR-E473", style="psr", size=(1400, 600), dark=True,
        display=dict(rect=_r(600, 64, 200, 118), bg="#a7c0d1", fg="#10283f", fg2="#24476e",
                     font="Segoe UI"),
        knobs=[(7, QPointF(96, 336), 22), (0, QPointF(452, 108), 22), (1, QPointF(530, 108), 22)],
        knob_names={7: "MASTER VOLUME", 0: "KNOB A", 1: "KNOB B"}, knob_ring="#3aa0ff",
        buttons=[(i, _r(352 + i * 62, 316, 54, 30), names[i]) for i in range(8)], button_led=True,
        pads=[(i, _r(1078 + i * 70, 312, 60, 36)) for i in range(4)],
        pad_style="flat", pad_caption=QPointF(1078, 292),
        keys=(_r(104, 384, 1276, 206), 36, 61),
        oct=[(-1, _r(160, 318, 52, 26), "TRANS−"), (1, _r(216, 318, 52, 26), "TRANS+")],
    )


def _vr730():
    names = ("LEAKAGE", "PERC", "VIBRATO", "ROTARY", "SPLIT", "LAYER", "SCENE", "WRITE")
    return dict(
        name="Roland VR-730", style="vr", size=(1600, 460), dark=True,
        display=dict(rect=_r(800, 46, 222, 104), bg="#1e5bb0", fg="#ffffff", fg2="#c6dbff",
                     font="Segoe UI"),
        knobs=[(i, QPointF(250 + (i % 4) * 62, 72 + (i // 4) * 82), 19) for i in range(8)],
        knob_skirt=True,
        buttons=[(i, _r(1124 + (i % 4) * 54, 48 + (i // 4) * 58, 48, 36), names[i]) for i in range(8)],
        button_led=True,
        pads=[(i, _r(1356 + (i % 4) * 52, 54 + (i // 4) * 58, 44, 40)) for i in range(8)],
        pad_style="reg", pad_caption=QPointF(1356, 26),
        keys=(_r(112, 262, 1452, 190), 28, 73),
        oct=[(-1, _r(40, 380, 54, 24), "OCT −"), (1, _r(40, 410, 54, 24), "OCT +")],
    )


MODELS = {"M-VAVE SMK-25": _smk25, "Yamaha PSR-E473": _psr_e473, "Roland VR-730": _vr730}
TRADEMARKS = ("Desenhos em homenagem aos instrumentos originais. M-VAVE (SMK-25), Yamaha (PSR-E473) e "
              "Roland (V-Combo VR-730), seus logotipos e imagens pertencem aos respectivos titulares; "
              "o AmpSim não é afiliado nem endossado por eles.")


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
        self.setMouseTracking(True)
        self.ready_index = 0
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
        self.split_note = None              # teclado dividido: 1ª nota da mão direita
        self.zone_names = ("", "")           # timbres (mão esquerda, mão direita)
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
        if self._drag is None and self._mouse is None:
            self._hover_tip(v, e.globalPosition().toPoint())
            return
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

    def _hover_tip(self, v, gpos):
        hit = self._hit(v)
        tip = ""
        if hit:
            kind, i = hit
            if kind == "knob":
                tip = f"Knob {i + 1}: {self.knob_labels[i]}\n(arraste para mudar · botão direito: função)"
            elif kind == "button":
                tip = f"{BUTTONS[i]}: {self.button_labels[i]}\n(botão direito: função)"
            elif kind == "key":
                if self.split_note is not None:
                    left = i < self.split_note
                    tip = (f"{note_name(i)} · mão {'esquerda' if left else 'direita'}: "
                           f"{self.zone_names[0 if left else 1]}\n(botão direito: trocar timbre ou dividir aqui)")
                else:
                    tip = f"{note_name(i)}\n(botão direito: trocar timbre ou dividir o teclado aqui)"
            elif kind == "pad":
                tip = (f"Pad {i + 1} B: {self.pad_keys_b[i]}" if self.bank else
                       f"Pad {i + 1}: {self.pad_labels[i]}") + "\n(botão direito: trocar)"
        if tip:
            QToolTip.showText(gpos, tip, self)
        else:
            QToolTip.hideText()

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

        style = m.get("style", "smk")
        if style == "psr":
            self._decor_psr(qp, vw, vh)
        elif style == "vr":
            self._decor_vr(qp, vw, vh)
        else:
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

            for t in m.get("texts", []):          # (rect, texto, px, negrito, cor, alinh. [, fonte, espaço, itálico])
                r, text, px, bold, color, align = t[:6]
                f = self._font(px, bold, t[6] if len(t) > 6 else "Segoe UI")
                if len(t) > 7:
                    f.setLetterSpacing(QFont.PercentageSpacing, t[7])
                if len(t) > 8:
                    f.setItalic(t[8])
                qp.setFont(f)
                qp.setPen(QColor(color))
                qp.drawText(r, align | Qt.AlignVCenter, text)

        # visor
        d = m["display"]
        lcd = d["rect"]
        if style in ("psr", "vr"):
            qp.setPen(QPen(QColor("#8a9099"), 2))
            qp.setBrush(QColor("#08090a"))
            qp.drawRoundedRect(lcd.adjusted(-10, -10, 10, 10), 8, 8)
        lg = QLinearGradient(lcd.topLeft(), lcd.bottomLeft())
        lg.setColorAt(0, QColor(d["bg"]).lighter(112))
        lg.setColorAt(1, QColor(d["bg"]))
        qp.setPen(QPen(QColor("#111"), 2))
        qp.setBrush(lg)
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
            if dark:
                bg = QLinearGradient(r.topLeft(), r.bottomLeft())
                bg.setColorAt(0, QColor("#4a4d53"))
                bg.setColorAt(1, QColor("#2a2c30"))
                qp.setBrush(bg)
            else:
                qp.setBrush(QColor("#dfe8ff") if name == "BT" else QColor("#ffffff"))
            qp.drawRoundedRect(r, 4, 4)
            if m.get("button_led"):
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor("#ff3b30") if i % 3 == 0 else QColor("#5a1a18"))
                qp.drawEllipse(QPointF(r.left() + 6, r.top() + 6), 2.6, 2.6)
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
            if m.get("knob_ring"):
                glow = QColor(m["knob_ring"])
                glow.setAlpha(110)
                qp.setPen(QPen(glow, 5))
                qp.setBrush(Qt.NoBrush)
                qp.drawEllipse(c, rad + 4, rad + 4)
            if m.get("knob_skirt"):
                sg = QLinearGradient(c.x(), c.y() - rad - 6, c.x(), c.y() + rad + 6)
                sg.setColorAt(0, QColor("#d9dde1"))
                sg.setColorAt(1, QColor("#7d838b"))
                qp.setPen(QPen(QColor("#000"), 1))
                qp.setBrush(sg)
                qp.drawEllipse(c, rad + 6, rad + 6)
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
                        _short2(txt, 18 if rad > 22 else 12))

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
                wg = QLinearGradient(r.topLeft(), r.bottomLeft())
                if note in self.active:
                    wg.setColorAt(0, QColor("#9db4ff"))
                    wg.setColorAt(1, QColor("#6f8ff5"))
                elif self.split_note is not None and note < self.split_note:
                    wg.setColorAt(0, QColor("#ead9b4"))        # zona da mão esquerda
                    wg.setColorAt(0.12, QColor("#f7ead0"))
                    wg.setColorAt(1, QColor("#e0cba0"))
                else:
                    wg.setColorAt(0, QColor("#e9eaec"))
                    wg.setColorAt(0.12, QColor("#fbfbfb"))
                    wg.setColorAt(1, QColor("#e2e3e6"))
                qp.setPen(QPen(QColor("#8d939b"), 1))
                qp.setBrush(wg)
                qp.drawRoundedRect(r.adjusted(0.5, 0, -0.5, 0), 2, 2)
                if note % 12 == 0:
                    qp.setPen(QColor("#777"))
                    qp.drawText(r.adjusted(0, 0, 0, -4), Qt.AlignHCenter | Qt.AlignBottom, note_name(note))
        for note, r, white in keys:
            if not white:
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(0, 0, 0, 70))
                qp.drawRoundedRect(r.adjusted(1, 0, 3, 3), 2, 2)       # sombra
                bg = QLinearGradient(r.topLeft(), r.bottomLeft())
                if note in self.active:
                    bg.setColorAt(0, QColor("#6f86e0"))
                    bg.setColorAt(1, QColor("#3e56b8"))
                else:
                    bg.setColorAt(0, QColor("#2c2c30"))
                    bg.setColorAt(0.85, QColor("#0b0b0d"))
                    bg.setColorAt(1, QColor("#303035"))
                qp.setPen(QPen(QColor("#000"), 1))
                qp.setBrush(bg)
                qp.drawRoundedRect(r, 2, 2)
                qp.setPen(QPen(QColor(255, 255, 255, 40), 1))
                qp.drawLine(QPointF(r.left() + 3, r.top() + 2), QPointF(r.left() + 3, r.bottom() - 8))
        self._paint_zones(qp, keys)

    def _paint_zones(self, qp, keys):
        """Teclado dividido: linha na divisão e o nome do timbre de cada mão sobre as teclas."""
        whites = [(n, r) for n, r, w in keys if w]
        if self.split_note is None or not whites:
            return
        left = [r for n, r in whites if n < self.split_note]
        right = [r for n, r in whites if n >= self.split_note]
        h = whites[0][1].height()
        if left and right:
            x = right[0].left()
            qp.setPen(QPen(QColor("#d9822b"), 3))
            qp.drawLine(QPointF(x, left[0].top()), QPointF(x, left[0].top() + h))
        qp.setFont(self._font(max(9.0, min(13.0, h * 0.075)), True))
        fm = qp.fontMetrics()
        for rects, text, color in ((left, "◀ " + self.zone_names[0], QColor(217, 130, 43, 225)),
                                   (right, self.zone_names[1] + " ▶", QColor(60, 90, 170, 215))):
            if not rects or len(text) < 4:
                continue
            zw = rects[-1].right() - rects[0].left()
            w = min(zw - 6, fm.horizontalAdvance(text) + 16)
            if w < 30:
                continue
            ph = max(16.0, h * 0.13)
            pill = QRectF(rects[0].left() + (zw - w) / 2, rects[0].top() + h * 0.64, w, ph)
            qp.setPen(Qt.NoPen)
            qp.setBrush(color)
            qp.drawRoundedRect(pill, ph / 2, ph / 2)
            qp.setPen(QColor("#ffffff"))
            qp.drawText(pill, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, int(w - 8)))


    # ------------------------------------------------------------------ decoração dos modelos grandes
    def _small_button(self, qp, r, led=None):
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor("#46494f"))
        g.setColorAt(1, QColor("#25272b"))
        qp.setPen(QPen(QColor("#0b0b0c"), 1))
        qp.setBrush(g)
        qp.drawRoundedRect(r, 3, 3)
        if led:
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(led))
            qp.drawEllipse(QPointF(r.left() + 5, r.top() + 5), 2.2, 2.2)

    def _label(self, qp, r, text, px=9, color="#b9bec5", bold=True, align=Qt.AlignCenter):
        qp.setFont(self._font(px, bold))
        qp.setPen(QColor(color))
        qp.drawText(r, align | Qt.AlignVCenter, text)

    def _grille(self, qp, r, radius):
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor("#1b1c1f"))
        g.setColorAt(1, QColor("#0c0c0e"))
        qp.fillPath(path, g)
        qp.setPen(QPen(QColor("#2f3236"), 2))
        qp.drawPath(path)
        qp.save()
        qp.setClipPath(path)
        qp.setPen(Qt.NoPen)
        qp.setBrush(QColor("#33363b"))
        y = r.top() + 7
        row = 0
        while y < r.bottom():
            x = r.left() + 6 + (4 if row % 2 else 0)
            while x < r.right():
                qp.drawEllipse(QPointF(x, y), 1.7, 1.7)
                x += 8
            y += 7
            row += 1
        hl = QLinearGradient(r.topLeft(), r.bottomLeft())
        hl.setColorAt(0, QColor(255, 255, 255, 22))
        hl.setColorAt(0.4, QColor(255, 255, 255, 0))
        qp.fillPath(path, hl)
        qp.restore()

    def _dial(self, qp, c, rad):
        dg = QLinearGradient(c.x(), c.y() - rad, c.x(), c.y() + rad)
        dg.setColorAt(0, QColor("#6a6e75"))
        dg.setColorAt(1, QColor("#1a1b1e"))
        qp.setPen(QPen(QColor("#000"), 1.5))
        qp.setBrush(dg)
        qp.drawEllipse(c, rad, rad)
        qp.setPen(QPen(QColor(255, 255, 255, 35), 1))
        for k in range(36):
            a = math.radians(k * 10)
            qp.drawLine(QPointF(c.x() + (rad - 5) * math.cos(a), c.y() + (rad - 5) * math.sin(a)),
                        QPointF(c.x() + rad * math.cos(a), c.y() + rad * math.sin(a)))
        cg = QLinearGradient(c.x(), c.y() - rad, c.x(), c.y() + rad)
        cg.setColorAt(0, QColor("#2b2d31"))
        cg.setColorAt(1, QColor("#3d4046"))
        qp.setBrush(cg)
        qp.drawEllipse(c, rad * 0.62, rad * 0.62)
        qp.setBrush(QColor("#111"))
        qp.drawEllipse(QPointF(c.x() + rad * 0.32, c.y() - rad * 0.22), rad * 0.1, rad * 0.1)

    def _decor_psr(self, qp, vw, vh):
        """Yamaha PSR-E473: corpo preto com centro elevado, alto-falantes grandes, painel central."""
        body = QPainterPath()
        body.moveTo(16, 70)
        body.quadTo(16, 44, 46, 42)
        body.lineTo(370, 42)
        body.cubicTo(400, 42, 400, 6, 440, 6)
        body.lineTo(960, 6)
        body.cubicTo(1000, 6, 1000, 42, 1030, 42)
        body.lineTo(1354, 42)
        body.quadTo(1384, 44, 1384, 70)
        body.lineTo(1384, 588)
        body.quadTo(1384, 598, 1370, 598)
        body.lineTo(30, 598)
        body.quadTo(16, 598, 16, 588)
        body.closeSubpath()
        g = QLinearGradient(0, 0, 0, vh)
        g.setColorAt(0, QColor("#2a2b2f"))
        g.setColorAt(0.5, QColor("#18191c"))
        g.setColorAt(1, QColor("#101113"))
        qp.fillPath(body, g)
        qp.setPen(QPen(QColor("#000"), 2))
        qp.drawPath(body)
        qp.setPen(QPen(QColor(255, 255, 255, 30), 1.5))
        qp.drawLine(QPointF(440, 9), QPointF(960, 9))
        # alto-falantes
        self._grille(qp, _r(44, 64, 300, 214), 30)
        self._grille(qp, _r(1056, 64, 300, 214), 30)
        # painel central
        panel = _r(372, 50, 656, 236)
        qp.setPen(QPen(QColor("#2d2f33"), 1.5))
        qp.setBrush(QColor("#1c1d20"))
        qp.drawRoundedRect(panel, 10, 10)
        f = self._font(26, True, "Arial Black")
        f.setLetterSpacing(QFont.PercentageSpacing, 140)
        qp.setFont(f)
        qp.setPen(QColor("#eceff2"))
        qp.drawText(_r(560, 12, 280, 40), Qt.AlignCenter, "YAMAHA")
        self._label(qp, _r(420, 64, 150, 14), "LIVE CONTROL")
        # botões do lado esquerdo do visor (categorias/funções)
        for row in range(2):
            for col in range(4):
                r = _r(404 + col * 46, 160 + row * 50, 38, 24)
                self._small_button(qp, r, "#ff3b30" if (row + col) % 3 == 0 else None)
        for k, t in enumerate(("METRONOME", "TEMPO/TAP", "FUNCTION", "PORTABLE")):
            self._label(qp, _r(396 + k * 46, 186, 54, 12), t, 7, "#8d939b", False)
        # botões do lado direito (voz, estilo, música e teclado numérico)
        for row in range(3):
            for col in range(4):
                self._small_button(qp, _r(840 + col * 44, 66 + row * 34, 36, 22))
        self._label(qp, _r(836, 168, 180, 12), "VOICE   STYLE   SONG   GROOVE", 7, "#8d939b", False)
        self._dial(qp, QPointF(892, 232), 34)
        self._label(qp, _r(942, 220, 80, 24), "DIAL", 8, "#8d939b")
        # faixa inferior: controles de estilo, botão azul e pads de quick sampling
        qp.setPen(QPen(QColor("#2d2f33"), 1))
        qp.drawLine(QPointF(40, 298), QPointF(1360, 298))
        blue = _r(290, 314, 46, 34)
        bg = QLinearGradient(blue.topLeft(), blue.bottomLeft())
        bg.setColorAt(0, QColor("#4fb6ff"))
        bg.setColorAt(1, QColor("#1677d6"))
        qp.setPen(QPen(QColor("#0b3a66"), 1))
        qp.setBrush(bg)
        qp.drawRoundedRect(blue, 4, 4)
        self._label(qp, _r(270, 350, 86, 12), "MEGA BOOST", 7, "#8d939b", False)
        self._label(qp, _r(352, 300, 496, 14), "STYLE CONTROL", 8, "#8d939b")
        self._label(qp, _r(1078, 350, 274, 12), "QUICK SAMPLING", 7, "#8d939b", False)
        # roda de pitch e nome do modelo
        wheel = _r(36, 410, 46, 150)
        qp.setPen(QPen(QColor("#000"), 1))
        qp.setBrush(QColor("#0a0a0b"))
        qp.drawRoundedRect(wheel, 8, 8)
        wg = QLinearGradient(wheel.topLeft(), wheel.bottomLeft())
        wg.setColorAt(0, QColor("#2a2b2e"))
        wg.setColorAt(0.5, QColor("#55585e"))
        wg.setColorAt(1, QColor("#2a2b2e"))
        qp.setBrush(wg)
        qp.drawRoundedRect(wheel.adjusted(10, 12, -10, -12), 5, 5)
        self._label(qp, _r(20, 392, 80, 14), "PITCH BEND", 8, "#8d939b")
        f = self._font(24, True, "Arial")
        f.setItalic(True)
        qp.setFont(f)
        qp.setPen(QColor("#d9dde1"))
        qp.drawText(_r(1100, 256, 250, 36), Qt.AlignRight | Qt.AlignVCenter, "PSR-E473")

    def _decor_vr(self, qp, vw, vh):
        """Roland V-Combo VR-730: laterais de madeira, painel em seções, drawbars e visor azul."""
        g = QLinearGradient(0, 0, 0, vh)
        g.setColorAt(0, QColor("#1f1f22"))
        g.setColorAt(1, QColor("#0b0b0d"))
        qp.setPen(QPen(QColor("#000"), 2))
        qp.setBrush(g)
        qp.drawRect(_r(0, 0, vw, vh))
        for x in (0, vw - 30):                                  # laterais de madeira
            wg = QLinearGradient(x, 0, x + 30, 0)
            wg.setColorAt(0, QColor("#4b2810"))
            wg.setColorAt(0.5, QColor("#8a5026"))
            wg.setColorAt(1, QColor("#4b2810"))
            qp.fillRect(_r(x, 0, 30, vh), wg)
            qp.setPen(QPen(QColor(40, 18, 6, 90), 1))
            for k in range(9):
                qp.drawLine(QPointF(x + 4 + k * 3, 0), QPointF(x + 2 + k * 3.2, vh))
        # painel superior escovado
        panel = _r(30, 0, vw - 60, 250)
        pg = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        pg.setColorAt(0, QColor("#2a2b2f"))
        pg.setColorAt(1, QColor("#1a1b1e"))
        qp.fillRect(panel, pg)
        qp.setPen(QPen(QColor(255, 255, 255, 10), 1))
        for y in range(4, 248, 3):
            qp.drawLine(QPointF(32, y), QPointF(vw - 32, y))
        qp.setPen(QPen(QColor("#3c3e43"), 1))
        for x in (210, 486, 776, 1102, 1340):                   # divisões das seções
            qp.drawLine(QPointF(x, 14), QPointF(x, 236))
        f = self._font(30, True, "Arial Black")
        f.setItalic(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 96)
        qp.setFont(f)
        qp.setPen(QColor("#f2f2f2"))
        qp.drawText(_r(46, 10, 160, 44), Qt.AlignLeft | Qt.AlignVCenter, "Roland")
        self._dial(qp, QPointF(120, 128), 30)                   # VOLUME
        self._label(qp, _r(70, 162, 100, 14), "VOLUME", 8, "#9aa0a8")
        for k in range(2):
            self._small_button(qp, _r(60 + k * 66, 188, 54, 26), "#ff3b30" if k == 0 else None)
        self._label(qp, _r(46, 218, 150, 12), "FAVORITE      KEY TRANSPOSE", 7, "#7d838b", False)
        self._label(qp, _r(220, 14, 256, 14), "ORGAN / EFFECTS", 9, "#aeb3b9")
        # harmonic bars
        self._label(qp, _r(496, 14, 270, 14), "HARMONIC BAR", 9, "#aeb3b9")
        colors = ("#7a4622", "#7a4622", "#f2f2f2", "#f2f2f2", "#111111", "#f2f2f2", "#111111",
                  "#111111", "#f2f2f2")
        levels = (8, 8, 8, 4, 0, 0, 0, 2, 0)
        for j in range(9):
            x = 512 + j * 28
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor("#050506"))
            qp.drawRoundedRect(_r(x - 4, 36, 8, 190), 3, 3)
            hy = 40 + 150 * levels[j] / 8
            hg = QLinearGradient(x - 11, hy, x + 11, hy)
            base = QColor(colors[j])
            hg.setColorAt(0, base.darker(130))
            hg.setColorAt(0.5, base.lighter(115))
            hg.setColorAt(1, base.darker(130))
            qp.setPen(QPen(QColor("#000"), 1))
            qp.setBrush(hg)
            qp.drawRoundedRect(_r(x - 11, hy, 22, 34), 3, 3)
        # centro: visor + dial
        self._dial(qp, QPointF(1060, 98), 34)
        f = self._font(15, True, "Arial")
        qp.setFont(f)
        qp.setPen(QColor("#e8e8e8"))
        qp.drawText(_r(790, 168, 240, 24), Qt.AlignCenter, "V-Combo  VR-730")
        for k in range(4):
            self._small_button(qp, _r(800 + k * 58, 202, 48, 24), "#ff3b30" if k == 1 else None)
        self._label(qp, _r(1112, 14, 228, 14), "PART / SCENE", 9, "#aeb3b9")
        self._label(qp, _r(1348, 10, 230, 14), "REGISTRATION", 9, "#aeb3b9")
        # alavanca de pitch/modulação
        lever = _r(44, 280, 46, 80)
        qp.setPen(QPen(QColor("#000"), 1))
        qp.setBrush(QColor("#0a0a0b"))
        qp.drawRoundedRect(lever, 6, 6)
        lg = QLinearGradient(lever.topLeft(), lever.topRight())
        lg.setColorAt(0, QColor("#55585e"))
        lg.setColorAt(1, QColor("#2a2b2e"))
        qp.setBrush(lg)
        qp.drawRoundedRect(_r(58, 296, 18, 50), 4, 4)
        self._label(qp, _r(36, 262, 64, 14), "BENDER", 8, "#8d939b")


def _short2(text, n=18):
    lines = text.split("\n")
    return "\n".join(t if len(t) <= n else t[: n - 1] + "…" for t in lines)
