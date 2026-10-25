"""Teclas & Pads: roteamento de notas, divisão, mapeamento e áudio do FluidSynth."""
import numpy as np
import pytest

from ampsim.audio.engine import AudioEngine
from ampsim.audio.soundfont import available
from ampsim.dsp.kernels import warmup
from ampsim.instruments import READY, SOUND_BY_NAME

pytestmark = pytest.mark.skipif(not available(), reason="timbres não baixados (tools/baixar_extras.py)")


@pytest.fixture(scope="module")
def engine():
    warmup()
    return AudioEngine()


def render(e, seconds, n=128):
    out = np.zeros((n, 2), np.float32)
    peak = 0.0
    for _ in range(int(48000 * seconds / n)):
        e._render(None, out, n)
        peak = max(peak, float(np.abs(out).max()))
    return peak


def test_every_ready_sound_plays(engine):
    inst = engine.instruments
    for name in READY:
        inst.set_ready(name)
        for k in (48, 60, 67):
            inst.key_on(k, 100)
        peak = render(engine, 0.3)
        inst.all_off()
        render(engine, 0.2)
        assert 0.02 < peak < 1.0, name


def test_split_routes_low_notes_to_layer2(engine):
    inst = engine.instruments
    inst.set_ready("Baixo | Piano (divisão em C3)")
    low = inst._targets(40)
    high = inst._targets(64)
    assert [s.name for s, _ in low] == ["Baixo Finger"]
    assert [s.name for s, _ in high] == ["Piano de Cauda"]


def test_pads_play_drums_without_keys(engine):
    inst = engine.instruments
    inst.all_off()
    render(engine, 0.5)
    for i in range(8):
        inst.pad_hit(i, 120)
    assert render(engine, 0.3) > 0.05


def test_learning_maps_pad_and_knob(engine):
    inst = engine.instruments
    inst.start_learning(("pads", "knobs"))
    inst.handle_midi(0x99, 44, 100)            # pad 1 envia nota 44 no canal 10
    assert inst.mapping["pads"][0] == [9, 44]
    for i in range(1, 8):
        inst.skip_learning_step()
    inst.handle_midi(0xB0, 70, 10)             # knob 1 envia CC70
    inst.handle_midi(0xB0, 70, 11)             # resto do giro: ignorado
    inst.handle_midi(0xB0, 71, 12)             # knob 2
    assert inst.mapping["knobs"][:2] == [[0, 70], [0, 71]]
    inst.stop_learning()
    hits = []
    inst.on_pad = lambda i, v: hits.append(i)
    inst.handle_midi(0x99, 44, 90)
    assert hits == [0]
    inst.handle_midi(0xB0, 70, 127)            # knob 1 = Volume teclas
    assert inst.levels["keys"] == 100


def test_keys_through_amp_flag(engine):
    pads = engine.tracks["pads"]
    inst = engine.instruments
    inst.set_ready("Guitarra Limpa (use com amp)")
    for flag in (False, True):
        pads.set_param("track", "use_amp", flag)
        inst.key_on(52, 110)
        assert render(engine, 0.3) > 0.01
        inst.all_off()
        render(engine, 0.2)
    pads.set_param("track", "use_amp", False)


def test_state_roundtrip(engine):
    inst = engine.instruments
    inst.set_ready("Rhodes + Pad")
    inst.knob_funcs[0] = "Reverb"
    st = inst.get_state()
    inst.set_ready("Piano Brilhante")
    inst.load_state(st)
    assert inst.ready == "Rhodes + Pad" and inst.knob_funcs[0] == "Reverb"
    assert SOUND_BY_NAME[inst.keys["sound1"]].name == "Rhodes com Chorus"
