"""Gravador da aba Faders / Pads: grava o som do AmpSim ou uma entrada, salva no banco e toca nos pads."""
import numpy as np
import pytest

from ampsim import storage
from ampsim.audio import sampler as smp
from ampsim.audio.engine import AudioEngine
from ampsim.audio.sampler import REC_PREFIX
from ampsim.dsp.kernels import warmup

N = 256


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    warmup()
    e = AudioEngine()
    e.tracks["pads"].set_param("track", "use_amp", False)
    return e


def run(e, secs, indata=None):
    out = np.zeros((N, 2), np.float32)
    peak = 0.0
    for _ in range(int(48000 * secs / N)):
        e._render(indata, out, N)
        peak = max(peak, float(np.abs(out).max()))
    return peak


def tone(fs=48000, secs=0.5, f=440.0, amp=0.5):
    t = np.arange(int(fs * secs)) / fs
    x = (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)
    return np.stack([x, x], axis=1)


def test_record_ampsim_output_trims_silence_and_saves(engine):
    e, inst = engine, engine.instruments
    run(e, 0.3)
    e.recorder.start(e.fs, "out")
    run(e, 0.4)                                   # silêncio antes de tocar: tem de sair do começo
    inst.set_ready("Piano + Pad (culto)")
    inst.key_on(60, 110)
    run(e, 0.8)
    inst.key_off(60)
    run(e, 0.3)
    data = e.recorder.stop()
    assert not e.recorder.active and len(data) > 0.5 * 48000
    assert np.abs(data[: int(0.02 * 48000)]).max() > 0.0005   # começa no som, não no silêncio
    name = smp.save_recording(data, e.fs)
    assert name == "Gravação 01" and smp.list_recordings() == ["Gravação 01"]
    a, sr = smp.load_recording(name)
    assert sr == 48000 and a.shape == data.shape and np.allclose(a, data)


def test_record_from_input_channel(engine):
    e = engine
    x = tone(secs=0.6)
    e.recorder.start(e.fs, 1)                     # entrada 2
    out = np.zeros((N, 2), np.float32)
    for k in range(len(x) // N):
        ind = np.zeros((N, 2), np.float32)
        ind[:, 1] = x[k * N:(k + 1) * N, 0]
        e._render(ind, out, N)
    data = e.recorder.stop()
    assert len(data) > 0.5 * 48000 and np.allclose(data[:, 0], data[:, 1])
    assert abs(float(np.abs(data).max()) - 0.5) < 0.01


def test_recording_plays_on_pad_and_follows_pads_volume_and_mute(engine):
    e, inst = engine, engine.instruments
    e.sampler.put("Grito", tone(secs=0.4, amp=0.4), 48000)
    inst.pad_sounds[0] = REC_PREFIX + "Grito"
    run(e, 0.2)
    inst.pad_hit(0, 127)
    loud = run(e, 0.3)
    assert loud > 0.1
    run(e, 0.5)
    inst.set_mute("Volume bateria", True)
    run(e, 0.1)                                   # o ganho desce aos poucos
    inst.pad_hit(0, 127)
    assert run(e, 0.3) < 1e-4
    inst.set_mute("Volume bateria", False)


def test_sampler_resamples_to_engine_rate():
    s = smp.Sampler()
    s.set_fs(48000)
    s.put("x", tone(fs=44100, secs=1.0), 44100)
    assert abs(len(s.samples["x"]) - 48000) <= 2
    s.set_fs(44100)
    assert len(s.samples["x"]) == 44100


def test_bank_rename_delete_and_limits(engine, tmp_path):
    a = tone(secs=0.2)
    n1 = smp.save_recording(a, 48000)
    n2 = smp.save_recording(a, 48000, "Voz: final?")
    assert n2 == "Voz  final" and smp.list_recordings() == ["Gravação 01", "Voz  final"]
    assert smp.rename_recording(n1, "Voz  final") is None             # nome já usado
    assert smp.rename_recording(n1, "Intro") == "Intro"
    smp.delete_recording("Intro")
    assert smp.list_recordings() == ["Voz  final"]
    assert smp.load_recording("não existe") is None
    r = smp.Recorder()
    r.start(1000, "out")
    for _ in range(100):                                                # 60 s a 1 kHz = 60000 amostras
        r.feed(np.ones((1000, 2), np.float32))
    assert not r.active and r.full


def test_double_tap_turns_the_playing_recording_into_a_loop_until_stop():
    """PLAY duas vezes seguidas (tela remota): a mesma voz que já começou passa a repetir até o STOP."""
    s = smp.Sampler()
    s.set_fs(48000)
    s.put("x", tone(secs=0.1, amp=0.4), 48000)                 # 4800 amostras
    mix = np.zeros((N, 2))

    def block():
        mix[:] = 0.0
        s.render(mix, N, 1.0)
        return float(np.abs(mix).max())

    s.trigger("x")
    assert block() > 0.1 and s.looping == ""
    s.loop("x")                                                # 2º toque: vira loop, sem voz nova
    block()
    assert len(s.voices) == 1 and s.looping == "x"
    for _ in range(int(0.5 * 48000 / N)):                      # bem depois do fim da gravação
        assert block() > 0.0
    assert len(s.voices) == 1
    s.stop_all()
    assert s.looping == "" and block() == 0.0 and not s.voices
    # um toque só: toca uma vez e acaba
    s.trigger("x")
    for _ in range(int(0.2 * 48000 / N)):
        block()
    assert not s.voices and block() == 0.0
    # loop sem nada tocando começa uma voz nova; gravação menor que o bloco repete dentro do bloco
    s.put("curta", np.full((100, 2), 0.25, np.float32), 48000)
    s.loop("curta")
    block()
    assert s.looping == "curta" and np.all(mix[:, 0] > 0.0)
    s.loop("x")                                                # outro loop: só um por vez
    block()
    assert s.looping == "x" and sum(1 for v in s.voices if v[4]) == 1


def test_stop_reaches_the_audio_thread_even_mid_block():
    """STOP enquanto o callback ainda segura a lista antiga de vozes: o loop para no bloco seguinte."""
    s = smp.Sampler()
    s.put("x", tone(secs=0.1, amp=0.4), 48000)
    s.loop("x")
    mix = np.zeros((N, 2))
    s.render(mix, N, 1.0)
    old = s.voices
    s.stop_all()
    s.voices = old                                             # o callback devolveu a lista antiga
    mix[:] = 0.0
    s.render(mix, N, 1.0)
    assert not s.voices and float(np.abs(mix).max()) == 0.0
