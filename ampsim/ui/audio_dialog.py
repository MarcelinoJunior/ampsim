"""Diálogo de configuração de áudio: API, dispositivos, taxa, buffer e canais."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout,
)

from ..audio import devices as dev

NO_INPUT = "(nenhuma — só pads)"

API_HINTS = {
    "ASIO": "Menor latência. Use o driver da sua interface ou o ASIO4ALL / FlexASIO.",
    "Windows WASAPI": "Bom sem ASIO. Ative o modo exclusivo para latência baixa.",
    "Windows WDM-KS": "Kernel streaming: latência baixa, mas alguns drivers são instáveis.",
    "Windows DirectSound": "Latência alta — use só se nada mais funcionar.",
    "MME": "Latência alta — use só se nada mais funcionar.",
}


class AudioDialog(QDialog):
    def __init__(self, engine, parent=None, suggest_output=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Configuração de áudio")
        self.setMinimumWidth(520)
        cfg = engine.config
        form = QFormLayout()

        self.api = QComboBox()
        self.api.addItems(dev.hostapis())
        form.addRow("API de áudio:", self.api)
        self.hint = QLabel()
        self.hint.setObjectName("small")
        self.hint.setWordWrap(True)
        form.addRow("", self.hint)

        self.out = QComboBox()
        form.addRow("Saída:", self.out)
        self.inp = QComboBox()
        form.addRow("Entrada:", self.inp)
        self.in_hint = QLabel()
        self.in_hint.setObjectName("warn")
        self.in_hint.setWordWrap(True)
        self.in_hint.setVisible(False)
        form.addRow("", self.in_hint)
        self.out_pair = QComboBox()
        form.addRow("Canais de saída:", self.out_pair)
        self.click_pair = QComboBox()
        self.click_pair.setToolTip("Onde o metrônomo (CLICK) toca. Num par de saídas só dele (ex.: 3-4 ligado nos\n"
                                   "fones da banda) o click não vaza para o PA.")
        form.addRow("Saída do metrônomo:", self.click_pair)
        self.g_ch = QComboBox()
        form.addRow("Canal da guitarra:", self.g_ch)
        self.b_ch = QComboBox()
        form.addRow("Canal do baixo:", self.b_ch)

        self.sr = QComboBox()
        for r in dev.SAMPLE_RATES:
            self.sr.addItem(f"{r} Hz", r)
        form.addRow("Taxa de amostragem:", self.sr)
        self.bs = QComboBox()
        for b in dev.BLOCK_SIZES:
            self.bs.addItem(str(b), b)
        form.addRow("Buffer (amostras):", self.bs)
        self.lat = QLabel()
        self.lat.setObjectName("small")
        form.addRow("", self.lat)
        self.rate_hint = QLabel()
        self.rate_hint.setObjectName("warn")
        self.rate_hint.setWordWrap(True)
        form.addRow("", self.rate_hint)
        self.excl = QCheckBox("WASAPI modo exclusivo (menor latência)")
        form.addRow("", self.excl)

        tools = QHBoxLayout()
        self.asio_btn = QPushButton("Painel do driver ASIO…")
        self.asio_btn.clicked.connect(self._asio_panel)
        refresh = QPushButton("Atualizar dispositivos")
        refresh.clicked.connect(self._refresh)
        tools.addWidget(self.asio_btn)
        tools.addWidget(refresh)
        tools.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Aplicar e iniciar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(tools)
        lay.addWidget(buttons)

        self.api.currentTextChanged.connect(self._api_changed)
        self.out.currentIndexChanged.connect(self._out_changed)
        self.out_pair.currentIndexChanged.connect(lambda *_: self._click_choices())
        self.inp.currentIndexChanged.connect(self._in_changed)
        self.sr.currentIndexChanged.connect(self._update_latency)
        self.excl.toggled.connect(lambda *_: self._update_rates())
        self.bs.currentIndexChanged.connect(self._update_latency)

        if cfg.hostapi in dev.hostapis():
            self.api.setCurrentText(cfg.hostapi)
        self._api_changed(self.api.currentText())
        self._select(self.out, cfg.output_device)
        self._select(self.inp, cfg.input_device or NO_INPUT)
        self._select(self.sr, cfg.samplerate, data=True)
        self._select(self.bs, cfg.blocksize, data=True)
        self.excl.setChecked(cfg.wasapi_exclusive)
        self._out_changed()
        self._in_changed()
        self._select(self.out_pair, cfg.output_offset, data=True)
        self._click_choices(cfg.click_offset)
        self._select(self.g_ch, engine.input_channel["guitar"], data=True)
        self._select(self.b_ch, engine.input_channel["bass"], data=True)
        self._update_rates()
        self._update_latency()
        if suggest_output:
            self.suggest(suggest_output)

    def _after_change(self):
        if getattr(self, "rate_hint", None) is not None and self.out.count():
            QTimer.singleShot(0, self._update_rates)        # depois de os dois combos se acertarem

    def suggest(self, short_name):
        """Aparelho recém-conectado: o ASIO do próprio fabricante se houver (ex.: Yamaha Steinberg
        USB ASIO), senão WASAPI (funciona com qualquer interface USB) com a saída dele."""
        from ..audio.hotplug import instrument_of, match_output

        model = instrument_of(short_name)
        if model and "ASIO" in dev.hostapis():
            for d in dev.devices("ASIO", "output"):
                if instrument_of(d.name) == model:
                    self.api.setCurrentText("ASIO")
                    self._api_changed("ASIO")
                    self._select(self.out, d.name)
                    self.inp.setCurrentIndex(0)             # a entrada do teclado não é guitarra
                    self.hint.setText(f"{model}: usando o driver ASIO do fabricante ({d.name}), o de menor "
                                      "atraso. Confira e clique em “Aplicar e iniciar”.")
                    self._update_rates()
                    return d.name
        keep_in = self.inp.currentText()
        for api in ("Windows WASAPI", self.api.currentText()):
            if api not in dev.hostapis():
                continue
            names = [d.name for d in dev.devices(api, "output")]
            name = match_output(short_name, names)
            if name:
                self.api.setCurrentText(api)
                self._api_changed(api)
                self._select(self.out, name)
                self._select(self.inp, keep_in)
                if self._keyboard_input(self.inp.currentData()):
                    self.inp.setCurrentIndex(0)
                self.hint.setText(f"Aparelho conectado: {name}. Confira e clique em “Aplicar e iniciar”.")
                return name
        return None

    @staticmethod
    def _select(combo, value, data=False):
        i = combo.findData(value) if data else combo.findText(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _api_changed(self, api):
        asio = dev.is_asio(api)
        self.hint.setText(API_HINTS.get(api, ""))
        self.asio_btn.setVisible(asio)
        self.excl.setVisible(api == "Windows WASAPI")
        self.out.blockSignals(True)
        self.out.clear()
        for d in dev.devices(api, "output"):
            self.out.addItem(d.name, d)
        self.out.blockSignals(False)
        self.inp.blockSignals(True)
        self.inp.clear()
        self.inp.addItem(NO_INPUT, None)
        for d in dev.devices(api, "input"):
            self.inp.addItem(d.name, d)
        if self.inp.count() > 1 and not self._keyboard_input(self.inp.itemData(1)):
            self.inp.setCurrentIndex(1)
        self.inp.blockSignals(False)
        self._out_changed()
        self._in_changed()

    def _out_changed(self, *_):
        self._after_change()
        d = self.out.currentData()
        if dev.is_asio(self.api.currentText()) and d is not None and self.inp.currentIndex() != 0:
            # no ASIO entrada e saída precisam ser o mesmo driver
            self._select(self.inp, d.name)
        cur = self.out_pair.currentData()
        self.out_pair.clear()
        n = d.max_out if d else 2
        for off in range(0, max(n - 1, 1), 2):
            self.out_pair.addItem(f"{off + 1}-{off + 2}" if off + 1 < n else f"{off + 1}", off)
        self._select(self.out_pair, cur, data=True)
        self._click_choices()

    def _click_choices(self, keep=None):
        """Metrônomo: nenhuma saída, a principal (vai para o PA) ou um par livre da placa."""
        if not hasattr(self, "click_pair"):
            return
        keep = self.click_pair.currentData() if keep is None else keep
        d = self.out.currentData()
        n = d.max_out if d else 2
        main = self.out_pair.currentData() or 0
        self.click_pair.blockSignals(True)
        self.click_pair.clear()
        self.click_pair.addItem("Nenhuma (o click não toca)", -2)
        self.click_pair.addItem("Saída principal (vai junto para o PA)", -1)
        for off in range(0, n - 1, 2):
            if off != main:
                self.click_pair.addItem(f"Saídas {off + 1}-{off + 2} (ex.: fones da banda)", off)
        i = self.click_pair.findData(keep)
        self.click_pair.setCurrentIndex(i if i >= 0 else 0)
        self.click_pair.blockSignals(False)

    @staticmethod
    def _keyboard_input(d):
        from ..audio.hotplug import is_keyboard_audio
        return d is not None and is_keyboard_audio(d.name)

    def _in_changed(self, *_):
        self._after_change()
        d = self.inp.currentData()
        kb = self._keyboard_input(d)
        self.in_hint.setVisible(kb or (d is not None and "asio4all" in d.name.lower()))
        if kb:
            self.in_hint.setText("Esta entrada é o som do próprio teclado: como guitarra/baixo faz microfonia. "
                                 "O AmpSim vai abrir sem ela. Escolha “nenhuma”.")
        elif self.in_hint.isVisible():
            self.in_hint.setText("ASIO4ALL: se a entrada ligada no painel dele for o teclado, escolha “nenhuma” "
                                 "aqui (senão o som do teclado volta pela guitarra/baixo e faz microfonia).")
        if dev.is_asio(self.api.currentText()) and d is not None and d.name != self.out.currentText():
            self._select(self.out, d.name)
        n = d.max_in if d else 0
        for combo, default in ((self.g_ch, 0), (self.b_ch, min(1, max(n - 1, 0)))):
            cur = combo.currentData()
            combo.clear()
            for c in range(n):
                combo.addItem(f"Entrada {c + 1}", c)
            combo.setEnabled(d is not None)
            self._select(combo, default if cur is None else cur, data=True)

    def _update_rates(self):
        """Só deixa escolher as taxas que a saída e a entrada aceitam juntas."""
        out, inp = self.out.currentData(), self.inp.currentData()
        if out is None:
            return
        excl = self.api.currentText() == "Windows WASAPI" and self.excl.isChecked()
        ok = dev.supported_rates(out.index, inp.index if inp is not None else None, exclusive=excl)
        if not ok and inp is not None:
            ok_out = dev.supported_rates(out.index, None, exclusive=excl)
            self.rate_hint.setText("Esta entrada e esta saída não têm taxa em comum: escolha outra entrada "
                                   "(ou “sem entrada”)." if ok_out else "")
        else:
            self.rate_hint.setText("")
        model = self.sr.model()
        for i in range(self.sr.count()):
            item = model.item(i) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(not ok or self.sr.itemData(i) in ok)
        if ok and self.sr.currentData() not in ok:
            self._select(self.sr, dev.best_rate(ok, self.sr.currentData()), data=True)

    def _update_latency(self, *_):
        sr = self.sr.currentData() or 48000
        bs = self.bs.currentData() or 128
        ms = bs / sr * 1000
        self.lat.setText(f"{ms:.1f} ms por buffer · ida e volta ≈ {2 * ms:.1f} ms + latência do conversor")

    def _refresh(self):
        self.engine.stop()
        dev.refresh()
        self._api_changed(self.api.currentText())

    def _asio_panel(self):
        d = self.out.currentData()
        if d is None:
            return
        self.engine.stop()
        try:
            dev.show_asio_panel(d.index)
        except Exception as exc:  # noqa: BLE001 - driver de terceiros
            QMessageBox.warning(self, "ASIO", f"Não foi possível abrir o painel:\n{exc}")

    def result_config(self):
        d_in = self.inp.currentData()
        d_out = self.out.currentData()
        cfg = dev.AudioConfig(
            hostapi=self.api.currentText(),
            input_device=d_in.name if d_in else "",
            output_device=d_out.name if d_out else "",
            samplerate=self.sr.currentData(),
            blocksize=self.bs.currentData(),
            wasapi_exclusive=self.excl.isChecked(),
            output_offset=self.out_pair.currentData() or 0,
            click_offset=self.click_pair.currentData() if self.click_pair.currentData() is not None else -2,
        )
        channels = {"guitar": self.g_ch.currentData() or 0, "bass": self.b_ch.currentData() or 0}
        return cfg, channels
