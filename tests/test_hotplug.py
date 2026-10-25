"""Aparelho conectado com o app aberto: o AmpSim pergunta se usa a saída dele e abre o MIDI."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import pytest  # noqa: E402

from ampsim.audio.hotplug import DeviceWatcher, audio_outputs, match_output  # noqa: E402

PA_NAMES = ["Alto-falantes (Realtek(R) Audio)", "Alto-falantes (M-VAVE SMK-25 Audio Interface)",
            "CABLE Input (VB-Audio Virtual Cable)"]


def test_match_output_with_truncated_winmm_name():
    # o winmm corta em 31 letras
    assert match_output("Alto-falantes (M-VAVE SMK-25 Au", PA_NAMES) == PA_NAMES[1]
    assert match_output("CABLE Input (VB-Audio Virtual C", PA_NAMES) == PA_NAMES[2]
    assert match_output("Fone Bluetooth", PA_NAMES) is None
    assert match_output("", PA_NAMES) is None


def test_watcher_reports_only_new_devices():
    outs = [["Realtek"]]
    midis = [[]]
    w = DeviceWatcher(lambda: outs[0], lambda: midis[0])
    assert w.poll() == ([], [])                       # 1ª leitura só guarda
    assert w.poll() == ([], [])
    outs[0] = ["Realtek", "M-VAVE SMK-25"]
    midis[0] = ["SMK-25"]
    assert w.poll() == (["M-VAVE SMK-25"], ["SMK-25"])
    assert w.poll() == ([], [])                       # já conhecido: não repete
    outs[0] = ["Realtek"]                             # desconectou
    assert w.poll() == ([], [])
    outs[0] = ["Realtek", "M-VAVE SMK-25"]            # conectou de novo: avisa de novo
    assert w.poll() == (["M-VAVE SMK-25"], [])


def test_real_windows_list_is_readable():
    assert isinstance(audio_outputs(), list)


@pytest.fixture()
def win(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ampsim import storage
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "presets")
    monkeypatch.setattr(storage, "SHARE_DIR", tmp_path / "share")
    from ampsim.audio.engine import AudioEngine
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    w.hotplug_timer.stop()
    yield w
    w.timer.stop()
    w.close()
    app.processEvents()


def _fake_devices(win, outs, midis):
    win.watcher = DeviceWatcher(lambda: outs[0], lambda: midis[0])
    win.watcher.poll()


def test_new_output_asks_and_opens_audio_setup(win, monkeypatch):
    outs, midis = [["Realtek"]], [[]]
    _fake_devices(win, outs, midis)
    asked, opened = [], []
    monkeypatch.setattr(win, "ask_use_output", lambda name: asked.append(name) or True)
    monkeypatch.setattr(win, "open_audio_dialog", lambda suggest_output=None: opened.append(suggest_output))
    outs[0] = ["Realtek", "Alto-falantes (M-VAVE SMK-25 Au"]
    win.check_new_devices()
    assert asked == ["Alto-falantes (M-VAVE SMK-25 Au"]
    assert opened == ["Alto-falantes (M-VAVE SMK-25 Au"]


def test_declined_output_is_not_asked_again(win, monkeypatch):
    outs, midis = [["Realtek"]], [[]]
    _fake_devices(win, outs, midis)
    asked = []
    monkeypatch.setattr(win, "ask_use_output", lambda name: asked.append(name) or False)
    outs[0] = ["Realtek", "M-VAVE"]
    win.check_new_devices()
    outs[0] = ["Realtek"]
    win.check_new_devices()
    outs[0] = ["Realtek", "M-VAVE"]
    win.check_new_devices()
    assert asked == ["M-VAVE"]


def test_new_midi_keyboard_opens_when_none_selected(win, monkeypatch):
    outs, midis = [[]], [[]]
    _fake_devices(win, outs, midis)

    class FakeMidi:
        name = None

        def open(self, name):
            self.name = name

        def close(self):
            self.name = None
    win.midi = FakeMidi()
    monkeypatch.setattr("ampsim.midi.winmm.list_inputs", lambda: midis[0])
    midis[0] = ["SMK-25"]
    win.check_new_devices()
    assert win.midi.name == "SMK-25"
    assert win.dock.midi_combo.currentText() == "SMK-25"


def test_audio_dialog_preselects_the_new_device(win, monkeypatch):
    from ampsim.audio import devices as dev
    from ampsim.ui.audio_dialog import AudioDialog
    real = [d for api in dev.hostapis() for d in dev.devices(api, "output")]
    if not any(api == "Windows WASAPI" for api in dev.hostapis()) or not real:
        pytest.skip("sem WASAPI neste computador")
    target = dev.devices("Windows WASAPI", "output")[-1].name
    dlg = AudioDialog(win.engine, win, suggest_output=target[:31])
    assert dlg.api.currentText() == "Windows WASAPI"
    assert dlg.out.currentText() == target
    dlg.reject()


def test_known_instruments_by_name():
    from ampsim.audio.hotplug import find_instrument_output, instrument_of
    assert instrument_of("Alto-falantes (M-VAVE SMK-25 Au") == "M-VAVE SMK-25"
    assert instrument_of("Digital Keyboard (PSR-E473)") == "Yamaha PSR-E473"
    assert instrument_of("OUT (VR-730)") == "Roland VR-730"
    assert instrument_of("Alto-falantes (Realtek(R) Audio") is None
    outs = ["Realtek", "OUT (VR-730)", "Digital Keyboard (PSR-E473)"]
    assert find_instrument_output(outs, prefer="Yamaha PSR-E473") == ("Yamaha PSR-E473", outs[2])
    assert find_instrument_output(outs) == ("Roland VR-730", outs[1])
    assert find_instrument_output(["Realtek"]) == (None, None)


def test_use_instrument_output_button(win, monkeypatch):
    import ampsim.ui.main_window as mw
    opened = []
    monkeypatch.setattr(win, "use_new_output", lambda name: opened.append(name))
    monkeypatch.setattr(mw, "audio_outputs", lambda: ["Realtek", "OUT (VR-730)", "Digital Keyboard (PSR-E473)"])
    win.inst.device = "Yamaha PSR-E473"                    # desenho na tela = PSR: prefere ele
    assert win.use_instrument_output()
    assert opened == ["Digital Keyboard (PSR-E473)"]
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: opened.append("ajuda")))
    monkeypatch.setattr(mw, "audio_outputs", lambda: ["Realtek"])
    assert not win.use_instrument_output()
    assert opened[-1] == "ajuda"
    from PySide6.QtWidgets import QPushButton
    assert any("saída do teclado" in b.text() for b in win.dock.findChildren(QPushButton))


def test_hotplug_question_names_the_instrument(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    win.ask_use_output("OUT (VR-730)")
    assert "Roland VR-730" in shown[0]
