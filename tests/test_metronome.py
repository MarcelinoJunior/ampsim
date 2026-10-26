"""Metrônomo: batidas no BPM com acento, saída principal ou par separado (fones da banda), sem vazar."""
import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ampsim.audio import devices as dev  # noqa: E402
from ampsim.audio.engine import AudioEngine  # noqa: E402
from ampsim.audio.metronome import Metronome  # noqa: E402
from ampsim.dsp.kernels import warmup  # noqa: E402


def onsets(m, frames, blocks, bpm):
    out = []
    for b in range(blocks):
        m.render(frames, bpm)
        x = np.abs(m.buf[:frames])
        prev = 0.0
        for i, v in enumerate(x):
            if v > 0.02 and prev <= 0.02 and (not out or b * frames + i - out[-1] > 1000):
                out.append(b * frames + i)
            prev = v
    return out


def test_beats_follow_bpm_with_accent():
    m = Metronome(48000, 256)
    m.on = True
    on = onsets(m, 256, int(48000 * 2.05 / 256), 120)           # 120 BPM: uma batida a cada 0,5 s
    assert len(on) == 5 and all(abs((b - a) - 24000) <= 2 for a, b in zip(on, on[1:]))
    m.restart()
    m.render(256, 120)
    assert m.beat == 0                                            # 1º tempo: acento
    assert np.abs(m.waves[0]).max() > np.abs(m.waves[1]).max()
    m.beats = 3
    m.restart()
    accents = []
    for _ in range(int(48000 * 3.1 / 256)):
        before = m.count
        m.render(256, 60)
        if m.count != before:
            accents.append(m.beat)
    assert accents[:4] == [0, 1, 2, 0]
    m.on = False
    assert not m.render(256, 120) and not m.buf[:256].any()


@pytest.fixture()
def engine():
    warmup()
    return AudioEngine()


def render4(e, blocks=200):
    out = np.zeros((128, 4), np.float32)
    peak = np.zeros(4)
    for _ in range(blocks):
        e._render(None, out, 128)
        peak = np.maximum(peak, np.abs(out).max(axis=0))
    return peak


def test_click_goes_only_to_its_own_pair(engine):
    e = engine
    e.metronome.on = True
    e.out_offset, e.click_offset = 0, 2                           # principal 1-2, click 3-4
    p = render4(e)
    assert p[2] > 0.1 and p[3] > 0.1 and p[0] == 0.0 and p[1] == 0.0     # nada vaza para o PA
    e.muted = True                                                # mute geral não corta o click dos fones
    e.metronome.restart()
    assert render4(e)[2] > 0.1
    e.muted = False
    e.click_offset = -1                                           # na saída principal (ensaio)
    e.metronome.restart()
    p = render4(e)
    assert p[0] > 0.1 and p[2] == 0.0
    e.muted = True
    e.metronome.restart()
    assert render4(e, 400)[0] == 0.0                              # mute geral cala o click no PA
    e.muted = False
    e.click_offset = -2                                           # sem saída: não toca em lugar nenhum
    assert not render4(e).any()


def test_stream_opens_the_click_pair(engine, monkeypatch):
    e = engine
    opened = {}

    class FakeStream:
        def __init__(self, **kw):
            opened.update(kw)
            self.active = True
            self.latency = 0.003
            self.cpu_load = 0.0

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass
    card = SimpleNamespace(index=5, name="Placa 4 saídas", max_in=0, max_out=4)
    monkeypatch.setattr(dev, "find_device", lambda api, name, kind: card)
    monkeypatch.setattr(dev, "supported_rates", lambda *a, **k: [48000])
    monkeypatch.setattr("ampsim.audio.engine.sd.OutputStream", FakeStream)
    cfg = dev.AudioConfig(hostapi="ASIO", output_device=card.name, samplerate=48000, click_offset=2)
    e.start(cfg)
    assert opened["channels"] == 4 and e.click_offset == 2 and e.out_offset == 0
    e.stop()
    card2 = SimpleNamespace(index=5, name="Placa 2 saídas", max_in=0, max_out=2)
    monkeypatch.setattr(dev, "find_device", lambda api, name, kind: card2)
    e.start(dev.AudioConfig(hostapi="ASIO", output_device=card2.name, samplerate=48000, click_offset=2))
    assert opened["channels"] == 2 and e.click_offset == -2       # a placa não tem 3-4: click sem saída
    e.stop()
