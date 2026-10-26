"""Saúde do áudio: falhas contadas e visíveis, áudio que cai é religado sozinho, sessão longa estável."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ampsim.audio.engine import AudioEngine  # noqa: E402
from ampsim.dsp.kernels import warmup  # noqa: E402
from ampsim.ui import health  # noqa: E402

N = 128


@pytest.fixture()
def engine():
    warmup()
    return AudioEngine()


class FakeStream:
    def __init__(self, active=True):
        self.active = active


def test_xruns_and_slow_blocks_are_logged(engine, monkeypatch):
    e = engine
    out = np.zeros((N, 2), np.float32)
    e._output_cb(out, N, None, False)
    assert e.xruns == 0
    e._output_cb(out, N, None, True)                          # o driver avisou: faltou som
    assert e.xruns == 1 and e.events[-1][1] == "falha"
    monkeypatch.setattr(e, "fs", 1e9)                          # prazo absurdo: todo bloco fica "lento"
    e._output_cb(out, N, None, False)
    assert e.overloads >= 1 and e.events[-1][1] == "lento"
    monkeypatch.setattr(type(e), "running", property(lambda self: True))
    lv, f, s = health.level(e)
    assert lv == "aviso" and f == 1 and s >= 1
    for _ in range(5):
        e._note_xrun(e.events[-1][0])
    assert health.level(e)[0] == "ruim"
    text, color, _ = health.badge(e)
    assert "falhas" in text and color == health.C["red"]
    assert any("buffer" in t.lower() for t in health.tips(e))
    e.reset_health()
    assert health.level(e)[0] == "ok" and health.badge(e)[0] == "● sem falhas"


def test_old_events_leave_the_minute_window(engine, monkeypatch):
    e = engine
    monkeypatch.setattr(type(e), "running", property(lambda self: True))
    e._note_xrun(100.0)
    assert health.level(e, now=130.0)[0] == "aviso"
    assert health.level(e, now=200.0)[0] == "ok"


def test_lost_stream_detection(engine):
    e = engine
    assert not e.lost
    e.stream = FakeStream(active=False)
    assert e.lost
    e.stream = FakeStream(active=True)
    assert not e.lost
    e.stream = None


def test_long_session_is_stable(engine):
    """~3 min de áudio com teclas, pads, pad contínuo e trocas de timbre: sem erro e sem crescer memória."""
    import tracemalloc
    e, inst = engine, engine.instruments
    out = np.zeros((256, 2), np.float32)
    blocks = int(48000 * 180 / 256)
    tracemalloc.start()
    readies = ["Piano + Pad (culto)", "Órgão Gospel (rotação)", "Rhodes com Delay (balada)"]
    mem = []
    for b in range(blocks):
        if b % 200 == 0:
            inst.key_on(48 + b % 24, 100)
            inst.pad_hit(b % 8, 100)
        if b % 200 == 100:
            inst.key_off(48 + (b - 100) % 24)
        if b % 3000 == 0:
            inst.set_ready(readies[(b // 3000) % 3])
            inst.start_cont_pad("CDEFGAB"[(b // 3000) % 7])
        if b % 6 == 0:
            inst.tick(1 / 30)
        e._render(None, out, 256)
        if b in (blocks // 4, blocks - 1):
            mem.append(tracemalloc.get_traced_memory()[0])
    tracemalloc.stop()
    assert np.isfinite(out).all()
    assert mem[1] - mem[0] < 2_000_000                             # sem vazamento (< 2 MB em ~2 min)
