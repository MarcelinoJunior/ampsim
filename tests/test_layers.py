"""Camadas das teclas: cada uma com os seus efeitos (rotação, drive, delay) e até 4 camadas."""
import numpy as np
import pytest

from ampsim.audio.engine import AudioEngine
from ampsim.audio.soundfont import available
from ampsim.dsp.keysfx import HORN_FAST, HORN_SLOW, K_ROT_HZ, ROT_MULTS, rotation_hz
from ampsim.dsp.kernels import warmup
from ampsim.instruments import CH_LAYERS, DEFAULT_FX, MAX_LAYERS, channel_routes, clean_layer

needs_sf = pytest.mark.skipif(not available(), reason="timbres não baixados (tools/baixar_extras.py)")
N = 128


@pytest.fixture()
def engine():
    warmup()
    e = AudioEngine()
    e.tracks["pads"].set_param("track", "use_amp", False)    # como no app: teclas com os próprios efeitos
    return e


def render(e, notes, secs=0.6):
    inst = e.instruments
    for n in notes:
        inst.key_on(n, 100)
    out = np.zeros((N, 2), np.float32)
    buf = []
    for _ in range(int(48000 * secs / N)):
        e._render(None, out, N)
        buf.append(out.copy())
    for n in notes:
        inst.key_off(n)
    for _ in range(int(48000 * 5.0 / N)):           # deixa a cauda (reverb) acabar antes do próximo
        e._render(None, out, N)
    return np.concatenate(buf)


def test_each_layer_has_its_own_output_route():
    from ampsim.audio.soundfont import N_FX_GROUPS, N_GROUPS
    from ampsim.instruments import CH_CPAD, PAD_CHANNELS, ROUTE_DRUMS, ROUTE_PAD

    r = channel_routes()
    assert len(r) == N_GROUPS == N_FX_GROUPS == 8           # 16 saídas picotavam o som (CPU)
    for i, ch in enumerate(CH_LAYERS):
        assert r[ch % N_GROUPS] == i
    assert all(r[ch % N_GROUPS] == ROUTE_PAD for ch in CH_CPAD)
    assert all(r[ch % N_GROUPS] == ROUTE_DRUMS for ch in PAD_CHANNELS)
    assert len(set(CH_LAYERS)) == MAX_LAYERS == 4


def test_rotation_speed_free_and_bpm():
    fx = dict(DEFAULT_FX)
    assert rotation_hz(fx, 100) == HORN_SLOW
    fx["rot_fast"] = True
    assert rotation_hz(fx, 100) == HORN_FAST
    fx["rot_fast_hz"] = 3.0
    assert rotation_hz(fx, 100) == 3.0
    fx.update(rot_sync=True, rot_fast_mult=2.0)
    assert rotation_hz(fx, 120) == pytest.approx(4.0)          # 120 BPM = 2 tempos/s x 2 voltas
    fx["rot_fast"] = False
    assert rotation_hz(fx, 120) == pytest.approx(1.0)          # lenta: 0,5 volta por tempo
    assert 4.0 in ROT_MULTS


def test_rotation_follows_bpm_changes(engine):
    inst = engine.instruments
    inst.fx.update(rot_on=True, rot_sync=True, rot_fast=True, rot_fast_mult=4.0)
    inst.set_bpm(90)
    assert engine.keys_fx[0].KP[K_ROT_HZ] == pytest.approx(6.0)
    inst.set_bpm(60)
    assert engine.keys_fx[0].KP[K_ROT_HZ] == pytest.approx(4.0)


@needs_sf
def test_effects_only_change_their_own_layer(engine):
    """Drive e rotação no máximo só na camada 1 (mão direita): a mão esquerda (camada 2) não muda.

    A mesma nota tocada duas vezes no FluidSynth já varia um pouco (~2% do pico); essa é a
    referência. Controle positivo: o mesmo drive na própria camada 2 muda muito a mão esquerda.
    """
    inst = engine.instruments
    inst.set_ready("Baixo | Piano (divisão em C3)")
    inst.apply_knob_func("Chorus", 0)        # o LFO do chorus anda com o tempo
    render(engine, [])
    a = render(engine, [40])
    b = render(engine, [40])
    natural = np.abs(a - b).max()
    peak = np.abs(a).max()
    assert peak > 0.01
    clean_right = render(engine, [64])
    inst.fx_layer = 0
    inst.fx.update(drive_on=True, drive=100, rot_on=True, rot_fast=True)
    inst.apply_fx()
    assert not inst.layer_fx[1]["drive_on"]
    left = render(engine, [40])
    right = render(engine, [64])
    assert np.abs(left - b).max() < max(2.5 * natural, 0.01 * peak)       # camada 2 intocada
    assert np.abs(right - clean_right).max() > 0.2 * np.abs(clean_right).max()   # camada 1 mudou
    inst.fx_layer = 1                                                        # controle positivo
    inst.fx.update(drive_on=True, drive=100)
    inst.apply_fx()
    left2 = render(engine, [40])
    assert np.abs(left2 - b).max() > 10 * natural


@needs_sf
def test_add_and_remove_layers(engine):
    inst = engine.instruments
    inst.set_ready("Piano Brilhante")
    assert inst.layer_count() == 2
    assert inst.add_layer("Cordas Lentas") == 3
    assert inst.add_layer("Pad Halo") == 4
    assert inst.add_layer("Coral") is None                       # no máximo 4
    chans = {ch for _, ch, _ in inst._targets(60)}
    assert {CH_LAYERS[0], CH_LAYERS[2], CH_LAYERS[3]} <= chans
    inst.set_extra_layer(3, zone="left")                          # cordas só na mão esquerda
    k = inst.keys["split"]
    assert CH_LAYERS[2] in {ch for _, ch, _ in inst._targets(k - 1)}
    assert CH_LAYERS[2] not in {ch for _, ch, _ in inst._targets(k + 5)}
    inst.layer_fx[3]["delay_on"] = True                           # efeito da camada 4
    inst.remove_layer(3)                                          # a 4 vira a 3, com o efeito junto
    assert inst.layer_count() == 3 and inst.extra_layers[0]["sound"] == "Pad Halo"
    assert inst.layer_fx[2]["delay_on"] and not inst.layer_fx[3]["delay_on"]
    peak = np.abs(render(engine, [60])).max()
    assert peak > 0.01


@needs_sf
def test_layers_and_fx_survive_save_and_load(engine):
    inst = engine.instruments
    inst.set_ready("Órgão + Piano")
    assert inst.layer_fx[1]["rot_on"] and not inst.layer_fx[0]["rot_on"]   # rotação só no órgão
    inst.add_layer("Cordas Lentas")
    inst.layer_fx[2].update(delay_on=True, delay_mix=40)
    inst.fx_layer = 2
    st = inst.get_state()
    e2 = AudioEngine()
    e2.instruments.load_state(st)
    i2 = e2.instruments
    assert i2.extra_layers == inst.extra_layers and i2.fx_layer == 2
    assert i2.layer_fx[1]["rot_on"] and i2.layer_fx[2]["delay_mix"] == 40


def test_old_session_with_single_fx_still_loads(engine):
    inst = engine.instruments
    inst.load_state({"fx": {"drive_on": True, "drive": 70, "bogus": 1}})
    assert inst.layer_fx[0]["drive_on"] and inst.layer_fx[0]["drive"] == 70
    assert "bogus" not in inst.layer_fx[0]


def test_clean_layer_rejects_garbage():
    assert clean_layer({"sound": "não existe"}) is None
    assert clean_layer("x") is None
    lay = clean_layer({"sound": "Coral", "vol": 999, "oct": -9, "on": "sim", "zone": "rm"})
    assert lay == dict(sound="Coral", vol=127, oct=-2, on=True, zone="all")
