"""Taxa de amostragem: placas que só aceitam 44,1 kHz (ex.: Yamaha PSR-E473 pelo USB)."""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ampsim.audio import devices as dev  # noqa: E402
from ampsim.audio.engine import AudioEngine  # noqa: E402

OUT = SimpleNamespace(index=30, name="Line (2- Digital Keyboard)", max_out=2)
MIC = SimpleNamespace(index=40, name="Microfone (Iriun Webcam)", max_in=1)


@pytest.fixture()
def engine():
    return AudioEngine()


def fake_rates(table):
    def supported(out_index, in_index=None, rates=dev.SAMPLE_RATES, exclusive=False):
        ok = set(table[out_index])
        if in_index is not None:
            ok &= set(table[in_index])
        return [r for r in rates if r in ok]
    return supported


def test_best_rate():
    assert dev.best_rate([44100, 48000], 96000) == 48000
    assert dev.best_rate([44100], 48000) == 44100
    assert dev.best_rate([], 48000) is None


def test_keyboard_only_44k_adjusts_rate(engine, monkeypatch):
    monkeypatch.setattr(dev, "supported_rates", fake_rates({30: [44100], 40: [44100, 48000]}))
    cfg = dev.AudioConfig(hostapi="Windows WASAPI", output_device=OUT.name, input_device=MIC.name, samplerate=48000)
    new, in_dev = engine._fit_rate(cfg, OUT, MIC)
    assert new.samplerate == 44100 and in_dev is MIC
    assert any("44.100" in n for n in engine.start_notes)


def test_no_common_rate_opens_output_only(engine, monkeypatch):
    monkeypatch.setattr(dev, "supported_rates", fake_rates({30: [44100], 40: [48000]}))
    cfg = dev.AudioConfig(hostapi="Windows WASAPI", output_device=OUT.name, input_device=MIC.name, samplerate=48000)
    new, in_dev = engine._fit_rate(cfg, OUT, MIC)
    assert in_dev is None and new.input_device == "" and new.samplerate == 44100
    assert any("só com a saída" in n for n in engine.start_notes)


def test_supported_rate_is_kept(engine, monkeypatch):
    monkeypatch.setattr(dev, "supported_rates", fake_rates({30: [44100, 48000], 40: [48000]}))
    cfg = dev.AudioConfig(hostapi="Windows WASAPI", output_device=OUT.name, input_device=MIC.name, samplerate=48000)
    new, _ = engine._fit_rate(cfg, OUT, MIC)
    assert new is cfg and engine.start_notes == []


def test_dialog_only_offers_supported_rates_and_prefers_vendor_asio(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ampsim.ui.audio_dialog import AudioDialog
    QApplication.instance() or QApplication([])
    D = dev.Device
    devs = {"ASIO": [D(27, "Yamaha Steinberg USB ASIO", 2, 2, 44100.0)],
            "Windows WASAPI": [D(30, OUT.name, 0, 2, 44100.0), D(40, MIC.name, 1, 0, 48000.0)]}
    monkeypatch.setattr(dev, "hostapis", lambda: ["ASIO", "Windows WASAPI"])
    monkeypatch.setattr(dev, "devices", lambda api, kind: [d for d in devs.get(api, [])
                                                         if (d.max_out if kind == "output" else d.max_in)])
    monkeypatch.setattr(dev, "supported_rates", fake_rates({27: [44100], 30: [44100], 40: [48000]}))
    e = AudioEngine()
    e.config = dev.AudioConfig(hostapi="Windows WASAPI", output_device=OUT.name, samplerate=48000)
    dlg = AudioDialog(e, suggest_output="Line (2- Digital Keyboard)")
    assert dlg.api.currentText() == "ASIO" and dlg.out.currentText().startswith("Yamaha")
    dlg._update_rates()
    assert dlg.sr.currentData() == 44100
    model = dlg.sr.model()
    assert not model.item(dlg.sr.findData(48000)).isEnabled()
    dlg.reject()
