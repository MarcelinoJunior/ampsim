"""Página de cada trilha: cabeçalho fino, seletor de amplificador e pedais compactos.

Layout (de cima para baixo):
    cabeçalho da trilha (uma linha)
    [synth de pads — só na aba Pads]
    Amplificador: seletor único (modelos AmpSim / capturas NAM / plugins VST3 / sem amp),
                  controles do amp escolhido e o gabinete ao lado
    Pedais antes do amp:  redutor de ruído, gate, compressor, overdrive
    Efeitos depois do amp: EQ, chorus, delay, reverb
"""
import math
import os
import shutil

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import storage
from ..audio import vst
from ..dsp.nam import list_captures
from ..dsp.params import AMP_MODELS, CAB_IR_INDEX, EFFECT_BY_KEY, SYNTH_GROUPS, TRACK_PARAMS
from ..dsp.synth import SYNTH_PRESETS
from ..presets import FACTORY
from .amp_skins import SKINS, TRADEMARK_NOTICE, capture_face, paint_face
from .widgets import Knob, LedButton, Meter

CALIB_TICKS = 70          # ~2,3 s com o timer de 33 ms da janela principal
CALIB_SKIP = 10           # ignora o começo (clique do mouse, transientes)
CALIB_MARGIN_DB = 6.0     # limiar fica 6 dB acima do pico do ruído

PRE_AMP = ("denoise", "gate", "comp", "overdrive")
POST_AMP = ("eq", "chorus", "delay", "reverb")


def _key(kind, arg):
    """Identificador (texto) de um item do seletor de amplificador."""
    return f"{kind}:{arg}"


def _combo():
    c = QComboBox()
    c.setFocusPolicy(Qt.NoFocus)
    return c


def _small(text=""):
    lab = QLabel(text)
    lab.setObjectName("small")
    return lab


class _Face(QWidget):
    """Área da fachada do amp: o desenho fica por conta do painel dono."""

    def __init__(self, painter):
        super().__init__()
        self._painter = painter

    def paintEvent(self, event):
        self._painter(event)


class _VLabel(QWidget):
    """Legenda vertical discreta ao lado de uma fileira de pedais."""

    def __init__(self, text):
        super().__init__()
        self.text = text
        self.setFixedWidth(16)
        self.setToolTip(text)

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setPen(QColor("#6f7480"))
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        qp.setFont(f)
        qp.translate(self.width() / 2 + 4, self.height() / 2)
        qp.rotate(-90)
        qp.drawText(QRectF(-self.height() / 2, -10, self.height(), 14), Qt.AlignCenter, self.text)


class EffectPanel(QFrame):
    """Pedal compacto: LED + nome (+ seletores) numa linha, knobs pequenos na outra."""

    def __init__(self, eff, accent, page):
        super().__init__()
        self.eff = eff
        self.page = page
        self.setObjectName("effect")
        self.controls = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 4)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.led = LedButton(accent)
        self.led.toggled.connect(lambda on: self.track().set_on(self.eff.key, on))
        title = QLabel(eff.title)
        title.setObjectName("fxtitle")
        head.addWidget(self.led)
        head.addWidget(title)
        head.addStretch(1)
        knobs = QHBoxLayout()
        knobs.setSpacing(0)
        for p in eff.params:
            if p.is_choice:
                combo = _combo()
                combo.addItems(p.choices)
                combo.setToolTip(p.label)
                combo.currentIndexChanged.connect(lambda i, k=p.key: self._changed(k, float(i)))
                self.controls[p.key] = combo
                head.addWidget(combo)
            else:
                knob = Knob(p, accent, size="small")
                knob.valueChanged.connect(lambda v, k=p.key: self._changed(k, v))
                self.controls[p.key] = knob
                knobs.addWidget(knob)
        knobs.addStretch(1)
        lay.addLayout(head)
        lay.addLayout(knobs)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def track(self):
        return self.page.track()

    def _changed(self, key, value):
        self.track().set_param(self.eff.key, key, value)

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


class CabPanel(EffectPanel):
    """Gabinete, ao lado do amplificador."""

    def __init__(self, eff, accent, page):
        super().__init__(eff, accent, page)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        lay = self.layout()
        row = QHBoxLayout()
        btn = QPushButton("Carregar IR…")
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setToolTip("Usa um impulso de gabinete (.wav) no lugar dos modelos internos")
        btn.clicked.connect(self._load_ir)
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.ir_label = _small()
        self.ir_label.setWordWrap(True)
        lay.addWidget(self.ir_label)
        lay.addStretch(1)

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
        super().refresh()
        t = self.track()
        txt = f"IR: {os.path.basename(t.ir_path)}" if t.ir_path else ""
        if t.ir_error:
            txt = f"erro na IR: {t.ir_error}"
        self.ir_label.setText(txt)


class AmpRigPanel(QFrame):
    """Escolha do amplificador em cima; embaixo só os controles do amp escolhido."""

    def __init__(self, page, accent):
        super().__init__()
        self.page = page
        self.setObjectName("amppanel")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.face = _Face(self._paint_face)
        self.face.setObjectName("ampface")
        fl = QVBoxLayout(self.face)
        fl.setContentsMargins(14, 8, 14, 24)
        fl.setSpacing(4)

        top = QHBoxLayout()
        lab = QLabel("Amplificador")
        lab.setObjectName("fxtitle")
        top.addWidget(lab)
        self.selector = _combo()
        self.selector.setMinimumWidth(380)
        self.selector.setMaxVisibleItems(30)
        self.selector.activated.connect(self._selected)
        top.addWidget(self.selector, 1)
        top.addStretch(0)
        fl.addLayout(top)

        self.grille = QWidget()
        self.grille.setFixedHeight(58)
        fl.addWidget(self.grille)

        # controles de cada tipo de amp (só um grupo fica visível)
        self.knobs = {}
        self.model_box = QWidget()
        ml = QHBoxLayout(self.model_box)
        ml.setContentsMargins(0, 12, 0, 0)
        ml.setSpacing(4)
        ml.addStretch(1)
        for p in EFFECT_BY_KEY["amp"].params:
            if p.is_choice:
                continue
            k = Knob(p, accent)
            k.valueChanged.connect(lambda v, key=p.key: self.track().set_param("amp", key, v))
            self.knobs[p.key] = k
            ml.addWidget(k)
        ml.addStretch(1)

        self.nam_box = QWidget()
        nl = QHBoxLayout(self.nam_box)
        nl.setContentsMargins(0, 12, 0, 0)
        nl.addStretch(1)
        self.nam_knobs = {}
        for p in EFFECT_BY_KEY["nam"].params:
            k = Knob(p, accent)
            k.valueChanged.connect(lambda v, key=p.key: self.track().set_param("nam", key, v))
            self.nam_knobs[p.key] = k
            nl.addWidget(k)
        nl.addSpacing(16)
        ncol = QVBoxLayout()
        add = QPushButton("Adicionar captura .nam…")
        add.setFocusPolicy(Qt.NoFocus)
        add.setToolTip("Copia um arquivo .nam (ex.: do ToneHunt) para a sua pasta de capturas")
        add.clicked.connect(self._add_capture)
        ncol.addWidget(add)
        self.nam_status = _small()
        ncol.addWidget(self.nam_status)
        nl.addLayout(ncol)
        nl.addStretch(1)

        self.vst_box = QWidget()
        vl = QHBoxLayout(self.vst_box)
        vl.setContentsMargins(0, 12, 0, 0)
        vl.addStretch(1)
        self.vst_mix = Knob(EFFECT_BY_KEY["vst"].params[0], accent)
        self.vst_mix.valueChanged.connect(lambda v: self.track().set_param("vst", "mix", v))
        vl.addWidget(self.vst_mix)
        vl.addSpacing(16)
        vcol = QVBoxLayout()
        self.edit_btn = QPushButton("Abrir editor do plugin")
        self.edit_btn.setFocusPolicy(Qt.NoFocus)
        self.edit_btn.clicked.connect(self._edit_vst)
        vcol.addWidget(self.edit_btn)
        self.vst_status = _small()
        vcol.addWidget(self.vst_status)
        vl.addLayout(vcol)
        vl.addStretch(1)

        self.di_box = QLabel("Sem amplificador: o sinal vai direto para o gabinete e os efeitos.")
        self.di_box.setAlignment(Qt.AlignCenter)

        for box in (self.model_box, self.nam_box, self.vst_box, self.di_box):
            box.setFixedHeight(104)          # espaço para o modelo escrito e o aviso de marca
            fl.addWidget(box)

        outer.addWidget(self.face, 4)
        self.cab = CabPanel(EFFECT_BY_KEY["cab"], accent, page)
        self.cab.setMinimumWidth(240)
        outer.addWidget(self.cab, 1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._fill_selector()

    def track(self):
        return self.page.track()

    # ------------------------------------------------------------------ seletor
    def _fill_selector(self):
        sel = self.selector
        sel.blockSignals(True)
        sel.clear()
        model = sel.model()

        def header(text):
            sel.addItem(text, None)
            item = model.item(sel.count() - 1) if isinstance(model, QStandardItemModel) else None
            if item is not None:
                item.setEnabled(False)

        sel.addItem("Sem amplificador (DI)", _key("none", ""))
        header("──  Modelos AmpSim  ──")
        for i, m in enumerate(AMP_MODELS):
            sel.addItem(f"{m['name']}   ·   estilo {m['inspired']}", _key("model", i))
        caps = list(list_captures())
        header("──  Capturas NAM (amps reais)  ──")
        for name in caps:
            sel.addItem(f"{name}   ·   captura NAM", _key("nam", name))
        sel.addItem("Adicionar captura .nam…", _key("nam_add", ""))
        header("──  Plugins VST3  ──")
        for path in vst.find_plugins():
            sel.addItem(f"{os.path.splitext(os.path.basename(path))[0]}   ·   plugin VST3", _key("vst", path))
        sel.addItem("Outro plugin .vst3…", _key("vst_other", ""))
        sel.blockSignals(False)

    def source(self):
        t = self.track()
        v = t.values
        if v["vst"]["on"] and v["vst"]["path"]:
            return ("vst", v["vst"]["path"])
        if v["nam"]["on"] and v["nam"]["file"]:
            return ("nam", v["nam"]["file"])
        if v["amp"]["on"]:
            return ("model", int(round(v["amp"]["model"])))
        return ("none", None)

    def _selected(self, _):
        data = self.selector.currentData()
        if not data:
            self.refresh()
            return
        kind, arg = data.split(":", 1)
        if kind == "model":
            arg = int(arg)
        t = self.track()
        if kind == "nam_add":
            self._add_capture()
            return
        if kind == "vst_other":
            path, _ = QFileDialog.getOpenFileName(self, "Escolher plugin VST3", vst.SYSTEM_VST3_DIR,
                                                  "Plugins VST3 (*.vst3)")
            if not path:
                self.refresh()
                return
            kind, arg = "vst", path
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if kind == "model":
                t.set_param("amp", "model", float(arg))
            elif kind == "nam":
                t.set_nam_file(arg)
            elif kind == "vst" and (t.vst is None or t.vst.path != arg):
                if not t.load_vst(arg):
                    QMessageBox.warning(self, "Plugin VST3", f"Não foi possível carregar:\n{t.vst_error}")
            t.set_on("amp", kind == "model")
            t.set_on("nam", kind == "nam")
            t.set_on("vst", kind == "vst" and t.vst is not None)
            if kind == "nam" and not t.values["cab"]["on"]:
                t.set_on("cab", True)          # as capturas são só o amp, sem falante
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()

    def _add_capture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Adicionar captura NAM", "", "Capturas NAM (*.nam)")
        if not path:
            self.refresh()
            return
        dest = storage.APP_DIR / "nam"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest / os.path.basename(path))
        self._fill_selector()
        name = os.path.splitext(os.path.basename(path))[0]
        i = self.selector.findData(_key("nam", name))
        if i >= 0:
            self.selector.setCurrentIndex(i)
            self._selected(i)

    def _edit_vst(self):
        t = self.track()
        if t.vst is None:
            return
        self.vst_status.setText("Editor aberto — feche a janela do plugin para voltar.")
        QApplication.processEvents()
        t.vst.show_editor()
        t.get_state()                    # guarda o novo estado do plugin
        self.refresh()

    # ------------------------------------------------------------------ aparência
    def _face_info(self):
        """(fachada, texto da marca/logo, modelo escrito no painel, aviso de marca)."""
        kind, arg = self.source()
        if kind == "model":
            m = AMP_MODELS[arg]
            if not m["brand"]:
                return m["skin"], m["name"], "", ""
            return (m["skin"], m["brand"], f"{m['model']}  ·  AmpSim {m['name']}",
                    TRADEMARK_NOTICE.format(brand=m["brand"]))
        if kind == "nam":
            skin, brand, model = capture_face(arg)
            if skin == "nam":
                return skin, arg, "captura NAM", ""
            return skin, brand, f"{model}  ·  captura NAM", TRADEMARK_NOTICE.format(brand=brand)
        if kind == "vst":
            t = self.track()
            return "vst", t.vst.name if t.vst else os.path.basename(arg), "plugin VST3", ""
        return "di", "Sinal direto (DI)", "", ""

    def _paint_face(self, _):
        skin, logo, model, notice = self._face_info()
        paint_face(self.face, skin, logo, self.grille.geometry(), model, notice)

    def refresh(self):
        t = self.track()
        kind, arg = self.source()
        key = _key(kind, arg if arg is not None else "")
        i = self.selector.findData(key)
        if i < 0 and kind == "nam":
            self._fill_selector()
            i = self.selector.findData(key)
        if i < 0 and kind == "vst":
            self.selector.insertItem(self.selector.count() - 1,
                                     f"{os.path.splitext(os.path.basename(arg))[0]}   ·   plugin VST3", key)
            i = self.selector.findData(key)
        self.selector.blockSignals(True)
        self.selector.setCurrentIndex(max(i, 0))
        self.selector.blockSignals(False)

        for box, k in ((self.model_box, "model"), (self.nam_box, "nam"), (self.vst_box, "vst"),
                       (self.di_box, "none")):
            box.setVisible(kind == k)

        skin = SKINS[self._face_info()[0]]
        for knob in list(self.knobs.values()) + list(self.nam_knobs.values()) + [self.vst_mix]:
            knob.set_skin(skin.accent, skin.knob_cap, skin.knob_ring, skin.text, skin.dim, skin.pointer,
                          style=skin.knob_style, skirt=skin.knob_skirt, upper=skin.upper)
        self.di_box.setStyleSheet(f"color: {skin.dim};")
        for key, k in self.knobs.items():
            k.setValue(t.values["amp"][key])
        for key, k in self.nam_knobs.items():
            k.setValue(t.values["nam"][key])
        self.vst_mix.setValue(t.values["vst"]["mix"])

        if t.nam_error:
            self.nam_status.setText(t.nam_error)
        else:
            self.nam_status.setText("Amp real capturado (Neural Amp Modeler).")
        self.edit_btn.setEnabled(t.vst is not None)
        if t.vst_error:
            self.vst_status.setText(f"Erro: {t.vst_error}")
        elif t.vst is not None and t.vst.error:
            self.vst_status.setText(f"Plugin desativado após erro: {t.vst.error}")
        elif t.vst is not None:
            self.vst_status.setText(f"{t.vst.name} · o estado do plugin fica salvo no preset")
        for lab in (self.nam_status, self.vst_status):
            lab.setStyleSheet(f"color: {skin.dim};")
        self.cab.refresh()
        self.face.update()


class SynthPanel(QFrame):
    def __init__(self, engine, accent):
        super().__init__()
        self.engine = engine
        self.setObjectName("effect")
        self.controls = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 5, 8, 4)
        outer.setSpacing(2)
        head = QHBoxLayout()
        title = QLabel("Synth de Pads")
        title.setObjectName("fxtitle")
        head.addWidget(title)
        head.addSpacing(12)
        head.addWidget(QLabel("Som:"))
        self.preset = _combo()
        self.preset.addItems(list(SYNTH_PRESETS))
        self.preset.activated.connect(self._apply_preset)
        head.addWidget(self.preset)
        head.addStretch(1)
        outer.addLayout(head)
        groups = QHBoxLayout()
        groups.setSpacing(4)
        for gname, params in SYNTH_GROUPS:
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(_small(gname))
            grid = QGridLayout()
            grid.setSpacing(0)
            col = 0
            for p in params:
                if p.is_choice:
                    combo = _combo()
                    combo.addItems(p.choices)
                    combo.setToolTip(p.label)
                    combo.currentIndexChanged.connect(lambda i, k=p.key: self._changed(k, float(i)))
                    self.controls[p.key] = combo
                    box.addWidget(combo)
                    continue
                knob = Knob(p, accent, size="small")
                knob.valueChanged.connect(lambda v, k=p.key: self._changed(k, v))
                self.controls[p.key] = knob
                grid.addWidget(knob, col // 4, col % 4)
                col += 1
            box.addLayout(grid)
            box.addStretch(1)
            groups.addLayout(box)
            groups.addSpacing(10)
        groups.addStretch(1)
        outer.addLayout(groups)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

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
    """Uma aba: cabeçalho fino da trilha + synth (pads) + amplificador + pedais."""

    def __init__(self, name, engine, accent):
        super().__init__()
        self.name = name
        self.engine = engine
        self.panels = []
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        root.addWidget(self._build_header(accent))

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        self.rig = AmpRigPanel(self, accent)
        bl.addWidget(self.rig)
        self.pre_panels = []
        for caption, keys in (("Antes do amp", PRE_AMP), ("Depois do amp", POST_AMP)):
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(_VLabel(caption))
            for key in keys:
                panel = EffectPanel(EFFECT_BY_KEY[key], accent, self)
                self.panels.append(panel)
                if key in PRE_AMP:
                    self.pre_panels.append(panel)
                row.addWidget(panel, sum(1 for p in EFFECT_BY_KEY[key].params if not p.is_choice))
            bl.addLayout(row)
        bl.addStretch(1)
        scroll = QScrollArea()          # só aparece se a janela for pequena demais
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)

        self.synth_panel = None
        self.keys_view = None
        if name != "pads":
            root.addWidget(scroll, 1)
        else:
            # aba Teclas & Pads: três visões que se alternam (nada de rolagem)
            from .keys_page import KeysView

            self.keys_view = KeysView(engine, accent)
            self.synth_panel = SynthPanel(engine, accent)
            synth_page = QWidget()
            sl = QVBoxLayout(synth_page)
            sl.setContentsMargins(0, 0, 0, 0)
            sl.addWidget(self.synth_panel)
            sl.addStretch(1)
            self.stack = QStackedWidget()
            for w in (self.keys_view, synth_page, scroll):
                self.stack.addWidget(w)
            switch = QHBoxLayout()
            switch.setSpacing(2)
            self.view_buttons = []
            for i, text in enumerate(("Controlador e timbres", "Synth AmpSim (pads)",
                                      "Amplificador e efeitos")):
                b = QPushButton(text)
                b.setObjectName("seg")
                b.setCheckable(True)
                b.setFocusPolicy(Qt.NoFocus)
                b.clicked.connect(lambda _, i=i: self.show_view(i))
                self.view_buttons.append(b)
                switch.addWidget(b)
            switch.addStretch(1)
            root.addLayout(switch)
            root.addWidget(self.stack, 1)
            self.show_view(0)
        self.reload_presets()

    def _build_header(self, accent):
        head = QFrame()
        head.setObjectName("trackhead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(8, 2, 8, 2)
        hl.setSpacing(8)
        self.enabled = QCheckBox("Ativa")
        self.enabled.setFocusPolicy(Qt.NoFocus)
        self.enabled.toggled.connect(lambda on: self._track_param("on", on))
        hl.addWidget(self.enabled)
        if self.name == "pads":
            self.amp_check = QCheckBox("Teclas passam pelo amplificador")
            self.amp_check.setFocusPolicy(Qt.NoFocus)
            self.amp_check.setToolTip("Ligado: as teclas (ex.: timbre de guitarra) passam pelo amplificador,\n"
                                      "gabinete e pedais. Desligado: som limpo do timbre, só com os efeitos.\n"
                                      "A bateria dos pads nunca passa pelo amplificador.")
            self.amp_check.toggled.connect(self._amp_toggled)
            hl.addWidget(self.amp_check)
        self.input_label = _small()
        hl.addWidget(self.input_label)
        self.mute_label = QLabel("")
        self.mute_label.setStyleSheet("color: #ff6b6b; font-weight: 600;")
        hl.addWidget(self.mute_label)
        self._calib = None
        if self.name != "pads":
            self.calib_btn = QPushButton("Calibrar ruído")
            self.calib_btn.setFocusPolicy(Qt.NoFocus)
            self.calib_btn.setToolTip("Com o instrumento plugado e as cordas abafadas, mede o chiado da\n"
                                      "entrada por 2 s e ajusta os limiares do Gate e do Redutor de Ruído.")
            self.calib_btn.clicked.connect(self._start_calibration)
            hl.addWidget(self.calib_btn)
        self.track_knobs = {}
        for p in TRACK_PARAMS:
            if self.name == "pads" and p.key == "input_gain":
                continue
            k = Knob(p, accent, size="mini")
            k.valueChanged.connect(lambda v, key=p.key: self._track_param(key, v))
            self.track_knobs[p.key] = k
            hl.addWidget(k)
        meters = QGridLayout()
        meters.setSpacing(2)
        self.m_in, self.m_out = Meter(horizontal=True), Meter(horizontal=True)
        for r, (lab, m) in enumerate((("in", self.m_in), ("out", self.m_out))):
            if self.name == "pads" and m is self.m_in:
                continue
            meters.addWidget(_small(lab), r, 0)
            meters.addWidget(m, r, 1)
        hl.addLayout(meters)
        hl.addStretch(1)
        hl.addWidget(QLabel("Preset:"))
        self.preset = _combo()
        self.preset.setMinimumWidth(220)
        self.preset.activated.connect(self._load_preset)
        hl.addWidget(self.preset)
        for text, slot in (("Salvar…", self._save_preset), ("Excluir", self._delete_preset)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            hl.addWidget(b)
        return head

    def track(self):
        return self.engine.tracks[self.name]

    def show_view(self, i):
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.view_buttons):
            b.setChecked(j == i)

    def _amp_toggled(self, on):
        self.track().set_param("track", "use_amp", bool(on))
        self.engine.instruments.all_off()
        self.refresh()

    def _track_param(self, key, value):
        self.track().set_param("track", key, value)
        self._update_mute_label()

    def _update_mute_label(self):
        v = self.track().values["track"]
        muted = v["volume"] <= -59.9 or not v["on"]
        self.mute_label.setText("⚠ trilha muda (volume no mínimo)" if v["volume"] <= -59.9 and v["on"]
                                else ("⚠ trilha desligada" if muted else ""))

    def refresh(self):
        v = self.track().values["track"]
        self.enabled.blockSignals(True)
        self.enabled.setChecked(bool(v["on"]))
        self.enabled.blockSignals(False)
        for key, k in self.track_knobs.items():
            k.setValue(v[key])
        self._update_mute_label()
        self.rig.refresh()
        for p in self.panels:
            p.refresh()
        use_amp = v.get("use_amp", True)
        self.rig.setEnabled(use_amp)
        for p in self.pre_panels:
            p.setEnabled(use_amp)
        if self.name == "pads":
            self.amp_check.blockSignals(True)
            self.amp_check.setChecked(use_amp)
            self.amp_check.blockSignals(False)
        if self.synth_panel:
            self.synth_panel.refresh()
        if self.keys_view:
            self.keys_view.refresh()

    def update_meters(self):
        pin, pout = self.track().meters()
        if self.name == "pads":          # teclas/bateria que saem direto (sem a trilha)
            pout = max(pout, self.engine.sf_peak)
            self.engine.sf_peak = 0.0
        self.m_in.push(pin)
        self.m_out.push(pout)
        if self._calib is not None:
            self._calib.append(pin)
            if len(self._calib) >= CALIB_TICKS:
                self._finish_calibration()
        return pout

    # ------------------------------------------------------------------ calibração de ruído
    def _start_calibration(self):
        if not self.engine.running:
            QMessageBox.information(self, "Calibrar ruído", "Ligue o áudio antes de calibrar.")
            return
        self._calib = []
        self.calib_btn.setEnabled(False)
        self.calib_btn.setText("Medindo… não toque")

    def _finish_calibration(self):
        peaks = self._calib[CALIB_SKIP:]
        self._calib = None
        self.calib_btn.setEnabled(True)
        self.calib_btn.setText("Calibrar ruído")
        noise = max(peaks) if peaks else 0.0
        if noise <= 1e-6:
            QMessageBox.information(self, "Calibrar ruído",
                                    "Nenhum sinal na entrada. Confira o canal da trilha em ⚙ Áudio.")
            return
        noise_db = 20 * math.log10(noise)
        thr = round(min(max(noise_db + CALIB_MARGIN_DB, -80.0), -20.0))
        t = self.track()
        t.set_on("denoise", True)
        t.set_param("denoise", "sens", thr)
        t.set_on("gate", True)
        t.set_param("gate", "threshold", thr)
        self.refresh()
        msg = (f"Ruído de entrada medido: {noise_db:.0f} dB (pico).\n"
               f"Gate e Redutor de Ruído ajustados para {thr} dB.")
        if noise_db > -40:
            msg += ("\n\nO ruído está alto. Verifique cabo e captadores, abaixe o ganho de entrada "
                    "do microfone no Windows ou afaste o instrumento do computador/monitor.")
        QMessageBox.information(self, "Calibrar ruído", msg)

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
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.track().load_state(state)
        finally:
            QApplication.restoreOverrideCursor()
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
