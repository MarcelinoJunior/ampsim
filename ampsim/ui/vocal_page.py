"""Aba Vocal: microfone com cadeia de voz (dsp/vocal.py), sem amplificador nem gabinete.

Layout (igual às abas Guitarra/Baixo):
    centro: pedais em três fileiras (Limpeza, Voz, Ambiente) e a curva do filtro + EQ
    direita: trilha (liga, mudo, fase, entrada, volume, pan, medidores, clip) e os plugins VST3 (FX)

Cada controle tem um identificador estável "vocal/<efeito>/<parâmetro>" (propriedade Qt "ctrl_id" e
VocalPage.controls_by_id), usado pelo mapeamento MIDI (midi_map.py; botão direito "Mapear controle físico…",
ui/ctl_map_ui.py). Os liga/desliga dos efeitos são "vocal/<efeito>/on"; os da trilha são "vocal/track/on",
"vocal/track/mute" e "vocal/track/phase".
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import storage
from ..dsp.vocal import PLUG_POS_PARAM, VOCAL_EFFECT_BY_KEY, VOCAL_TRACK_PARAMS, latency_note
from ..presets import FACTORY
from .icons import icon
from .panels import EffectPanel, _VLabel, _combo, _small
from .theme import ACCENT, C
from .widgets import Knob, Meter, ToggleSwitch, find_data

ROWS = (("Limpeza", ("hpf", "gate", "deess")),
        ("Voz", ("comp", "eq")),
        ("Ambiente", ("double", "delay", "reverb")))
CLIP_HOLD_S = 1.5
SIGNAL_FLOOR = 10 ** (-70 / 20)     # entrada abaixo de -70 dBFS: sem sinal (cabo solto, mic mudo na placa)
SIGNAL_HOLD_S = 1.0


def e_running(page):
    """O áudio está ligado (sem áudio não há sinal para o gate abrir)."""
    return bool(getattr(page.engine, "running", False))

TOGGLE_ON = (f"QPushButton {{ background: {C['red']}; border: 1px solid #ff8a96; color: white; "
             "font-weight: 800; border-radius: 6px; padding: 4px 8px; }")
TOGGLE_PHASE_ON = (f"QPushButton {{ background: {C['card']}; border: 1px solid {C['accent']}; color: {C['accent']}; "
                   "font-weight: 700; border-radius: 6px; padding: 4px 8px; }")


def ctrl_id(effect, key):
    return f"vocal/{effect}/{key}"


class _GrBar(QWidget):
    """Barra de redução em dB (compressor / de-esser): cresce da esquerda, até 20 dB."""

    def __init__(self, tip):
        super().__init__()
        self.setFixedSize(84, 14)
        self.setToolTip(tip)
        self.db = 0.0
        self.shown = 0.0

    def push(self, db):
        self.shown = max(db, self.shown - 0.6)       # cai ~18 dB/s (dá para ler)
        self.update()

    def paintEvent(self, _):
        qp = QPainter(self)
        w, h = self.width(), self.height()
        qp.fillRect(0, 0, w, h, QColor("#08101b"))
        t = min(max(self.shown / 20.0, 0.0), 1.0)
        qp.fillRect(1, 2, int((w - 2) * t), h - 4, QColor(C["accent"]))
        f = QFont(self.font())
        f.setPointSizeF(7.0)
        qp.setFont(f)
        qp.setPen(QColor(C["text"]))
        qp.drawText(QRectF(0, 0, w - 3, h), Qt.AlignRight | Qt.AlignVCenter,
                    f"−{self.shown:.0f} dB" if self.shown >= 0.5 else "0 dB")


class VocalCurve(QWidget):
    """Curva do filtro de graves + EQ de voz (o que está ligado), de 20 Hz a 20 kHz, ±15 dB."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._sig = None
        n = 160
        self.freqs = [20.0 * (1000.0 ** (i / (n - 1))) for i in range(n)]
        self.resp = [0.0] * n

    def sync(self, force=False):
        v = self.page.track().values
        sig = (tuple(sorted(v["hpf"].items())), tuple(sorted(v["eq"].items())))
        if sig == self._sig and not force:
            return
        self._sig = sig
        self.resp = list(self.page.track().response(self.freqs))
        self.update()

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(34, 8, -10, -18)
        qp.fillRect(self.rect(), QColor(C["card"]))
        qp.setPen(QPen(QColor(C["border"]), 1))
        f = QFont(self.font())
        f.setPointSizeF(7.0)
        qp.setFont(f)

        def x_of(fr):
            return r.left() + r.width() * math.log10(fr / 20.0) / 3.0

        def y_of(db):
            return r.center().y() - r.height() / 2 * max(-15.0, min(15.0, db)) / 15.0
        for fr, lab in ((50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1k"), (2000, "2k"),
                        (5000, "5k"), (10000, "10k")):
            x = x_of(fr)
            qp.setPen(QPen(QColor(C["border"]), 1))
            qp.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            qp.setPen(QColor(C["dim"]))
            qp.drawText(QRectF(x - 20, r.bottom() + 2, 40, 14), Qt.AlignCenter, lab)
        for db in (-12, -6, 0, 6, 12):
            y = y_of(db)
            qp.setPen(QPen(QColor(C["border2"] if db == 0 else C["border"]), 1))
            qp.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            qp.setPen(QColor(C["dim"]))
            qp.drawText(QRectF(0, y - 7, 30, 14), Qt.AlignRight | Qt.AlignVCenter, f"{db:+d}" if db else "0")
        path = QPainterPath()
        for i, (fr, db) in enumerate(zip(self.freqs, self.resp)):
            p = QPointF(x_of(fr), y_of(db))
            path.moveTo(p) if i == 0 else path.lineTo(p)
        qp.setPen(QPen(QColor(C["accent"]), 2))
        qp.drawPath(path)
        qp.setPen(QColor(C["dim"]))
        qp.drawText(QRectF(r.left() + 6, r.top(), 300, 14), Qt.AlignLeft | Qt.AlignVCenter,
                    "Curva da voz (filtro de graves + EQ)")


class VocalPage(QWidget):
    """Aba Vocal. Mesma interface pública da TrackPage que a janela principal, o banco de presets, o menu
    Arquivo e a tela remota usam (track, refresh, preset, presets, medidores, input_label...)."""

    def __init__(self, engine, accent=ACCENT):
        super().__init__()
        self.name = "vocal"
        self.engine = engine
        self.panels = []
        self.controls_by_id = {}
        self._clip_until = 0.0
        self._tick = 0
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        intro = QFrame()
        intro.setObjectName("card")
        il = QVBoxLayout(intro)
        il.setContentsMargins(12, 8, 12, 8)
        il.setSpacing(2)
        t = QLabel("Microfone: ligue a trilha à direita e escolha o canal em ⚙ Áudio (Canal do vocal).")
        t.setWordWrap(True)
        il.addWidget(t)
        tip = _small("Comece por um preset ★ (ex.: Voz limpa). Cada pedal tem o seu LED de liga/desliga. "
                     "A saída passa pelo compressor/limitador do Master, que protege as caixas.")
        tip.setWordWrap(True)
        il.addWidget(tip)
        self.warn_label = QLabel("")
        self.warn_label.setObjectName("warn")
        self.warn_label.setWordWrap(True)
        self.warn_label.setVisible(False)
        il.addWidget(self.warn_label)
        intro.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        bl.addWidget(intro)

        self.panel_by_key = {}
        for caption, keys in ROWS:
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(_VLabel(caption))
            for key in keys:
                eff = VOCAL_EFFECT_BY_KEY[key]
                panel = EffectPanel(eff, accent, self)
                self.panels.append(panel)
                self.panel_by_key[key] = panel
                self._register(ctrl_id(key, "on"), panel.led)
                for pk, w in panel.controls.items():
                    self._register(ctrl_id(key, pk), w)
                row.addWidget(panel, max(1, sum(1 for p in eff.params if not p.is_choice)))
            bl.addLayout(row)
        self._add_dynamics()
        self.curve = VocalCurve(self)
        bl.addWidget(self.curve, 1)
        bl.addStretch(0)                # curva escondida (barra de baixo aberta): o espaço sobra embaixo

        scroll = QScrollArea()          # só aparece se a janela for pequena demais
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(body)
        self.scroll = scroll
        root.addWidget(scroll, 1)
        root.addWidget(self._build_side(accent))

        self.preset = _combo()          # fica na barra superior (TopBar.preset_stack)
        self.preset.setToolTip("Preset da voz (★ = de fábrica)")
        self.preset.activated.connect(self._load_preset)
        self.reload_presets()

    # ------------------------------------------------------------------ construção
    def _register(self, cid, w):
        from .ctl_map_ui import install
        install(w, cid)                 # ctrl_id + botão direito "Mapear controle físico…" (midi_map.py)
        self.controls_by_id[cid] = w

    def _add_dynamics(self):
        """Medidores dentro dos pedais: redução do compressor e do de-esser, gate aberto/fechado; o Tempo
        do delay fica apagado quando ele segue o BPM."""
        comp = self.panel_by_key["comp"]
        self.comp_gr = _GrBar("Quanto o compressor está abaixando os picos da voz agora")
        comp.layout().itemAt(0).layout().addWidget(self.comp_gr)
        ds = self.panel_by_key["deess"]
        self.deess_gr = _GrBar("Quanto o de-esser está abaixando os agudos do “S” agora")
        ds.layout().itemAt(0).layout().addWidget(self.deess_gr)
        gate = self.panel_by_key["gate"]
        self.gate_state = _small("")
        self.gate_state.setToolTip("Gate aberto: passa a voz. Fechado: abaixa o ruído entre as frases.")
        gate.layout().itemAt(0).layout().addWidget(self.gate_state)
        dl = self.panel_by_key["delay"]
        dl.controls["sync"].currentIndexChanged.connect(lambda *_: self._sync_delay_time())

    def _build_side(self, accent):
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(262)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        hi = QLabel()
        hi.setPixmap(icon("mic", C["text"], 18).pixmap(18, 18))
        head.addWidget(hi)
        t = QLabel("Trilha do Vocal")
        t.setObjectName("h2")
        head.addWidget(t, 1)
        self.enabled = ToggleSwitch()
        self.enabled.setToolTip("Liga/desliga o microfone (a trilha começa desligada)")
        self.enabled.toggled.connect(lambda on: self._switch("on", on))
        self._register(ctrl_id("track", "on"), self.enabled)
        head.addWidget(self.enabled)
        lay.addLayout(head)
        self.input_label = _small()
        self.input_label.setWordWrap(True)
        lay.addWidget(self.input_label)
        self.mute_label = QLabel("")
        self.mute_label.setObjectName("bad")
        self.mute_label.setWordWrap(True)
        lay.addWidget(self.mute_label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.mute_btn = QPushButton("Mudo")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFocusPolicy(Qt.NoFocus)
        self.mute_btn.setToolTip("Silencia a voz sem desligar o microfone (os medidores continuam). Atalho: Alt+V")
        self.mute_btn.clicked.connect(lambda on: self._switch("mute", on))
        self._register(ctrl_id("track", "mute"), self.mute_btn)
        row.addWidget(self.mute_btn, 1)
        self.phase_btn = QPushButton("Ø Inverter fase")
        self.phase_btn.setCheckable(True)
        self.phase_btn.setFocusPolicy(Qt.NoFocus)
        self.phase_btn.setToolTip("Inverte a polaridade do microfone (use se a voz ficar fina somada a outro "
                                  "microfone ou ao retorno)")
        self.phase_btn.clicked.connect(lambda on: self._switch("phase", on))
        self._register(ctrl_id("track", "phase"), self.phase_btn)
        row.addWidget(self.phase_btn, 1)
        lay.addLayout(row)

        card = QFrame()
        card.setObjectName("card")
        kl = QHBoxLayout(card)
        kl.setContentsMargins(4, 8, 4, 4)
        kl.setSpacing(0)
        self.track_knobs = {}
        for p in VOCAL_TRACK_PARAMS:
            k = Knob(p, accent, size="medium")
            k.valueChanged.connect(lambda v, key=p.key: self._track_param(key, v))
            self.track_knobs[p.key] = k
            self._register(ctrl_id("track", p.key), k)
            kl.addWidget(k, 1)
        lay.addWidget(card)

        meters = QGridLayout()
        meters.setHorizontalSpacing(8)
        meters.setVerticalSpacing(4)
        self.m_in, self.m_out = Meter(horizontal=True), Meter(horizontal=True)
        for r, (lab, m) in enumerate((("Entrada", self.m_in), ("Saída", self.m_out))):
            m.setFixedSize(140, 8)
            meters.addWidget(_small(lab), r, 0)
            meters.addWidget(m, r, 1)
        self.clip_label = QLabel("CLIP")
        self.clip_label.setToolTip("Acende quando a entrada passou do máximo: abaixe o ganho na placa de som "
                                   "(ou o knob Entrada)")
        self.clip_label.setAlignment(Qt.AlignCenter)
        self.clip_label.setFixedWidth(36)
        meters.addWidget(self.clip_label, 0, 2)
        lay.addLayout(meters)
        self._set_clip(False)

        from .plugin_slot import FxLine
        self.fx_line = FxLine(lambda: self.track().fx_chain, self._open_fx, "Plugins")
        lay.addWidget(self.fx_line)
        self.fx_btn = self.fx_line.button
        lay.addWidget(_small("Os plugins entram:"))
        self.plug_pos = _combo()
        self.plug_pos.addItems(PLUG_POS_PARAM.choices)
        self.plug_pos.setToolTip("Antes: o plugin recebe a voz limpa (ex.: afinador, EQ) e a dobra/delay/reverb "
                                 "vêm depois.\nNo fim: depois de toda a cadeia (ex.: um reverb próprio).")
        self.plug_pos.currentIndexChanged.connect(lambda i: self._track_param("plug_pos", float(i)))
        self._register(ctrl_id("track", "plug_pos"), self.plug_pos)
        lay.addWidget(self.plug_pos)
        tip = _small("Ganho: cante forte e ajuste a Entrada (ou o ganho da placa) até o medidor chegar perto do "
                     "amarelo sem acender o CLIP. Microfonia: abaixe o Volume ou o retorno, não a Entrada.")
        tip.setWordWrap(True)
        lay.addSpacing(6)
        lay.addWidget(tip)
        lay.addStretch(1)
        return side

    # ------------------------------------------------------------------ trilha
    def track(self):
        return self.engine.tracks["vocal"]

    def control_ids(self):
        """Identificadores estáveis de todos os controles da aba (para o mapeamento MIDI)."""
        return list(self.controls_by_id)

    def _open_fx(self):
        win = self.window()
        if hasattr(win, "open_fx"):
            win.open_fx("track", "vocal")

    def set_compact(self, on):
        """Barra inferior aberta: a curva sai da tela (sobra altura para os pedais)."""
        self.curve.setVisible(not on)

    def _switch(self, key, on):
        self.track().set_switch(key, on)
        self._update_mute_label()
        self._style_buttons()
        win = self.window()
        dock = getattr(win, "dock", None)
        if dock is not None:
            dock.refresh_levels()

    def _track_param(self, key, value):
        self.track().set_param("track", key, value)
        self._update_mute_label()
        if key == "volume":
            dock = getattr(self.window(), "dock", None)
            if dock is not None:
                dock.refresh_levels()

    def _update_mute_label(self):
        v = self.track().values["track"]
        if not v["on"]:
            txt = "Microfone desligado (ligue no botão acima)"
        elif v["mute"]:
            txt = "⚠ voz no MUDO"
        elif v["volume"] <= -59.9:
            txt = "⚠ trilha muda (volume no mínimo)"
        else:
            txt = ""
        self.mute_label.setText(txt)
        self.mute_label.setObjectName("small" if not v["on"] else "bad")
        self.mute_label.style().unpolish(self.mute_label)
        self.mute_label.style().polish(self.mute_label)
        self.mute_label.setVisible(bool(txt))

    def _style_buttons(self):
        v = self.track().values["track"]
        self.mute_btn.setText("MUDO" if v["mute"] else "Mudo")
        self.mute_btn.setStyleSheet(TOGGLE_ON if v["mute"] else "")
        self.phase_btn.setStyleSheet(TOGGLE_PHASE_ON if v["phase"] else "")

    def _sync_delay_time(self):
        dl = self.panel_by_key["delay"]
        free = dl.controls["sync"].currentIndex() == 0
        dl.controls["time"].setEnabled(free)
        dl.controls["time"].setToolTip("Tempo do delay em ms" if free else
                                       f"Seguindo o BPM do app: {self.track().delay_ms():.0f} ms agora")

    def refresh(self):
        v = self.track().values["track"]
        for w, key in ((self.enabled, "on"), (self.mute_btn, "mute"), (self.phase_btn, "phase")):
            w.blockSignals(True)
            w.setChecked(bool(v[key]))
            w.blockSignals(False)
        for key, k in self.track_knobs.items():
            k.setValue(v[key])
        self.plug_pos.blockSignals(True)
        self.plug_pos.setCurrentIndex(int(round(v.get("plug_pos", 0))))
        self.plug_pos.blockSignals(False)
        for p in self.panels:
            p.refresh()
        self._sync_delay_time()
        self._update_mute_label()
        self._style_buttons()
        self.curve.sync(force=True)
        self._update_warning()

    def _update_warning(self):
        e = self.engine
        msgs = []
        t = self.track()
        if t.on and e.running:
            cfg = e.config
            note = latency_note(cfg.blocksize, e.fs)
            if note:
                msgs.append(note)
            if not cfg.input_device:
                msgs.append("Sem entrada de áudio escolhida: escolha a placa do microfone em ⚙ Áudio.")
            elif not e.vocal_channel_ok():
                msgs.append(f"O canal {e.input_channel.get('vocal', 0) + 1} do microfone não existe nesta "
                            "entrada: escolha outro em ⚙ Áudio → Canal do vocal.")
        txt = "\n".join(msgs)
        if txt != self.warn_label.text():
            self.warn_label.setText(txt)
        self.warn_label.setVisible(bool(txt))

    def _set_clip(self, on):
        self.clip_label.setStyleSheet(
            f"background: {C['red']}; color: white; font-weight: 800; font-size: 7.5pt; border-radius: 4px;"
            if on else f"background: {C['card']}; color: {C['faint']}; font-weight: 700; font-size: 7.5pt; "
                       f"border: 1px solid {C['border2']}; border-radius: 4px;")

    def update_meters(self):
        t = self.track()
        pin, pout = t.meters()
        gr, ds, gate_open, clip = t.dyn_meters()
        self.m_in.push(pin)
        self.m_out.push(pout)
        now = time.monotonic()
        if clip:
            self._clip_until = now + CLIP_HOLD_S
        lit = now < self._clip_until
        if lit != getattr(self, "_clip_lit", None):
            self._clip_lit = lit
            self._set_clip(lit)
        if self.isVisible():
            self.comp_gr.push(gr)
            self.deess_gr.push(ds)
            if pin > SIGNAL_FLOOR:
                self._signal_at = now
            # microfone desligado ou sem sinal: nada aceso (o "aberto" verde sem voz confundia)
            live = t.on and e_running(self) and now - getattr(self, "_signal_at", -1e9) < SIGNAL_HOLD_S
            if not t.values["gate"]["on"] or not t.on:
                txt, color = "", C["dim"]
            elif not live:
                txt, color = "sem sinal", C["faint"]
            else:
                txt, color = ("aberto", C["green"]) if gate_open else ("fechado", C["dim"])
            if (txt, color) != getattr(self, "_gate_shown", None):
                self._gate_shown = (txt, color)
                self.gate_state.setText(txt)
                self.gate_state.setStyleSheet(f"color: {color};")
            self._tick += 1
            if self._tick % 10 == 0:
                self.curve.sync()
                self._update_warning()
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
            i = find_data(self.preset, select)
            if i >= 0:
                self.preset.setCurrentIndex(i)
        self.preset.blockSignals(False)

    def apply_preset_data(self, data):
        """Preset de voz: efeitos e plugins. Liga/desliga, mudo, volume e ganho de entrada não mudam."""
        data = data if isinstance(data, dict) else {}
        keep = dict(self.track().values["track"])
        values = dict(data.get("values", {})) if isinstance(data.get("values"), dict) else {}
        values["track"] = keep
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.track().load_state({"values": values, "fx_chain": data.get("fx_chain", [])})
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()

    def apply_preset_part(self, data, part):
        """A Vocal não tem amplificador: "fx" (ou qualquer parte) é o preset inteiro."""
        self.apply_preset_data(data)

    def _load_preset(self, _):
        d = self.preset.currentData()
        if not d:
            return
        kind, n = d
        data = FACTORY[self.name].get(n) if kind == "factory" else storage.load_user_preset(self.name, n)
        if data:
            self.apply_preset_data(data)

    def preset_step(self, d):
        n = self.preset.count()
        if n:
            self.preset.setCurrentIndex((self.preset.currentIndex() + d) % n)
            self._load_preset(self.preset.currentIndex())

    def load_preset(self, kind, n):
        i = find_data(self.preset, (kind, n))
        if i >= 0:
            self.preset.setCurrentIndex(i)
            self._load_preset(i)

    def preset_data(self):
        data = self.track().get_state()
        data["values"].pop("track", None)
        return data

    def save_preset(self):
        n, ok = QInputDialog.getText(self, "Salvar preset", "Nome do preset de voz:")
        if not ok or not n.strip():
            return None
        return self.save_preset_as(n)

    def save_preset_as(self, name):
        n = (name or "").strip()
        if not n:
            return None
        storage.save_user_preset(self.name, n, self.preset_data())
        self.reload_presets(select=("user", storage._safe(n)))
        return n

    def delete_user_preset(self, n):
        if QMessageBox.question(self, "Excluir preset", f"Excluir o preset “{n}”?") == QMessageBox.Yes:
            storage.delete_user_preset(self.name, n)
            self.reload_presets()
            return True
        return False

