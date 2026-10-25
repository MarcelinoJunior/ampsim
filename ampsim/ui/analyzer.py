"""Curvas de EQ e analisador de espectro (RTA) para as abas de guitarra/baixo e o pad contínuo."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..audio.engine import RTA_N
from ..dsp.filters import biquad
from ..dsp.padeq import DEFAULT_PAD_EQ, PAD_AMB_PARAMS, PAD_EQ_PARAMS, PAD_EQ_PRESETS, VOICINGS
from ..dsp.params import EQ_FREQS
from .widgets import Knob

F_LO, F_HI = 20.0, 20000.0
GRID_F = (50, 100, 200, 500, 1000, 2000, 5000, 10000)


def _fx(f, x0, w):
    return x0 + w * math.log(f / F_LO) / math.log(F_HI / F_LO)


def _fpos(x, x0, w):
    return F_LO * (F_HI / F_LO) ** min(max((x - x0) / w, 0.0), 1.0)


def _bq_mag(c, z):
    b0, b1, b2, a1, a2 = c
    return np.abs((b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z))


class Spectrum:
    """FFT com janela de Hann, suavizada em ~1/6 de oitava sobre eixo log; decaimento suave."""

    def __init__(self, fs, n_points=160):
        self.fs = fs
        self.freqs = np.geomspace(F_LO, F_HI, n_points)
        self.win = np.hanning(RTA_N)
        self.norm = 2.0 / self.win.sum()
        bins = np.fft.rfftfreq(RTA_N, 1.0 / fs)
        lo = np.searchsorted(bins, self.freqs * 2 ** (-1 / 12))
        hi = np.maximum(np.searchsorted(bins, self.freqs * 2 ** (1 / 12)), lo + 1)
        self.edges = np.stack([lo, hi], axis=1)
        self.level = np.full(n_points, -120.0)

    def update(self, ring, pos):
        x = np.roll(ring, -pos) * self.win
        mag = np.abs(np.fft.rfft(x)) * self.norm
        p = mag * mag
        c = np.concatenate(([0.0], np.cumsum(p)))
        lo, hi = self.edges[:, 0], np.minimum(self.edges[:, 1], len(p))
        band = (c[hi] - c[lo]) / np.maximum(hi - lo, 1)
        db = 10.0 * np.log10(band + 1e-14)
        # sobe na hora, desce devagar (fica legível)
        self.level = np.where(db > self.level, db, self.level - 1.2)
        return self.level


class EqGraph(QWidget):
    """Grade log de 20 Hz a 20 kHz com curva(s) de EQ e, opcionalmente, o RTA por trás.

    Com `bands` (lista de frequências), cada banda vira um ponto que se arrasta na vertical.
    """

    bandMoved = Signal(int, float)          # índice da banda, ganho em dB

    def __init__(self, accent="#e8a33d", db_range=15.0, bands=(), parent=None):
        super().__init__(parent)
        self.accent = QColor(accent)
        self.db_range = db_range
        self.bands = list(bands)
        self.gains = [0.0] * len(self.bands)
        self.curve = None                   # dB nos pontos self.freqs
        self.freqs = np.geomspace(F_LO, F_HI, 240)
        self.rta_out = None
        self.rta_in = None
        self._drag = None
        self.setMinimumHeight(110)
        self.setMouseTracking(True)

    def _area(self):
        return QRectF(34, 6, self.width() - 42, self.height() - 22)

    def _y(self, db, r):
        return r.center().y() - db / self.db_range * r.height() / 2

    def _y_rta(self, db, r):                 # RTA: 0 dBFS em cima, -96 embaixo
        return r.top() + min(max(-db / 96.0, 0.0), 1.0) * r.height()

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.fillRect(self.rect(), QColor("#15171c"))
        r = self._area()
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        qp.setFont(f)
        qp.setPen(QPen(QColor("#2a2e36"), 1))
        for g in GRID_F:
            x = _fx(g, r.left(), r.width())
            qp.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        for d in (-12, -6, 0, 6, 12):
            if abs(d) <= self.db_range:
                y = self._y(d, r)
                qp.setPen(QPen(QColor("#3a404b") if d == 0 else QColor("#24272e"), 1))
                qp.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                qp.setPen(QColor("#7d8590"))
                qp.drawText(QRectF(0, y - 7, 30, 14), Qt.AlignRight | Qt.AlignVCenter, f"{d:+d}" if d else "0")
        qp.setPen(QColor("#7d8590"))
        for g in GRID_F:
            x = _fx(g, r.left(), r.width())
            qp.drawText(QRectF(x - 20, r.bottom() + 2, 40, 12), Qt.AlignCenter,
                        f"{g // 1000}k" if g >= 1000 else str(g))
        if self.rta_out is not None or self.rta_in is not None:
            qp.setPen(QColor("#5f6670"))             # escala do RTA (dBFS) à direita
            for d in (-24, -48, -72):
                y = self._y_rta(d, r)
                qp.drawText(QRectF(r.right() - 60, y - 13, 56, 12), Qt.AlignRight, f"{d} dBFS")
        for data, color, fill in ((self.rta_in, QColor(150, 160, 175, 150), None),
                                  (self.rta_out, QColor(self.accent), QColor(self.accent.red(), self.accent.green(),
                                                                            self.accent.blue(), 45))):
            if data is None:
                continue
            freqs, lv = data
            path = QPainterPath()
            for k, (fq, d) in enumerate(zip(freqs, lv)):
                pt = QPointF(_fx(fq, r.left(), r.width()), self._y_rta(d, r))
                path.lineTo(pt) if k else path.moveTo(pt)
            if fill is not None:
                area = QPainterPath(path)
                area.lineTo(r.right(), r.bottom())
                area.lineTo(r.left(), r.bottom())
                area.closeSubpath()
                qp.fillPath(area, fill)
            qp.setPen(QPen(color, 1.2))
            qp.drawPath(path)
        if self.curve is not None:
            path = QPainterPath()
            for k, (fq, d) in enumerate(zip(self.freqs, self.curve)):
                y = min(max(self._y(d, r), r.top()), r.bottom())
                pt = QPointF(_fx(fq, r.left(), r.width()), y)
                path.lineTo(pt) if k else path.moveTo(pt)
            qp.setPen(QPen(QColor("#f2f2f2"), 2))
            qp.drawPath(path)
        for i, (fq, g) in enumerate(zip(self.bands, self.gains)):
            c = QPointF(_fx(fq, r.left(), r.width()), self._y(g, r))
            qp.setPen(QPen(QColor("#111"), 1))
            qp.setBrush(self.accent if self._drag != i else QColor("#ffffff"))
            qp.drawEllipse(c, 6, 6)

    def _band_at(self, pos):
        r = self._area()
        best, bd = None, 18.0
        for i, fq in enumerate(self.bands):
            d = abs(pos.x() - _fx(fq, r.left(), r.width()))
            if d < bd:
                best, bd = i, d
        return best

    def mousePressEvent(self, e):
        self._drag = self._band_at(e.position())
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            i = self._band_at(e.position())
            self.setCursor(Qt.SizeVerCursor if i is not None else Qt.ArrowCursor)
            return
        r = self._area()
        g = (r.center().y() - e.position().y()) / (r.height() / 2) * self.db_range
        g = round(min(max(g, -12.0), 12.0) * 2) / 2
        self.bandMoved.emit(self._drag, g)

    def mouseReleaseEvent(self, _):
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        i = self._band_at(e.position())
        if i is not None:
            self.bandMoved.emit(i, 0.0)


class TrackAnalyzer(QFrame):
    """Guitarra/baixo: EQ gráfico (o pedal Equalizador, arrastando os pontos) + RTA entrada/saída."""

    def __init__(self, page, accent):
        super().__init__()
        self.page = page
        self.setObjectName("effect")
        self.spec_in = self.spec_out = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 6)
        lay.setSpacing(3)
        head = QHBoxLayout()
        title = QLabel("EQ gráfico e analisador (RTA)")
        title.setObjectName("fxtitle")
        head.addWidget(title)
        head.addSpacing(10)
        self.show_eq = QCheckBox("Curva do EQ")
        self.show_eq.setChecked(True)
        self.show_rta = QCheckBox("RTA saída")
        self.show_rta.setChecked(True)
        self.show_in = QCheckBox("RTA entrada (sinal seco)")
        for w in (self.show_eq, self.show_rta, self.show_in):
            w.setFocusPolicy(Qt.NoFocus)
            w.toggled.connect(self._options)
            head.addWidget(w)
        head.addStretch(1)
        self.hint = QLabel("Arraste os pontos para mexer no Equalizador · duplo-clique zera a banda")
        self.hint.setObjectName("small")
        head.addWidget(self.hint)
        self.float_btn = QPushButton("⇱ Janela")
        self.float_btn.setToolTip("Abrir o analisador numa janela separada (feche para voltar aqui)")
        self.float_btn.setFocusPolicy(Qt.NoFocus)
        self.float_btn.clicked.connect(self._toggle_window)
        head.addWidget(self.float_btn)
        lay.addLayout(head)
        self.graph = EqGraph(accent, 15.0, EQ_FREQS)
        self.graph.bandMoved.connect(self._band_moved)
        lay.addWidget(self.graph, 1)
        self.dialog = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    def track(self):
        return self.page.track()

    def _options(self):
        self.refresh()

    def _band_moved(self, i, g):
        page = self.page
        if not self.track().values["eq"]["on"]:
            self.track().set_on("eq", True)         # mexeu na curva: liga o Equalizador
        self.track().set_param("eq", f"b{i}", g)
        for p in page.panels:
            if p.eff.key == "eq":
                p.refresh()
        self.refresh()

    def refresh(self):
        v = self.track().values["eq"]
        fs = self.page.engine.fs
        g = self.graph
        g.gains = [v[f"b{i}"] for i in range(len(EQ_FREQS))]
        if self.show_eq.isChecked():
            z = np.exp(-2j * np.pi * g.freqs / fs)
            h = np.ones_like(g.freqs)
            for i, fq in enumerate(EQ_FREQS):
                h = h * _bq_mag(biquad("peak", fs, fq, g.gains[i], q=1.0), z)
            g.curve = 20 * np.log10(h) + (v["level"] if v["on"] else 0.0)
            if not v["on"]:
                g.curve = g.curve * 0.0
        else:
            g.curve = None
        g.update()

    def _tick(self):
        if not self.isVisible():
            if self.page.engine.rta_track == self.page.name:
                self.page.engine.rta_track = None
            return
        v = self.track().values["eq"]
        sig = tuple(sorted(v.items()))
        if sig != getattr(self, "_eq_sig", None):    # knobs do pedal mudaram: redesenha a curva
            self._eq_sig = sig
            self.refresh()
        eng = self.page.engine
        want = self.isVisible() and (self.show_rta.isChecked() or self.show_in.isChecked())
        if want:
            eng.rta_track = self.page.name
        elif eng.rta_track == self.page.name:
            eng.rta_track = None
        if not want or eng.stream is None:
            if self.graph.rta_out is not None or self.graph.rta_in is not None:
                self.graph.rta_out = self.graph.rta_in = None
                self.graph.update()
            return
        if self.spec_out is None or self.spec_out.fs != eng.fs:
            self.spec_out, self.spec_in = Spectrum(eng.fs), Spectrum(eng.fs)
        g = self.graph
        g.rta_out = ((self.spec_out.freqs, self.spec_out.update(eng.rta_out, eng.rta_pos_out))
                     if self.show_rta.isChecked() else None)
        g.rta_in = ((self.spec_in.freqs, self.spec_in.update(eng.rta_in, eng.rta_pos_in))
                    if self.show_in.isChecked() else None)
        g.update()

    # ---------------------------------------------------------------- janela separada
    def _toggle_window(self):
        if self.dialog is None:
            self._dock_parent = self.parentWidget()
            self._dock_layout = self._dock_parent.layout()
            self._dock_index = self._dock_layout.indexOf(self)
            d = QDialog(self.window())
            d.setWindowTitle("EQ e RTA — " + {"guitar": "Guitarra", "bass": "Baixo"}.get(self.page.name, ""))
            d.resize(900, 420)
            QVBoxLayout(d).addWidget(self)
            d.finished.connect(lambda _: self._dock())
            self.dialog = d
            self.float_btn.setText("⇲ Encaixar")
            d.show()
            self.show()
        else:
            self.dialog.close()

    def _dock(self):
        d, self.dialog = self.dialog, None
        self._dock_layout.insertWidget(self._dock_index, self, 1)
        self.float_btn.setText("⇱ Janela")
        self.show()
        d.deleteLater()


class PadEqDialog(QDialog):
    """Botão direito no pad B: EQ (tirar harmônicos em cima/embaixo), ambiente e tom do pad contínuo."""

    def __init__(self, inst, accent, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.setWindowTitle("Pad contínuo — equalizador e ambiente")
        self.resize(760, 470)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.on = QCheckBox("EQ ligado")
        self.on.setFocusPolicy(Qt.NoFocus)
        self.on.toggled.connect(lambda v: self._set(on=v))
        top.addWidget(self.on)
        top.addSpacing(12)
        top.addWidget(QLabel("Atalhos:"))
        self.preset = QComboBox()
        self.preset.addItems(list(PAD_EQ_PRESETS))
        self.preset.activated.connect(self._preset)
        top.addWidget(self.preset)
        top.addSpacing(12)
        top.addWidget(QLabel("Notas do pad:"))
        self.voicing = QComboBox()
        self.voicing.addItems(list(VOICINGS))
        self.voicing.setToolTip("Quais notas o pad toca a partir do tom escolhido.\n"
                                "“sem grave” ajuda quando o baixo/teclado já ocupa a região grave.")
        self.voicing.activated.connect(lambda _: self._set(voicing=self.voicing.currentText()))
        top.addWidget(self.voicing)
        top.addStretch(1)
        lay.addLayout(top)
        self.graph = EqGraph(accent, 15.0)
        self.graph.setMinimumHeight(170)
        lay.addWidget(self.graph, 1)
        self.knobs = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        for row, params, caption in ((0, PAD_EQ_PARAMS, "Equalizador"), (1, PAD_AMB_PARAMS, "Ambiente")):
            lab = QLabel(caption)
            lab.setObjectName("fxtitle")
            grid.addWidget(lab, row, 0)
            for col, p in enumerate(params):
                k = Knob(p, accent, size="small")
                k.valueChanged.connect(lambda v, key=p.key: self._set(**{key: v}))
                self.knobs[p.key] = k
                grid.addWidget(k, row, col + 1)
        grid.setColumnStretch(len(PAD_EQ_PARAMS) + 1, 1)
        lay.addLayout(grid)
        bottom = QHBoxLayout()
        tip = QLabel("Corte de graves/agudos tiram harmônicos embaixo/em cima (24 dB/oitava). "
                     "Vale para todos os tons do banco B.")
        tip.setObjectName("small")
        bottom.addWidget(tip, 1)
        reset = QPushButton("Restaurar padrão")
        reset.clicked.connect(self._reset)
        bottom.addWidget(reset)
        close = QPushButton("Fechar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self.refresh()

    def _set(self, **values):
        self.inst.set_pad_eq(**values)
        self._curve()

    def _preset(self, _):
        v = {p.key: p.default for p in PAD_EQ_PARAMS}
        v.update(PAD_EQ_PRESETS[self.preset.currentText()])
        v["on"] = True
        self.inst.set_pad_eq(**v)
        self.refresh()

    def _reset(self):
        self.inst.set_pad_eq(**DEFAULT_PAD_EQ)
        self.refresh()

    def refresh(self):
        pe = self.inst.pad_eq
        self.on.blockSignals(True)
        self.on.setChecked(bool(pe["on"]))
        self.on.blockSignals(False)
        self.voicing.setCurrentText(pe["voicing"])
        for key, k in self.knobs.items():
            k.setValue(pe[key])
        self._curve()

    def _curve(self):
        eq = self.inst.engine.pad_eq
        g = self.graph
        g.curve = eq.response(g.freqs) if self.inst.pad_eq["on"] else np.zeros_like(g.freqs)
        g.update()
