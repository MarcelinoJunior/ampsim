"""Painéis de efeito, painel do synth e página de cada trilha."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import storage
from ..dsp.params import CAB_IR_INDEX, EFFECTS, SYNTH_GROUPS, TRACK_PARAMS
from ..dsp.synth import SYNTH_PRESETS
from ..presets import FACTORY
from .widgets import Knob, LedButton, Meter

KNOBS_PER_ROW = 4


def _choice_box(param, on_change):
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(2, 0, 2, 0)
    lay.setSpacing(2)
    lab = QLabel(param.label)
    lab.setObjectName("small")
    combo = QComboBox()
    combo.setFocusPolicy(Qt.NoFocus)
    combo.addItems(param.choices)
    combo.currentIndexChanged.connect(lambda i: on_change(float(i)))
    lay.addWidget(lab)
    lay.addWidget(combo)
    return box, combo


class EffectPanel(QFrame):
    def __init__(self, eff, accent, page):
        super().__init__()
        self.eff = eff
        self.page = page
        self.setObjectName("effect")
        self.controls = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.led = LedButton(accent)
        self.led.toggled.connect(self._toggled)
        title = QLabel(eff.title)
        title.setObjectName("fxtitle")
        head.addWidget(self.led)
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(2)
        row = col = 0
        for p in eff.params:
            if p.is_choice:
                w, combo = _choice_box(p, lambda v, k=p.key: self._changed(k, v))
                self.controls[p.key] = combo
                if col:
                    row, col = row + 1, 0
                grid.addWidget(w, row, 0, 1, KNOBS_PER_ROW)
                row += 1
                continue
            knob = Knob(p, accent)
            knob.valueChanged.connect(lambda v, k=p.key: self._changed(k, v))
            self.controls[p.key] = knob
            grid.addWidget(knob, row, col)
            col += 1
            if col == KNOBS_PER_ROW:
                row, col = row + 1, 0
        lay.addLayout(grid)

        if eff.key == "cab":
            irrow = QHBoxLayout()
            btn = QPushButton("Carregar IR…")
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(self._load_ir)
            self.ir_label = QLabel("")
            self.ir_label.setObjectName("small")
            self.ir_label.setWordWrap(True)
            irrow.addWidget(btn)
            irrow.addWidget(self.ir_label, 1)
            lay.addLayout(irrow)
        lay.addStretch(1)

    def track(self):
        return self.page.track()

    def _toggled(self, on):
        self.track().set_on(self.eff.key, on)

    def _changed(self, key, value):
        self.track().set_param(self.eff.key, key, value)

    def _load_ir(self):
        path, _ = QFileDialog.getOpenFileName(self, "Escolher impulso de gabinete (IR)", "",
                                              "Arquivos WAV (*.wav)")
        if not path:
            return
        t = self.track()
        if not t.load_ir_file(path):
            QMessageBox.warning(self, "IR", f"Não foi possível ler o arquivo:\n{t.ir_error}")
            return
        t.set_on("cab", True)
        t.set_param("cab", "model", CAB_IR_INDEX)
        self.refresh()

    def refresh(self):
        vals = self.track().values[self.eff.key]
        self.led.blockSignals(True)
        self.led.setChecked(bool(vals["on"]))
        self.led.blockSignals(False)
        for key, w in self.controls.items():
            w.blockSignals(True)
            if isinstance(w, QComboBox):
                w.setCurrentIndex(int(round(vals[key])))
            else:
                w.setValue(vals[key])
            w.blockSignals(False)
        if self.eff.key == "cab":
            t = self.track()
            txt = os.path.basename(t.ir_path) if t.ir_path else "nenhuma IR carregada"
            if t.ir_error:
                txt = f"erro: {t.ir_error}"
            self.ir_label.setText(txt)


class SynthPanel(QFrame):
    def __init__(self, engine, accent):
        super().__init__()
        self.engine = engine
        self.setObjectName("effect")
        self.controls = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        head = QHBoxLayout()
        title = QLabel("Synth de Pads")
        title.setObjectName("fxtitle")
        head.addWidget(title)
        head.addSpacing(12)
        head.addWidget(QLabel("Som:"))
        self.preset = QComboBox()
        self.preset.setFocusPolicy(Qt.NoFocus)
        self.preset.addItems(list(SYNTH_PRESETS))
        self.preset.activated.connect(self._apply_preset)
        head.addWidget(self.preset)
        head.addStretch(1)
        outer.addLayout(head)
        groups = QHBoxLayout()
        for gname, params in SYNTH_GROUPS:
            box = QVBoxLayout()
            lab = QLabel(gname)
            lab.setObjectName("small")
            box.addWidget(lab)
            grid = QGridLayout()
            grid.setSpacing(2)
            row = col = 0
            for p in params:
                if p.is_choice:
                    w, combo = _choice_box(p, lambda v, k=p.key: self._changed(k, v))
                    self.controls[p.key] = combo
                    grid.addWidget(w, row, col)
                else:
                    knob = Knob(p, accent)
                    knob.valueChanged.connect(lambda v, k=p.key: self._changed(k, v))
                    self.controls[p.key] = knob
                    grid.addWidget(knob, row, col)
                col += 1
                if col == 4:
                    row, col = row + 1, 0
            box.addLayout(grid)
            box.addStretch(1)
            groups.addLayout(box)
            groups.addSpacing(10)
        outer.addLayout(groups)

    def _changed(self, key, value):
        self.engine.synth.set_param(key, value)

    def _apply_preset(self, _):
        self.engine.synth.apply_preset(self.preset.currentText())
        self.refresh()

    def refresh(self):
        vals = self.engine.synth.values
        for key, w in self.controls.items():
            w.blockSignals(True)
            if isinstance(w, QComboBox):
                w.setCurrentIndex(int(round(vals[key])))
            else:
                w.setValue(vals[key])
            w.blockSignals(False)


class TrackPage(QWidget):
    """Uma aba: cabeçalho da trilha (presets, níveis) + cadeia de efeitos."""

    def __init__(self, name, engine, accent):
        super().__init__()
        self.name = name
        self.engine = engine
        self.panels = []
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        head = QFrame()
        head.setObjectName("trackhead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 4, 10, 4)
        self.enabled = QCheckBox("Ativa")
        self.enabled.setFocusPolicy(Qt.NoFocus)
        self.enabled.toggled.connect(lambda on: self.track().set_param("track", "on", on))
        hl.addWidget(self.enabled)
        self.input_label = QLabel("")
        self.input_label.setObjectName("small")
        hl.addWidget(self.input_label)
        hl.addSpacing(8)
        self.track_knobs = {}
        for p in TRACK_PARAMS:
            if name == "pads" and p.key == "input_gain":
                continue
            k = Knob(p, accent)
            k.valueChanged.connect(lambda v, key=p.key: self.track().set_param("track", key, v))
            self.track_knobs[p.key] = k
            hl.addWidget(k)
        self.m_in, self.m_out = Meter(), Meter()
        for lab, m in (("in", self.m_in), ("out", self.m_out)):
            if name == "pads" and m is self.m_in:
                continue
            col = QVBoxLayout()
            col.addWidget(m, 1, Qt.AlignHCenter)
            t = QLabel(lab)
            t.setObjectName("small")
            col.addWidget(t, 0, Qt.AlignHCenter)
            hl.addLayout(col)
        hl.addStretch(1)
        hl.addWidget(QLabel("Preset:"))
        self.preset = QComboBox()
        self.preset.setFocusPolicy(Qt.NoFocus)
        self.preset.setMinimumWidth(190)
        self.preset.activated.connect(self._load_preset)
        hl.addWidget(self.preset)
        for text, slot in (("Salvar…", self._save_preset), ("Excluir", self._delete_preset)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            hl.addWidget(b)
        root.addWidget(head)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        self.synth_panel = None
        if name == "pads":
            self.synth_panel = SynthPanel(engine, accent)
            bl.addWidget(self.synth_panel)
        grid = QGridLayout()
        grid.setSpacing(6)
        layout_rows = (("gate", "comp", "overdrive", "amp"), ("cab", "eq", "chorus", "delay", "reverb"))
        by_key = {e.key: e for e in EFFECTS}
        for r, keys in enumerate(layout_rows):
            for c, key in enumerate(keys):
                panel = EffectPanel(by_key[key], accent, self)
                self.panels.append(panel)
                span = 2 if key == "amp" else 1
                grid.addWidget(panel, r, c, 1, span)
        bl.addLayout(grid)
        bl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.reload_presets()

    def track(self):
        return self.engine.tracks[self.name]

    def refresh(self):
        v = self.track().values["track"]
        self.enabled.blockSignals(True)
        self.enabled.setChecked(bool(v["on"]))
        self.enabled.blockSignals(False)
        for key, k in self.track_knobs.items():
            k.setValue(v[key])
        for p in self.panels:
            p.refresh()
        if self.synth_panel:
            self.synth_panel.refresh()

    def update_meters(self):
        pin, pout = self.track().meters()
        self.m_in.push(pin)
        self.m_out.push(pout)
        return pout

    # ------------------------------------------------------------------ presets
    def reload_presets(self, select=None):
        self.preset.blockSignals(True)
        self.preset.clear()
        for n in FACTORY.get(self.name, {}):
            self.preset.addItem(f"★ {n}", ("factory", n))
        for n in storage.list_user_presets(self.name):
            self.preset.addItem(n, ("user", n))
        if select:
            i = self.preset.findData(select)
            if i >= 0:
                self.preset.setCurrentIndex(i)
        self.preset.blockSignals(False)

    def apply_preset_data(self, data):
        keep_track = dict(self.track().values["track"])     # volume/pan não mudam com preset
        state = {"values": dict(data.get("values", {})), "ir_path": data.get("ir_path")}
        state["values"]["track"] = keep_track
        self.track().load_state(state)
        if self.name == "pads" and "synth" in data:
            self.engine.synth.load_state(data["synth"])
        self.refresh()

    def _load_preset(self, _):
        kind, n = self.preset.currentData()
        data = FACTORY[self.name][n] if kind == "factory" else storage.load_user_preset(self.name, n)
        if data:
            self.apply_preset_data(data)

    def _save_preset(self):
        n, ok = QInputDialog.getText(self, "Salvar preset", "Nome do preset:")
        if not ok or not n.strip():
            return
        n = n.strip()
        data = self.track().get_state()
        data["values"].pop("track", None)
        if self.name == "pads":
            data["synth"] = self.engine.synth.get_state()
        storage.save_user_preset(self.name, n, data)
        self.reload_presets(select=("user", n))

    def _delete_preset(self):
        kind, n = self.preset.currentData() or ("factory", "")
        if kind != "user":
            QMessageBox.information(self, "Presets", "Presets de fábrica (★) não podem ser excluídos.")
            return
        if QMessageBox.question(self, "Excluir preset", f"Excluir o preset “{n}”?") == QMessageBox.Yes:
            storage.delete_user_preset(self.name, n)
            self.reload_presets()
