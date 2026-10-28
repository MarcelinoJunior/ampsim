"""Fader de mesa de som para a barra de baixo (aba Faders / Pads): trilho escuro com marcas, cursor
retangular cinza com a linha de pega (o mesmo desenho da tela remota) e, no Master e no Compressor, o
medidor aceso dentro do trilho (nível da saída de baixo para cima; redução nos picos de cima para baixo).

O cursor é baixo (12 px) e vazado no meio: as duas metades ficam dos lados do trilho e o trilho (com o
medidor) aparece através dele, então o medidor nunca fica escondido, em qualquer posição do fader."""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSlider

from .theme import C

CAP_W, CAP_H = 30, 12
SLOT_W = 10
DECAY = 0.03                 # quanto o medidor cai por atualização (~33 ms): mesma retenção do Meter
GR_MAX_DB = 20.0             # redução do compressor que enche o trilho


def level_from_peak(peak):
    """Pico linear -> 0..1 numa escala de -60 a 0 dBFS (como os outros medidores)."""
    db = 20 * math.log10(peak) if peak > 1e-6 else -120.0
    return min(max((db + 60.0) / 60.0, 0.0), 1.0)


def level_from_gr(gr_db):
    return min(max(gr_db / GR_MAX_DB, 0.0), 1.0)


class DeskFader(QSlider):
    """QSlider vertical 0..100 desenhado como fader de mesa.

    inverted: 0 com o cursor EM CIMA e 100 embaixo (Compressor: quanto mais para baixo, mais compressão).
    meter: None, "level" (nível da saída, verde -> amarelo -> vermelho, de baixo para cima) ou "gr"
    (redução do compressor, laranja, de cima para baixo)."""

    def __init__(self, inverted=False, meter=None, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setRange(0, 100)
        self.inverted = inverted
        self.meter = meter
        self.level = 0.0
        self.muted = False
        self._grab = None
        self.setInvertedControls(inverted)           # roda do mouse para cima = cursor sobe
        self.setMinimumSize(CAP_W + 6, 48)
        self.setFocusPolicy(Qt.NoFocus)

    # ------------------------------------------------------------------ estado
    def set_meter(self, t):
        """t 0..1 (já na escala do medidor). Sobe na hora, desce aos poucos."""
        t = min(max(float(t), 0.0), 1.0)
        new = max(t, self.level - DECAY)
        if abs(new - self.level) > 1e-3 or (new == 0.0) != (self.level == 0.0):
            self.level = new
            self.update()

    def set_muted(self, on):
        if on != self.muted:
            self.muted = on
            self.update()

    # ------------------------------------------------------------------ geometria
    def _span(self):
        return max(1.0, self.height() - CAP_H - 2.0)

    def _cap_top(self, v=None):
        t = (self.value() if v is None else v) / 100.0
        return 1.0 + (t if self.inverted else 1.0 - t) * self._span()

    def _value_at(self, cap_top):
        t = min(max((cap_top - 1.0) / self._span(), 0.0), 1.0)
        return round((t if self.inverted else 1.0 - t) * 100)

    # ------------------------------------------------------------------ mouse (arrasta o cursor; clicar no trilho pula)
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not self.isEnabled():
            return super().mousePressEvent(e)
        y = e.position().y()
        top = self._cap_top()
        self._grab = y - top if top - 3 <= y <= top + CAP_H + 3 else CAP_H / 2
        self.setSliderDown(True)
        self.setValue(self._value_at(y - self._grab))
        e.accept()

    def mouseMoveEvent(self, e):
        if self._grab is None:
            return super().mouseMoveEvent(e)
        self.setValue(self._value_at(e.position().y() - self._grab))
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._grab is None:
            return super().mouseReleaseEvent(e)
        self._grab = None
        self.setSliderDown(False)
        e.accept()

    # ------------------------------------------------------------------ desenho
    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        on = self.isEnabled()
        cx = w / 2.0
        y0, y1 = CAP_H / 2.0, h - CAP_H / 2.0               # o trilho vai de meio cursor a meio cursor
        slot = QRectF(cx - SLOT_W / 2.0, y0, SLOT_W, y1 - y0)
        # marcas de 10 em 10% dos dois lados
        qp.setPen(QPen(QColor("#3a4d6e"), 1))
        for i in range(11):
            y = round(y0 + (y1 - y0) * i / 10.0) + 0.5
            qp.drawLine(int(cx - SLOT_W / 2 - 7), int(y), int(cx - SLOT_W / 2 - 3), int(y))
            qp.drawLine(int(cx + SLOT_W / 2 + 3), int(y), int(cx + SLOT_W / 2 + 7), int(y))
        # trilho
        qp.setPen(QPen(QColor("#1e2d46"), 1))
        qp.setBrush(QColor("#04070d"))
        qp.drawRoundedRect(slot, 4, 4)
        inner = slot.adjusted(1.5, 1.5, -1.5, -1.5)
        if self.meter == "level" and self.level > 0:
            hh = inner.height() * self.level
            r = QRectF(inner.left(), inner.bottom() - hh, inner.width(), hh)
            g = QLinearGradient(0, inner.bottom(), 0, inner.top())
            g.setColorAt(0.0, QColor(C["green"]))
            g.setColorAt(0.75, QColor(C["green"]))
            g.setColorAt(0.85, QColor(C["yellow"]))
            g.setColorAt(1.0, QColor(C["red"]))
            qp.setPen(Qt.NoPen)
            qp.setBrush(g)
            qp.drawRoundedRect(r, 2, 2)
        elif self.meter == "gr" and self.level > 0:
            hh = inner.height() * self.level
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor("#f2994a"))
            qp.drawRoundedRect(QRectF(inner.left(), inner.top(), inner.width(), hh), 2, 2)
        elif self.meter is None and on:
            # posição do fader (como o azul da tela remota), de baixo até o cursor
            top = self._cap_top() + CAP_H / 2.0
            if inner.bottom() > top:
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(C["red"] if self.muted else C["accent"]))
                qp.drawRoundedRect(QRectF(inner.left(), top, inner.width(), inner.bottom() - top), 2, 2)
        # cursor: retângulo cinza claro com a linha de pega (vermelho quando mudo), vazado em cima do trilho
        cap = QRectF(cx - CAP_W / 2.0, self._cap_top(), CAP_W, CAP_H)
        g = QLinearGradient(0, cap.top(), 0, cap.bottom())
        if self.muted:
            g.setColorAt(0.0, QColor("#ffd9dd"))
            g.setColorAt(0.45, QColor("#f08d98"))
            g.setColorAt(1.0, QColor("#c8505d"))
            border, grip = QColor("#ff8a96"), QColor("#5a1220")
        else:
            g.setColorAt(0.0, QColor("#fbfcfe"))
            g.setColorAt(0.45, QColor("#c9cfd9"))
            g.setColorAt(1.0, QColor("#9da6b5"))
            border = QColor("#8fbaff") if self.isSliderDown() else QColor("#5d6778")
            grip = QColor("#1d2433")
        if not on:
            qp.setOpacity(0.35)
        side = (CAP_W - SLOT_W) / 2.0 - 1.0                # largura de cada metade (fora do trilho)
        halves = (QRectF(cap.left(), cap.top(), side, CAP_H), QRectF(cap.right() - side, cap.top(), side, CAP_H))
        qp.setPen(QPen(QColor(0, 0, 0, 120), 1))
        qp.setBrush(Qt.NoBrush)
        for r in halves:
            qp.drawRoundedRect(r.translated(0, 1.5), 2, 2)                # sombra
        qp.setPen(QPen(border, 1))
        qp.setBrush(g)
        for r in halves:
            qp.drawRoundedRect(r, 2, 2)
        # moldura fina por cima do trilho ligando as metades (o meio fica vazado: o medidor aparece)
        qp.setPen(QPen(border, 1))
        xl, xr = halves[0].right(), halves[1].left()
        qp.drawLine(int(xl), int(cap.top()), int(xr), int(cap.top()))
        qp.drawLine(int(xl), int(cap.bottom()), int(xr), int(cap.bottom()))
        qp.setPen(QPen(grip, 2))
        mid = cap.center().y()
        for r in halves:
            qp.drawLine(int(r.left() + 2), int(mid), int(r.right() - 2), int(mid))
