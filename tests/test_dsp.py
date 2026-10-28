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


def test_output_limiter_lowers_volume_instead_of_distorting():
    """Pad alto + piano passando do teto: o limitador abaixa o volume, sem cortar os picos
    (o corte de cada pico é o que soava como chiado no alto-falante)."""
    from ampsim.dsp.kernels import limiter_state, write_output_lim
    fs = 48000
    t = np.arange(fs) / fs
    sig = 2.0 * np.sin(2 * np.pi * 220 * t)              # o dobro do que cabe
    lim = limiter_state(fs)
    out = np.zeros((fs, 2), dtype=np.float32)
    for i in range(0, fs, BLOCK):
        mix = np.stack([sig[i:i + BLOCK]] * 2, axis=1).astype(np.float64)
        write_output_lim(mix, len(mix), out[i:i + BLOCK], 0, 1.0, lim)
    y = out[fs // 10:, 0].astype(np.float64)              # depois do primeiro pico
    assert np.abs(out).max() <= 0.9 + 1e-3
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    f = np.fft.rfftfreq(len(y), 1 / fs)
    fund = spec[np.abs(f - 220) < 5].max()
    harm = sum(spec[np.abs(f - 220 * k) < 5].max() ** 2 for k in range(2, 10)) ** 0.5
    assert harm / fund < 0.01, harm / fund                # menos de 1% de distorção
    assert lim[2] < 0.5                                    # e registrou o quanto abaixou
    # sinal normal passa intacto
    lim = limiter_state(fs)
    mix = np.full((BLOCK, 2), 0.5)
    out = np.zeros((BLOCK, 2), dtype=np.float32)
    write_output_lim(mix, BLOCK, out, 0, 1.0, lim)
    assert np.allclose(out, 0.5) and lim[2] == 1.0


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


@pytest.mark.parametrize("shape", [0, 1, 2])
def test_pulse_has_no_clicks(shape):
    """O pulso no BPM (e o Tap no meio da nota) não pode gerar degraus audíveis (cliques)."""
    s = SynthDSP(FS)
    s.apply_preset("Baixo Pulsante")
    s.set_bpm(80)
    s.values["pulse_shape"] = shape
    s.update_all()
    out = np.zeros((BLOCK, 1), dtype=np.float32)
    ev = np.zeros((4, 3), dtype=np.int32)
    ev[0] = (Ly.EV_NOTE_ON, 36, 110)
    ys = []
    for b in range(int(FS * 3 / BLOCK)):
        if b in (700, 1000):
            s.restart_pulse()
        render_synth(out, BLOCK, ev, 1 if b == 0 else 0, s.SD, s.VS, s.SST, FS)
        ys.append(out[:, 0].astype(float))
    y = np.concatenate(ys)[int(FS * 0.5):]
    d2 = np.abs(np.diff(y, 2))
    assert d2.max() / np.percentile(d2, 99) < 8.0


def _run_output(sig, amount, fs=48000, lim=None):
    from ampsim.dsp.kernels import limiter_state, write_output_lim
    lim = limiter_state(fs) if lim is None else lim
    lim[3] = amount
    out = np.zeros((len(sig), 2), dtype=np.float32)
    for i in range(0, len(sig), BLOCK):
        mix = np.stack([sig[i:i + BLOCK]] * 2, axis=1).astype(np.float64)
        write_output_lim(mix, len(mix), out[i:i + BLOCK], 0, 1.0, lim)
    return out, lim


def _db(a):
    return 20 * np.log10(np.sqrt(np.mean(np.asarray(a, np.float64) ** 2)))


def test_output_compressor_evens_out_notes_held_on_the_pedal():
    """Compressor da saída: muitas notas presas no pedal (+10 dB de uma vez) somam bem menos com ele
    no máximo; desligado (0, o padrão) não muda nada."""
    fs = 48000
    t = np.arange(2 * fs) / fs
    amp = np.where(t < 1.0, 0.1, 0.1 * 10 ** (10 / 20))         # poucas notas -> muitas notas
    sig = amp * np.sin(2 * np.pi * 220 * t)
    off, _ = _run_output(sig, 0.0)
    assert np.allclose(off[:, 0], sig, atol=1e-6)                 # 0 = som exatamente igual
    on, lim = _run_output(sig, 1.0)
    step = _db(on[int(1.5 * fs):, 0]) - _db(on[int(0.5 * fs):fs, 0])
    assert step < 10.0 - 5.0, step                                 # o salto de 10 dB vira menos de 5 dB
    assert np.isfinite(on).all() and np.isfinite(lim).all()
    # soltar o pedal (-10 dB): a diferença entre antes e depois fica bem menor, e o que sobra volta
    # aos poucos (release de ~350 ms) em vez de ficar lá embaixo
    down = np.where(t < 1.0, 0.1 * 10 ** (10 / 20), 0.1) * np.sin(2 * np.pi * 220 * t)
    rel, _ = _run_output(down, 1.0)
    w = int(0.02 * fs)
    just_after = _db(rel[fs + w:fs + 2 * w, 0])
    settled = _db(rel[int(1.8 * fs):, 0])
    assert _db(rel[int(0.8 * fs):fs, 0]) - settled < 10.0 - 5.0    # a queda de 10 dB vira menos de 5 dB
    assert settled - just_after > 3.0                              # e o volume sobe de volta sozinho


def test_output_compressor_is_nan_safe_and_turns_off_cleanly():
    fs = 48000
    sig = 0.5 * np.sin(2 * np.pi * 110 * np.arange(fs) / fs)
    sig[1000:1010] = np.nan
    sig[2000] = np.inf
    out, lim = _run_output(sig, 1.0)
    assert np.isfinite(out).all() and np.isfinite(lim).all() and 0.0 < lim[5] <= 2.0
    # desligar com o ganho ainda baixo: volta suave para 1 e depois passa direto
    out, lim = _run_output(np.full(5 * fs, 0.3), 0.0, lim=lim)
    assert lim[5] == 1.0 and np.allclose(out[-100:, 0], 0.3)


def test_output_meter_reports_level_and_compressor_reduction():
    """Medidores do Master e do Compressor: pico da saída (depois do limitador) e o menor ganho do
    compressor desde a última leitura (lim[9] e lim[10], lidos e zerados pela interface)."""
    fs = 48000
    quiet, _ = _run_output(np.zeros(fs // 10), 1.0)
    from ampsim.dsp.kernels import limiter_state
    lim = limiter_state(fs)
    assert lim[9] == 0.0 and lim[10] == 1.0
    sig = 0.5 * np.sin(2 * np.pi * 220 * np.arange(fs // 2) / fs)
    _, lim = _run_output(np.zeros(fs // 10), 1.0)
    assert lim[9] == 0.0 and lim[10] == 1.0                      # silêncio: nada aceso
    _, lim = _run_output(sig, 0.0)
    assert 0.45 < lim[9] <= 0.9 and lim[10] == 1.0               # sem compressor: só o nível
    _, lim = _run_output(sig, 1.0)
    gr = -20 * np.log10(lim[10])
    assert lim[9] > 0.1 and gr > 6.0, gr                         # compressor no máximo com sinal alto


def test_compressor_meter_shows_applied_reduction_and_limiter():
    """Medidor do Compressor: a redução de verdade (ganho aplicado, com ataque), não o alvo instantâneo; e
    a redução total nos picos inclui o limitador (com o Compressor em 0 o limitador também aparece)."""
    from ampsim.dsp.kernels import limiter_state
    fs = 48000
    t = np.arange(fs // 2) / fs
    burst = np.where((t > 0.2) & (t < 0.21), 0.6, 0.01) * np.sin(2 * np.pi * 220 * t)   # estalo de 10 ms
    _, lim = _run_output(burst, 1.0)
    shown = -20 * np.log10(lim[10])
    # alvo instantâneo para um seno de pico 0.6 (~-7.4 dBFS RMS) com limiar -24 e razão 4:1
    target = 0.75 * (20 * np.log10(0.6 / np.sqrt(2)) + 24)
    assert 0.5 < shown < target - 3.0, (shown, target)        # o ataque de 15 ms não deixa chegar no alvo
    # Compressor em 0, sinal passando do teto: o limitador segura e o medidor mostra
    loud = 2.0 * np.sin(2 * np.pi * 220 * t)
    out, lim = _run_output(loud, 0.0)
    assert -20 * np.log10(lim[10]) > 6.0 and lim[11] == 1.0
    # e com o Compressor em 0 o áudio continua igual ao de antes (só o limitador mexe)
    quiet = 0.3 * np.sin(2 * np.pi * 220 * t)
    out, lim = _run_output(quiet, 0.0)
    assert np.array_equal(out[:, 0], quiet.astype(np.float32)) and lim[10] == 1.0
    assert limiter_state(fs)[11] == 1.0


def test_limiter_recovery_never_passes_the_ceiling():
    """Sinal 30–40 dB acima do teto: na volta do ganho a saída passava de LIM_CEIL (0,904)."""
    from ampsim.dsp.kernels import LIM_CEIL, limiter_state, write_output_lim
    n = 256
    for db_over in (30.0, 40.0):
        lim = limiter_state(FS)
        amp = LIM_CEIL * 10 ** (db_over / 20)
        t = np.arange(n * 40)
        sig = amp * np.sin(2 * np.pi * 220 * t / FS)
        peak = 0.0
        for b in range(40):
            mix = np.zeros((n, 2))
            mix[:, 0] = sig[b * n:(b + 1) * n]
            mix[:, 1] = sig[b * n:(b + 1) * n] * 0.7
            out = np.zeros((n, 2), np.float32)
            write_output_lim(mix, n, out, 0, 1.0, lim)
            peak = max(peak, float(np.abs(out).max()))
        assert peak <= LIM_CEIL + 1e-6, (db_over, peak)


def test_limiter_does_not_touch_normal_signal():
    """Compressor em 0 e sinal abaixo do teto: a saída é a entrada (bit a bit, em float32)."""
    from ampsim.dsp.kernels import limiter_state, write_output_lim
    n = 256
    rng = np.random.default_rng(3)
    lim = limiter_state(FS)
    for _ in range(20):
        x = rng.standard_normal((n, 2)) * 0.1
        mix = x.copy()
        out = np.zeros((n, 2), np.float32)
        write_output_lim(mix, n, out, 0, 1.0, lim)
        assert np.array_equal(out, x.astype(np.float32))
