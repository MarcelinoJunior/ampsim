"""Testes offline do DSP (sem placa de som): estabilidade, níveis e desempenho."""
import os
import time

import numpy as np
import pytest

from ampsim.dsp import layout as Ly
from ampsim.dsp.kernels import process_track, render_synth, warmup, write_output
from ampsim.dsp.params import AMP_MODELS, CAB_CHOICES, EFFECTS
from ampsim.dsp.synth import SYNTH_PRESETS, SynthDSP
from ampsim.dsp.track import TrackDSP

FS = 48000.0
BLOCK = 64


@pytest.fixture(scope="module", autouse=True)
def compiled():
    warmup(FS)


def run(track, signal, block=BLOCK):
    from ampsim.dsp.kernels import process_post, process_pre

    n = len(signal)
    src = signal.astype(np.float32).reshape(-1, 1)
    out = np.zeros((n, 2))
    mix = np.zeros((block, 2))
    for i in range(0, n - block + 1, block):
        if track.external_active():
            process_pre(src[i:i + block], 0, block, *track.pre_arrays)
            track.run_external(track.W[0], block)
            process_post(block, mix, *track.post_arrays)
        else:
            process_track(src[i:i + block], 0, block, mix, *track.arrays)
        out[i:i + block] = mix
        mix[:] = 0
    return out


def guitar_signal(seconds=1.0, amp=0.3):
    t = np.arange(int(FS * seconds)) / FS
    env = np.exp(-t * 2.0)
    x = sum(np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate((82.4, 164.8, 247.0, 329.6)))
    return amp * env * x / 2.0


@pytest.mark.parametrize("model", range(len(AMP_MODELS)))
@pytest.mark.parametrize("cab", range(len(CAB_CHOICES) - 1))
def test_amp_cab_finite_and_bounded(model, cab):
    t = TrackDSP(FS)
    for e in EFFECTS:
        t.set_on(e.key, True)
    t.set_param("amp", "model", model)
    t.set_param("amp", "gain", 10)
    t.set_param("cab", "model", cab)
    y = run(t, guitar_signal(0.5))
    assert np.all(np.isfinite(y))
    peak = np.abs(y).max()
    assert 0.01 < peak < 8.0, peak


def test_bypass_is_transparent():
    t = TrackDSP(FS)
    x = guitar_signal(0.2)
    y = run(t, x)
    n = len(y)
    assert np.allclose(y[:, 0], x[:n], atol=1e-6)
    assert np.allclose(y[:, 1], x[:n], atol=1e-6)


def test_ir_convolution_matches_numpy():
    t = TrackDSP(FS)
    rng = np.random.default_rng(1)
    ir = rng.standard_normal(300) * np.exp(-np.arange(300) / 60.0)
    t.values["cab"]["model"] = len(CAB_CHOICES) - 1
    t.set_cab_ir(ir)
    t.set_on("cab", True)
    assert t.D[Ly.CAB_MODE] == 1.0
    x = rng.standard_normal(4096) * 0.1
    y = run(t, x)[:, 0]
    ir_used = t.IR[: int(t.D[Ly.CAB_IRLEN])]
    ref = np.convolve(x, ir_used)[: len(y)]
    assert np.allclose(y, ref, atol=1e-5)


def test_reverb_tail_decays_and_no_denormal_stall():
    t = TrackDSP(FS)
    t.set_on("reverb", True)
    t.set_on("delay", True)
    x = np.zeros(int(FS * 12))
    x[:100] = 0.5
    y = run(t, x)
    assert np.all(np.isfinite(y))
    assert np.abs(y[-4800:]).max() < 1e-3


@pytest.mark.parametrize("preset", list(SYNTH_PRESETS))
def test_synth_presets(preset):
    s = SynthDSP(FS)
    s.apply_preset(preset)
    out = np.zeros((BLOCK, 1), dtype=np.float32)
    ev = np.zeros((16, 3), dtype=np.int32)
    chunks = []
    for blk in range(int(FS * 1.5) // BLOCK):
        nev = 0
        if blk == 0:
            for k, note in enumerate((60, 64, 67, 71)):
                ev[k] = (Ly.EV_NOTE_ON, note, 100)
            nev = 4
        if blk == int(FS * 0.8) // BLOCK:
            for k, note in enumerate((60, 64, 67, 71)):
                ev[k] = (Ly.EV_NOTE_OFF, note, 0)
            nev = 4
        render_synth(out, BLOCK, ev, nev, s.SD, s.VS, s.SST, FS)
        chunks.append(out[:, 0].copy())
    y = np.concatenate(chunks)
    assert np.all(np.isfinite(y))
    assert 0.005 < np.abs(y).max() < 2.0


def test_voice_stealing_never_crashes():
    s = SynthDSP(FS)
    out = np.zeros((BLOCK, 1), dtype=np.float32)
    ev = np.zeros((40, 3), dtype=np.int32)
    for k in range(40):
        ev[k] = (Ly.EV_NOTE_ON, 30 + k, 90)
    render_synth(out, BLOCK, ev, 40, s.SD, s.VS, s.SST, FS)
    assert int(s.VS[:, Ly.V_ACTIVE].sum()) == Ly.MAX_VOICES


def test_output_limiter():
    mix = np.full((BLOCK, 2), 5.0)
    out = np.zeros((BLOCK, 4), dtype=np.float32)
    write_output(mix, BLOCK, out, 2, 1.0)
    assert np.all(np.abs(out[:, 2:]) <= 1.0)
    assert np.all(out[:, :2] == 0)
    assert np.all(mix == 0)


def test_realtime_budget():
    """Três trilhas com tudo ligado + synth com 16 vozes precisam caber folgado em 64 amostras."""
    tracks = [TrackDSP(FS) for _ in range(3)]
    for t in tracks:
        for e in EFFECTS:
            t.set_on(e.key, True)
        t.set_param("amp", "model", 2)
    s = SynthDSP(FS)
    ev = np.zeros((16, 3), dtype=np.int32)
    for k in range(16):
        ev[k] = (Ly.EV_NOTE_ON, 40 + k, 100)
    so = np.zeros((BLOCK, 1), dtype=np.float32)
    src = (np.random.default_rng(0).standard_normal((BLOCK, 2)) * 0.1).astype(np.float32)
    mix = np.zeros((BLOCK, 2))
    out = np.zeros((BLOCK, 2), dtype=np.float32)
    render_synth(so, BLOCK, ev, 16, s.SD, s.VS, s.SST, FS)
    iters = 300
    t0 = time.perf_counter()
    for _ in range(iters):
        render_synth(so, BLOCK, ev, 0, s.SD, s.VS, s.SST, FS)
        process_track(src, 0, BLOCK, mix, *tracks[0].arrays)
        process_track(src, 1, BLOCK, mix, *tracks[1].arrays)
        process_track(so, 0, BLOCK, mix, *tracks[2].arrays)
        write_output(mix, BLOCK, out, 0, 1.0)
    per_block = (time.perf_counter() - t0) / iters
    budget = BLOCK / FS
    print(f"\nCPU por bloco: {per_block * 1e6:.0f} us de {budget * 1e6:.0f} us "
          f"({100 * per_block / budget:.0f}% da janela)")
    assert per_block < budget * 0.6


def _rms_db(y):
    return 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)


def test_denoise_cuts_amplified_hiss():
    """Chiado de entrada (-60 dB, típico de entrada de microfone USB) num preset com distorção."""
    from ampsim.presets import FACTORY

    hiss = np.random.default_rng(3).standard_normal(int(FS * 2)) * 1e-3
    preset = FACTORY["guitar"]["Crunch Clássico"]["values"]
    off = TrackDSP(FS)
    off.load_state({"values": {k: v for k, v in preset.items() if k not in ("denoise", "gate")}})
    on = TrackDSP(FS)
    on.load_state({"values": preset})
    # o que o botão "Calibrar ruído" faz: limiares 6 dB acima do pico do chiado
    thr = round(20 * np.log10(np.abs(hiss).max()) + 6)
    on.set_param("denoise", "sens", thr)
    on.set_param("gate", "threshold", thr)
    before = _rms_db(run(off, hiss)[int(FS):, 0])
    after = _rms_db(run(on, hiss)[int(FS):, 0])
    print(f"\nchiado amplificado: {before:.1f} dB -> {after:.1f} dB")
    assert after < before - 30


def test_denoise_keeps_playing_signal():
    t = TrackDSP(FS)
    t.set_on("denoise", True)
    x = guitar_signal(1.0, amp=0.3)
    y = run(t, x)[:, 0]
    assert abs(_rms_db(y[:24000]) - _rms_db(x[:24000])) < 1.5


def test_hum_notch():
    t = TrackDSP(FS)
    t.set_on("denoise", True)
    t.set_param("denoise", "hiss", 0)
    tt = np.arange(int(FS * 2)) / FS
    hum = 0.1 * (np.sin(2 * np.pi * 60 * tt) + 0.5 * np.sin(2 * np.pi * 180 * tt))
    y = run(t, hum)[int(FS):, 0]
    assert _rms_db(y) < _rms_db(hum) - 25


# --------------------------------------------------------------------------- NAM / cadeia dividida
def test_pre_post_equals_full_chain():
    from ampsim.dsp.kernels import process_post, process_pre

    a, b = TrackDSP(FS), TrackDSP(FS)
    for t in (a, b):
        for e in EFFECTS:
            t.set_on(e.key, True)
    x = guitar_signal(0.3).astype(np.float32).reshape(-1, 1)
    mix_a = np.zeros((BLOCK, 2))
    mix_b = np.zeros((BLOCK, 2))
    for i in range(0, len(x) - BLOCK + 1, BLOCK):
        process_track(x[i:i + BLOCK], 0, BLOCK, mix_a, *a.arrays)
        process_pre(x[i:i + BLOCK], 0, BLOCK, *b.pre_arrays)
        process_post(BLOCK, mix_b, *b.post_arrays)
    assert np.allclose(mix_a, mix_b)


def _captures():
    from ampsim.dsp.nam import list_captures

    return list_captures()


@pytest.mark.skipif(not _captures(), reason="capturas não baixadas (tools/baixar_extras.py)")
def test_nam_captures_load_and_behave():
    from ampsim.dsp.nam import NamModel

    t = np.arange(int(FS * 0.5)) / FS
    x = 0.1 * np.sin(2 * np.pi * 220 * t)
    for name, path in _captures().items():
        m = NamModel(path)
        y = x.copy()
        for i in range(0, len(y) - BLOCK + 1, BLOCK):
            m.process(y[i:i + BLOCK], BLOCK)
        seg = y[len(y) // 2:]
        assert np.all(np.isfinite(seg)), name
        assert 1e-4 < np.sqrt(np.mean(seg ** 2)) < 2.0, name
    # amp limpo: a saída precisa seguir a entrada (pesos na ordem certa)
    clean = NamModel(_captures()["Fender Twin Reverb (limpo)"])
    y = x.copy()
    for i in range(0, len(y) - BLOCK + 1, BLOCK):
        clean.process(y[i:i + BLOCK], BLOCK)
    spec = np.abs(np.fft.rfft(y[len(y) // 2:]))
    f = np.fft.rfftfreq(len(y) - len(y) // 2, 1 / FS)
    fund = spec[np.abs(f - 220) < 5].max()
    assert spec[np.abs(f - 440) < 5].max() < fund * 0.05


@pytest.mark.skipif(not _captures(), reason="capturas não baixadas (tools/baixar_extras.py)")
def test_nam_in_track_and_realtime_budget():
    from ampsim.dsp.kernels import process_post, process_pre

    t = TrackDSP(FS)
    t.set_nam_file("Marshall JCM900 Lead")
    t.set_on("nam", True)
    t.set_on("cab", True)
    assert t.nam is not None and t.external_active()
    src = (np.random.default_rng(1).standard_normal((BLOCK, 1)) * 0.1).astype(np.float32)
    mix = np.zeros((BLOCK, 2))
    iters = 400
    t0 = time.perf_counter()
    for _ in range(iters):
        process_pre(src, 0, BLOCK, *t.pre_arrays)
        t.run_external(t.W[0], BLOCK)
        process_post(BLOCK, mix, *t.post_arrays)
    per_block = (time.perf_counter() - t0) / iters
    print(f"\nNAM na trilha: {100 * per_block / (BLOCK / FS):.0f}% da janela de {BLOCK} amostras")
    assert np.all(np.isfinite(mix))
    assert per_block < (BLOCK / FS) * 0.5


def test_factory_presets_load():
    from ampsim.presets import FACTORY

    for kind in ("guitar", "bass", "pads"):
        for name, data in FACTORY[kind].items():
            t = TrackDSP(FS)
            t.load_state(data)
            if data["values"].get("nam", {}).get("file") and _captures():
                assert t.nam is not None, name
            y = run(t, guitar_signal(0.2))
            assert np.all(np.isfinite(y)), name


def test_vst_bad_path_is_reported():
    t = TrackDSP(FS)
    assert t.load_vst(r"C:\nao\existe.vst3") is False
    assert t.vst is None and t.vst_error


NAM_VST3 = r"C:\Program Files\Common Files\VST3\NeuralAmpModeler.vst3"


@pytest.mark.skipif(not os.path.isdir(NAM_VST3), reason="plugin NAM não instalado")
def test_vst3_slot_with_nam_plugin():
    t = TrackDSP(FS)
    assert t.load_vst(NAM_VST3), t.vst_error
    t.set_on("vst", True)
    assert t.external_active()
    y = run(t, guitar_signal(0.3))
    assert np.all(np.isfinite(y)) and t.vst.error is None
    state = t.get_state()
    assert state["values"]["vst"]["state"]
    t2 = TrackDSP(FS)
    t2.load_state(state)
    assert t2.vst is not None and t2.vst.name == t.vst.name
