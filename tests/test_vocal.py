"""Testes offline da trilha Vocal (dsp/vocal.py) e dos presets de voz (vocal_presets.py)."""
import time

import numpy as np
import pytest

from ampsim.dsp import vocal as V
from ampsim.dsp.kernels import limiter_state, write_output_lim
from ampsim.dsp.vocal import VOCAL_EFFECTS, VocalChain, clean_values, default_values, latency_note
from ampsim.vocal_presets import DEFAULT_VOCAL_PRESET, VOCAL_FACTORY

FS = 48000.0


@pytest.fixture(scope="module", autouse=True)
def compiled():
    V.warmup(FS)


def chain(*on, fs=FS, **params):
    """Trilha ligada, ganhos já no valor final, com os efeitos `on` ligados e params {efeito: {k: v}}."""
    v = VocalChain(fs)
    v.set_switch("on", True)
    for eff, vals in params.items():
        for k, x in vals.items():
            v.set_param(eff, k, x)
    for eff in on:
        v.set_on(eff, True)
    v._snap_gains()
    return v


def tone(f, seconds=0.5, amp=0.1, fs=FS):
    t = np.arange(int(fs * seconds)) / fs
    return amp * np.sin(2 * np.pi * f * t)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def band_db(x, lo, hi, fs=FS):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / fs)
    return 10 * np.log10(spec[(f >= lo) & (f <= hi)].sum() + 1e-20)


def voiced(seconds=0.5, f0=200.0, amp=0.2):
    """Vogal sintética: harmônicos de f0 caindo 1/k até ~4 kHz."""
    t = np.arange(int(FS * seconds)) / FS
    x = sum(np.sin(2 * np.pi * f0 * k * t + k) / k for k in range(1, 21))
    return amp * x / np.abs(x).max()


def sibilance(seconds=0.5, amp=0.1, seed=1):
    """Ruído só entre 6 e 9 kHz (um "S")."""
    rng = np.random.default_rng(seed)
    n = int(FS * seconds)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    spec[(f < 6000) | (f > 9000)] = 0
    x = np.fft.irfft(spec, n)
    return amp * x / np.abs(x).max()


# ---------------------------------------------------------------------------- básico
def test_defaults_track_off_and_silent():
    v = VocalChain(FS)
    assert v.values["track"]["on"] is False      # não abre o microfone sem querer
    assert not v.running
    assert not any(v.values[e.key]["on"] for e in VOCAL_EFFECTS)


def test_bypass_bit_identical_all_off():
    v = chain()
    rng = np.random.default_rng(0)
    x = (rng.standard_normal(9000) * 0.2).astype(np.float32)
    for block in (256, 64, 37):
        v2 = chain()
        y = v2.render(x, block=block)
        assert np.array_equal(y[:, 0], x.astype(np.float64))
        assert np.array_equal(y[:, 1], x.astype(np.float64))
    y = v.render(x)
    assert np.array_equal(y[:, 0], x.astype(np.float64))


def test_mix_is_summed_not_overwritten():
    v = chain()
    src = np.full((64, 1), 0.25, np.float32)
    mix = np.full((64, 2), 0.5)
    v.process(src, 0, 64, mix)
    assert np.allclose(mix, 0.75)


@pytest.mark.parametrize("fs", [44100.0, 48000.0, 96000.0])
def test_all_effects_finite_and_bounded(fs):
    v = chain(*[e.key for e in VOCAL_EFFECTS], fs=fs)
    rng = np.random.default_rng(2)
    n = int(fs * 0.6)
    x = np.concatenate([np.sign(np.sin(np.arange(n) * 0.05)) * 0.99,
                        rng.standard_normal(n) * 0.3, np.zeros(n)])
    y = v.render(x)
    assert np.all(np.isfinite(y))
    assert np.abs(y).max() < 8.0


@pytest.mark.parametrize("edge", ["lo", "hi"])
def test_param_extremes_finite(edge):
    v = chain(*[e.key for e in VOCAL_EFFECTS])
    for e in VOCAL_EFFECTS:
        for p in e.params:
            v.set_param(e.key, p.key, p.lo if edge == "lo" else p.hi)
    v.set_param("track", "input_gain", 36 if edge == "hi" else -24)
    v._snap_gains()
    y = v.render(np.concatenate([voiced(0.3), sibilance(0.3), np.zeros(int(5 * FS))]))
    assert np.all(np.isfinite(y))
    # no silêncio, delay (85%) e reverb (maior sala) só caem: nada realimenta acima de 1
    peak = np.abs(y).max()
    assert np.abs(y[-int(1.5 * FS):]).max() < 0.9 * peak


# ---------------------------------------------------------------------------- efeitos
def test_hpf_cuts_50hz():
    v = chain("hpf")                                   # padrão: 100 Hz, 24 dB/oitava
    lo = v.render(tone(50))[12000:, 0]
    v = chain("hpf")
    mid = v.render(tone(1000))[12000:, 0]
    assert rms_db(lo) - rms_db(tone(50)[12000:]) < -18
    assert abs(rms_db(mid) - rms_db(tone(1000)[12000:])) < 0.5
    v = chain("hpf", hpf=dict(slope=0))                # suave: 12 dB/oitava
    lo2 = v.render(tone(50))[12000:, 0]
    assert -15 < rms_db(lo2) - rms_db(tone(50)[12000:]) < -9


def test_gate_closes_on_noise_and_opens_on_voice():
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(int(FS)) * 10 ** (-70 / 20)      # chiado a -70 dBFS
    v = chain("gate")                                            # limiar -55, abaixa 30 dB
    y = v.render(noise)[int(0.6 * FS):, 0]
    assert rms_db(y) - rms_db(noise[int(0.6 * FS):]) < -25
    # voz depois do silêncio: abre e passa inteira
    x = np.concatenate([noise, voiced(0.5, amp=0.1)])
    v = chain("gate")
    y = v.render(x)[:, 0]
    seg = slice(int(FS) + 2400, len(x))
    assert abs(rms_db(y[seg]) - rms_db(x[seg])) < 0.5
    _, _, gate_open, _ = v.dyn_meters()
    assert gate_open


def test_gate_holds_word_end_then_closes():
    v = chain("gate")
    x = np.concatenate([voiced(0.3, amp=0.1), np.zeros(int(FS * 0.8))])
    y = v.render(x)[:, 0]
    n0 = int(0.3 * FS)
    assert v.VS[V.S_G_OPEN] < 0.5                     # fechou no silêncio
    # depois de fechar, abaixa até a "Redução" (não muta de vez)
    assert abs(v.VS[V.S_G_GAIN] - 10 ** (-30 / 20)) < 1e-3
    assert np.all(np.isfinite(y[n0:]))


def test_compressor_reduces_peaks_and_meters():
    quiet = tone(300, 0.5, amp=10 ** (-30 / 20))
    loud = tone(300, 0.5, amp=10 ** (-6 / 20))
    x = np.concatenate([quiet, loud])
    v = chain("comp", comp=dict(amount=70))
    y = v.render(x)[:, 0]
    h = len(quiet)
    in_diff = rms_db(x[h + 4800:]) - rms_db(x[4800:h])          # 24 dB
    out_diff = rms_db(y[h + 4800:]) - rms_db(y[4800:h])
    assert in_diff - out_diff > 10
    gr, _, _, _ = v.dyn_meters()
    assert gr > 6
    assert v.dyn_meters()[0] == 0.0                           # o medidor zera ao ler
    assert np.abs(y).max() < 0.9


def test_compressor_auto_makeup_keeps_peak_level():
    x = tone(300, 0.5, amp=10 ** (-12 / 20))
    for amount in (20, 50, 90):
        v = chain("comp", comp=dict(amount=amount))
        y = v.render(x)[:, 0]
        assert abs(rms_db(y[12000:]) - rms_db(x[12000:])) < 2.5
    v = chain("comp", comp=dict(amount=0))
    assert v.auto_makeup_db() == 0


def test_eq_bands():
    for key, f in (("low", 80), ("body", 400), ("presence", 3200), ("air", 14000)):
        v = chain("eq", eq={key: 6})
        y = v.render(tone(f))[12000:, 0]
        gain = rms_db(y) - rms_db(tone(f)[12000:])
        assert 4.5 < gain < 6.5, (key, gain)
        assert abs(v.response([f])[0] - gain) < 0.3
    v = chain("eq", eq=dict(highcut=3500))
    y = v.render(tone(9000))[12000:, 0]
    assert rms_db(y) - rms_db(tone(9000)[12000:]) < -12


def test_deesser_reduces_sibilance_not_vowels():
    s = sibilance(0.5)
    v = chain("deess")
    ys = v.render(s)[:, 0]
    red = band_db(ys[4800:], 6000, 9000) - band_db(s[4800:], 6000, 9000)
    assert red < -4, red
    assert v.dyn_meters()[1] > 3
    vo = voiced(0.5)
    v = chain("deess")
    y = v.render(vo)[:, 0]
    assert abs(rms_db(y[4800:]) - rms_db(vo[4800:])) < 0.3
    assert v.dyn_meters()[1] < 0.5
    # mais quantidade, mais redução
    v = chain("deess", deess=dict(amount=100))
    y2 = v.render(s)[:, 0]
    assert band_db(y2[4800:], 6000, 9000) < band_db(ys[4800:], 6000, 9000) - 1


def test_doubler_widens():
    x = voiced(0.5)
    v = chain("double")
    y = v.render(x)
    assert np.all(np.isfinite(y))
    side = y[:, 0] - y[:, 1]
    assert rms_db(side[4800:]) > rms_db(x[4800:]) - 20
    v = chain("double", double=dict(width=0))
    y = v.render(x)
    assert np.allclose(y[:, 0], y[:, 1])


def test_delay_time_free_and_bpm():
    imp = np.zeros(int(FS * 1.2))
    imp[0] = 0.5
    v = chain("delay", delay=dict(time=250, feedback=0, mix=100))
    y = v.render(imp)[:, 0]
    k = np.argmax(np.abs(y[100:])) + 100
    assert abs(k - int(0.25 * FS)) < 30
    v = chain("delay", delay=dict(sync=1, feedback=0, mix=100))
    v.set_bpm(120)                                     # 1/4 a 120 BPM = 500 ms
    assert v.delay_ms() == 500
    y = v.render(imp)[:, 0]
    k = np.argmax(np.abs(y[100:])) + 100
    assert abs(k - int(0.5 * FS)) < 30


def test_reverb_types_tail_and_decay():
    imp = np.zeros(int(FS * 4))
    imp[0] = 0.5
    for typ in range(len(V.REVERB_TYPES)):
        v = chain("reverb", reverb=dict(type=typ, mix=50))
        y = v.render(imp)
        assert np.all(np.isfinite(y))
        tail = y[int(0.1 * FS):int(0.5 * FS)]
        assert np.abs(tail).max() > 1e-4               # tem cauda
        assert np.abs(y[-4800:]).max() < np.abs(tail).max()
    v = chain("reverb", reverb=dict(predelay=100, mix=100))
    y = v.render(imp)[:, 0]
    assert np.abs(y[100:int(0.09 * FS)]).max() < 1e-9  # nada antes do pré-delay


# ---------------------------------------------------------------------------- trilha
def test_phase_invert():
    x = voiced(0.1)
    v = chain()
    v.set_switch("phase", True)
    v._snap_gains()
    y = v.render(x)
    assert np.array_equal(y[:, 0], -x.astype(np.float32).astype(np.float64))


def test_mute_and_off_ramp_without_click():
    x = tone(400, 0.3, amp=0.5)
    v = chain()
    src = x.astype(np.float32).reshape(-1, 1)
    mix = np.zeros((V.Ly.MAX_BLOCK, 2))
    v.process(src[:2400], 0, 2400, mix)
    mix[:] = 0
    v.set_switch("mute", True)
    v.process(src[2400:4800], 0, 2400, mix)
    y = mix[:2400, 0].copy()
    assert np.abs(y[-200:]).max() < 1e-6              # ~15 ms depois: mudo
    assert np.abs(np.diff(y)).max() < 0.06            # sem degrau (rampa)
    assert v.running                                   # mute continua medindo
    v.set_switch("mute", False)
    v.set_switch("on", False)
    mix[:] = 0
    v.process(src[4800:8800], 0, 4000, mix)
    assert not v.running                               # desligou depois da rampa: o motor para de chamar


def test_off_on_restarts_clean():
    imp = np.zeros(int(FS))
    imp[0] = 0.5
    v = chain("reverb", reverb=dict(mix=100, size=100))
    v.render(imp[:2400])
    v.set_switch("on", False)
    v.render(np.zeros(4800))
    assert not v.running
    v.set_switch("on", True)
    v._snap_gains()
    y = v.render(np.zeros(4800))
    assert np.abs(y).max() == 0.0                      # sem a cauda antiga ao religar


def test_block_larger_than_buffers_is_split():
    v = VocalChain(FS, max_block=256)
    v.set_switch("on", True)
    v._snap_gains()
    src = np.full((1000, 1), 0.25, np.float32)
    mix = np.zeros((1000, 2))
    v.process(src, 0, 1000, mix)
    assert np.allclose(mix, 0.25)


def test_input_meter_and_clip():
    v = chain()
    v.render(np.full(256, 0.5))
    pin, pout = v.meters()
    assert abs(pin - 0.5) < 1e-6 and abs(pout - 0.5) < 1e-6
    assert v.meters() == (0.0, 0.0)
    assert not v.dyn_meters()[3]
    v.render(np.full(256, 1.0))                        # chegou cortado da placa
    assert v.dyn_meters()[3]
    v.set_param("track", "input_gain", 12)
    v._snap_gains()
    v.render(np.full(256, 0.3))                        # ganho demais no app
    assert v.dyn_meters()[3]
    assert not v.dyn_meters()[3]                       # zera ao ler


def test_volume_and_pan():
    v = chain()
    v.set_param("track", "volume", -6)
    v.set_param("track", "pan", -100)
    v._snap_gains()
    y = v.render(np.full(256, 0.5))
    assert abs(y[-1, 0] - 0.5 * 10 ** (-6 / 20) * np.sqrt(2)) < 1e-9
    assert abs(y[-1, 1]) < 1e-12
    v.set_param("track", "volume", -60)
    v._snap_gains()
    assert np.abs(v.render(np.full(256, 0.5))).max() == 0.0


def test_plugin_positions_and_nan_recovery():
    seen = []

    class Fake:
        active = True
        slots = (1,)
        bad = False

        def process(self, KB, n):
            seen.append(KB[:n].copy())
            if self.bad:
                KB[0, 0] = np.nan

    imp = np.zeros(2400)
    imp[0] = 0.5
    v = chain("reverb", reverb=dict(mix=100, predelay=0))
    v.fx_chain = Fake()
    v.render(imp, block=2400)
    assert np.abs(seen[-1][1000:]).max() == 0.0        # antes do reverb: só o impulso seco
    v = chain("reverb", reverb=dict(mix=100, predelay=0))
    v.set_param("track", "plug_pos", 1)
    v.fx_chain = Fake()
    v.render(imp, block=2400)
    assert np.abs(seen[-1][1000:]).max() > 0.0         # no fim: já com a cauda
    # plugin que solta NaN: o bloco vira silêncio e o estado é zerado; o próximo bloco volta ao normal
    v = chain("reverb")
    v.fx_chain = Fake()
    v.fx_chain.bad = True
    y = v.render(voiced(0.05), block=256)
    assert np.all(np.isfinite(y))
    v.fx_chain.bad = False
    y = v.render(voiced(0.05), block=256)
    assert np.all(np.isfinite(y)) and np.abs(y).max() > 0.01
    assert v.VS[V.S_BAD] == 0.0
    # cadeia vazia/inativa: não é chamada
    seen.clear()
    v.fx_chain.active = False
    v.render(imp)
    assert not seen


def test_master_limiter_protects_output():
    """Microfonia/grito: a saída do motor continua segura pelo limitador do Master."""
    v = chain(*[e.key for e in VOCAL_EFFECTS], comp=dict(amount=0))
    v.set_param("track", "input_gain", 36)
    v.set_param("track", "volume", 12)
    v._snap_gains()
    lim = limiter_state(FS)
    x = tone(2500, 1.0, amp=0.9).astype(np.float32).reshape(-1, 1)
    mix = np.zeros((256, 2))
    out = np.zeros((256, 2), np.float32)
    peak = 0.0
    for i in range(0, len(x) - 255, 256):
        v.process(x[i:i + 256], 0, 256, mix)
        write_output_lim(mix, 256, out, 0, 1.0, lim)
        peak = max(peak, float(np.abs(out).max()))
    assert peak <= 0.9 + 1e-6


# ---------------------------------------------------------------------------- estado e presets
def test_clean_values_rejects_garbage():
    assert clean_values(None) == default_values()
    d = clean_values({"hpf": {"freq": 5000, "on": "sim", "x": 1}, "gate": {"threshold": float("nan")},
                      "reverb": {"type": 7.6, "mix": True}, "track": {"on": 1, "mute": True, "volume": -500},
                      "evil": {"a": 1}})
    assert d["hpf"]["freq"] == 200 and d["hpf"]["on"] is False and "x" not in d["hpf"]
    assert d["gate"]["threshold"] == -52
    assert d["reverb"]["type"] == 2 and d["reverb"]["mix"] == 20
    assert d["track"]["on"] is False and d["track"]["mute"] is True and d["track"]["volume"] == -60
    assert "evil" not in d


def test_state_roundtrip_and_old_session():
    v = chain("comp", "reverb", comp=dict(amount=77))
    st = v.get_state()
    w = VocalChain(FS)
    w.load_state(st)
    assert w.values == v.values
    old = VocalChain(FS)
    old.load_state({})                                 # sessão antiga, sem vocal
    assert old.values == default_values() and not old.running
    old.load_state({"values": "lixo"})
    assert old.values == default_values()


def test_state_includes_plugin_chain():
    class Chain:
        active = False
        slots = ()
        got = None

        def to_list(self):
            return [{"path": "x.vst3", "state": "", "on": True, "mix": 100}]

        def apply(self, lst):
            Chain.got = lst

        def process(self, KB, n):
            pass

    v = VocalChain(FS)
    v.fx_chain = Chain()
    st = v.get_state()
    assert st["fx_chain"][0]["path"] == "x.vst3"
    w = VocalChain(FS)
    w.fx_chain = Chain()
    w.load_state(st)
    assert Chain.got == st["fx_chain"]
    w.load_state({"values": {}})                       # preset/sessão sem plugins: a cadeia esvazia
    assert Chain.got == []


def test_factory_presets():
    assert 5 <= len(VOCAL_FACTORY) <= 8
    assert DEFAULT_VOCAL_PRESET in VOCAL_FACTORY
    keys = default_values()
    for name, preset in VOCAL_FACTORY.items():
        vals = preset["values"]
        assert "track" not in vals, name
        for eff, params in vals.items():
            assert eff in keys, (name, eff)
            for k, x in params.items():
                assert k in keys[eff], (name, eff, k)
                p = next((p for p in V.VOCAL_EFFECT_BY_KEY[eff].params if p.key == k), None)
                if p is not None:
                    assert p.lo <= x <= p.hi, (name, eff, k, x)
        v = chain()
        v.set_param("track", "volume", -3)
        v.apply_preset(preset)
        assert v.values["track"]["volume"] == -3 and v.values["track"]["on"] is True
        v._snap_gains()
        y = v.render(np.concatenate([voiced(0.3), sibilance(0.1), np.zeros(4800)]))
        assert np.all(np.isfinite(y)) and np.abs(y).max() < 2.0, name


def test_latency_note():
    assert latency_note(256, 48000) == ""
    assert latency_note(512, 48000) == ""
    msg = latency_note(1024, 48000)
    assert "1024" in msg and "atrasada" in msg


def test_cpu_full_chain_256():
    v = chain(*[e.key for e in VOCAL_EFFECTS])
    src = (np.random.default_rng(5).standard_normal((256, 1)) * 0.1).astype(np.float32)
    mix = np.zeros((256, 2))
    for _ in range(50):
        v.process(src, 0, 256, mix)
    n = 2000
    t0 = time.perf_counter()
    for _ in range(n):
        v.process(src, 0, 256, mix)
    per = (time.perf_counter() - t0) / n
    budget = 256 / FS
    print(f"\nvocal: {per * 1e6:.1f} us por bloco de 256 ({100 * per / budget:.2f}% do prazo)")
    assert per < 0.15 * budget


# ---------------------------------------------------------------------------- no motor (offline)
@pytest.fixture()
def engine():
    from ampsim.audio.engine import AudioEngine
    e = AudioEngine(FS)
    for name in ("guitar", "bass"):                    # só o microfone na entrada
        e.tracks[name].set_param("track", "on", False)
    return e


def render_engine(e, x, ch, n_in=2, block=256):
    """Microfone simulado: x no canal `ch` da entrada -> saída principal do motor (depois do Master)."""
    out = np.zeros((len(x), 2), np.float32)
    for i in range(0, len(x) - block + 1, block):
        ind = np.zeros((block, n_in), np.float32)
        ind[:, ch] = x[i:i + block]
        o = np.zeros((block, 2), np.float32)
        e._render(ind, o, block)
        out[i:i + block] = o
    return out


def test_engine_mic_track_off_by_default_then_on(engine):
    from ampsim.audio.engine import INPUT_CHANNEL_TRACKS, TRACKS
    e = engine
    v = e.tracks["vocal"]
    assert "vocal" in TRACKS and "vocal" in INPUT_CHANNEL_TRACKS and isinstance(v, VocalChain)
    e.input_channel["vocal"] = 1
    x = tone(500, 0.3, amp=0.2)
    y = render_engine(e, x, 1)
    assert np.abs(y).max() < 1e-6                      # desligada: o microfone não toca
    v.set_switch("on", True)
    y = render_engine(e, x, 1)
    seg = slice(4800, len(y) - 256)
    assert abs(rms_db(y[seg, 0]) - rms_db(x[seg])) < 0.5 and abs(rms_db(y[seg, 1]) - rms_db(x[seg])) < 0.5
    # canal que a placa não tem: silêncio (sem erro)
    e.input_channel["vocal"] = 5
    assert np.abs(render_engine(e, x, 1)).max() < 1e-6
    # analisador da aba (RTA) também funciona na Vocal
    e.input_channel["vocal"] = 1
    e.rta_track = "vocal"
    pos = e.rta_pos_out
    render_engine(e, x[:2560], 1)
    assert e.rta_pos_out != pos and np.abs(e.rta_out).max() > 0.05


def test_engine_vocal_full_chain_bounded_and_protected(engine):
    e = engine
    v = e.tracks["vocal"]
    e.input_channel["vocal"] = 0
    v.apply_preset(VOCAL_FACTORY["Ministração (reverb longo)"])
    v.set_switch("on", True)
    v.set_param("track", "input_gain", 36)
    v.set_param("track", "volume", 12)
    rng = np.random.default_rng(9)
    x = np.clip(rng.standard_normal(int(FS)) * 0.5, -1, 1)          # "grito"/microfonia: muito acima do teto
    y = render_engine(e, x, 0)
    assert np.all(np.isfinite(y)) and np.abs(y).max() <= 0.9 + 1e-6     # limitador do Master segura


def test_engine_rate_change_keeps_vocal_and_bpm(engine):
    e = engine
    v = e.tracks["vocal"]
    v.set_switch("on", True)
    v.set_on("delay", True)
    v.set_param("delay", "sync", 1)
    chain = v.fx_chain
    e.instruments.set_bpm(90)
    assert v.bpm == 90 and abs(v.delay_ms() - 60000 / 90) < 1e-6
    e._rebuild(44100)
    w = e.tracks["vocal"]
    assert w is not v and isinstance(w, VocalChain) and w.fs == 44100
    assert w.values == v.values and w.fx_chain is chain and w.bpm == 90
    e._rebuild(44100)                                  # mesma taxa: só zera o estado
    assert e.tracks["vocal"] is w


# ---------------------------------------------------------------------------- gate entre frases (QA rodada 8)
def _words_with_noise(noise_db, seed=4):
    """0,2 s de chiado, palavra 1 (0,5 s, termina com 50 ms caindo), pausa de 0,7 s, palavra 2 (0,4 s), pausa
    de 0,7 s; chiado de fundo (branco, RMS = noise_db) o tempo todo. -> (sinal, [(início, fim) das palavras])"""
    rng = np.random.default_rng(seed)
    parts, words, t = [], [], 0

    def word(sec):
        w = voiced(sec, amp=1.0)
        w *= 10 ** (-25 / 20) / np.sqrt(np.mean(w ** 2))           # voz a -25 dBFS RMS
        fade = int(0.05 * FS)
        w[-fade:] *= np.linspace(1.0, 0.0, fade)
        return w
    for kind, sec in (("p", 0.2), ("w", 0.5), ("p", 0.7), ("w", 0.4), ("p", 0.7)):
        seg = word(sec) if kind == "w" else np.zeros(int(sec * FS))
        if kind == "w":
            words.append((t, t + len(seg)))
        parts.append(seg)
        t += len(seg)
    x = np.concatenate(parts)
    return x + rng.standard_normal(len(x)) * 10 ** (noise_db / 20), words


def _gate_gain_track(v, x, block=32):
    """Ganho do gate (dB) amostrado a cada bloco, junto com o índice da amostra no fim do bloco."""
    src = x.astype(np.float32).reshape(-1, 1)
    mix = np.zeros((block, 2))
    pos, gains = [], []
    for i in range(0, len(x) - block + 1, block):
        mix[:] = 0
        v.process(src[i:i + block], 0, block, mix)
        pos.append(i + block)
        gains.append(20 * np.log10(max(v.VS[V.S_G_GAIN], 1e-9)))
    return np.array(pos), np.array(gains)


@pytest.mark.parametrize("noise_db", [-60, -65])
@pytest.mark.parametrize("name", list(VOCAL_FACTORY))
def test_gate_closes_between_phrases_with_every_preset(name, noise_db):
    v = chain()
    v.apply_preset(VOCAL_FACTORY[name])
    if not v.values["gate"]["on"]:
        pytest.skip("preset sem gate")
    x, words = _words_with_noise(noise_db)
    pos, g = _gate_gain_track(v, x)
    for k, (a, b) in enumerate(words):
        # durante a palavra (depois de 5 ms) e no fim dela (os 50 ms que caem) o gate está aberto
        inside = (pos > a + int(0.005 * FS)) & (pos <= b)
        assert g[inside].min() > -1.0, (name, noise_db, k, g[inside].min())
        # na pausa: -10 dB ou mais em até 0,3 s e continua fechado até a próxima palavra
        nxt = words[k + 1][0] if k + 1 < len(words) else len(x)
        late = (pos > b + int(0.3 * FS)) & (pos <= nxt)
        assert g[late].max() <= -10.0, (name, noise_db, k, g[late].max())


def test_gate_detector_is_rms_and_hysteresis_3db():
    """Chiado entre o fechamento (limiar - 3 dB) e o limiar mantém o estado; abaixo de limiar - 3 dB fecha."""
    rng = np.random.default_rng(7)
    for noise_db, should_close in ((-57.0, True), (-53.5, False)):
        v = chain("gate", gate=dict(threshold=-52, range=30, release=100))
        n = rng.standard_normal(int(FS)) * 10 ** (noise_db / 20)
        v.render(np.concatenate([tone(300, 0.1, amp=0.1), n]))     # voz abre o gate; depois só o chiado
        assert (v.VS[V.S_G_OPEN] < 0.5) == should_close, noise_db
