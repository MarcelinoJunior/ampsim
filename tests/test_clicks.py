"""Estalos (clicks) no áudio: tocar rápido não pode gerar degraus na forma de onda.

Detector: a 2ª diferença do sinal (|x[n+1] - 2x[n] + x[n-1]|) em janelas de 2 ms, comparada com
as janelas vizinhas (±20 ms). Um degrau (voz cortada, volume que pula) faz uma janela saltar
muitas vezes acima das vizinhas; som tonal ou ruído contínuo não. Janelas quase em silêncio são
ignoradas. O próprio detector é testado com um estalo inserido de propósito.
"""
import numpy as np
import pytest

from ampsim.audio.engine import AudioEngine
from ampsim.audio.soundfont import available
from ampsim.dsp.kernels import warmup
from ampsim.dsp.worship import DRUM_TYPE_NAMES, DV_ACTIVE, GHOSTS, DrumSynth, render_drums

FS = 48000.0
N = 128
W = 96                                       # janela de 2 ms
LIMIT = 6.0                                  # quantas vezes acima das vizinhas é estalo


def click_score(x, floor_db=-60.0, skip=()):
    """Maior razão (janela / mediana das vizinhas) do sinal; ~1-3 em som limpo.

    `skip`: amostras de ataque de propósito (nota/batida começando); a janela que as contém e a
    seguinte ficam de fora.
    """
    x = np.asarray(x, dtype=np.float64)
    d2 = np.abs(np.diff(x, 2))
    nwin = len(d2) // W
    m = d2[:nwin * W].reshape(nwin, W).max(axis=1)
    lvl = np.abs(x[:nwin * W]).reshape(nwin, W).max(axis=1)
    floor = np.abs(x).max() * 10 ** (floor_db / 20)
    # a 2ª diferença em n usa x[n..n+2]: o ataque em s0 já aparece em d2[s0 - 2]
    skipped = {k for s0 in skip for k in range((s0 - 2) // W, s0 // W + 3)}
    worst = 0.0
    for i in range(nwin):
        if lvl[i] < floor or i in skipped:
            continue
        nb = np.r_[m[max(0, i - 10):i], m[i + 1:i + 11]]
        if len(nb) < 4:
            continue
        worst = max(worst, m[i] / (np.median(nb) + 1e-12))
    return worst


@pytest.fixture(scope="module", autouse=True)
def _jit():
    warmup()


def fresh_engine():
    e = AudioEngine()
    e.instruments.set_pad_preset("Worship Moderno")
    return e


def play(e, step, every, secs):
    out = np.zeros((N, 2), np.float32)
    buf = []
    for b in range(int(FS * secs / N)):
        if b % every == 0:
            step(b // every)
        e.instruments.tick(N / FS)            # fades do pad contínuo no ritmo real
        e._render(None, out, N)
        buf.append(out[:, 0].copy())
    return np.concatenate(buf)


# ------------------------------------------------------------------ o detector funciona?
def test_detector_finds_inserted_click():
    t = np.arange(int(FS)) / FS
    x = 0.3 * np.sin(2 * np.pi * 220 * t) * np.exp(-t)
    assert click_score(x) < 3
    y = x.copy()
    y[24000:] -= 0.02                          # degrau de 2% (bem audível como "tic")
    assert click_score(y) > LIMIT


# ------------------------------------------------------------------ bateria sintetizada (kernel)
def _sine_drum_synth(voices):
    """Bateria com um tipo "seno puro" de cauda longa: qualquer degrau aparece na 2ª diferença."""
    d = DrumSynth(FS)
    d.DV = np.zeros((voices + GHOSTS, d.DV.shape[1]))
    d.DT[:] = 0.0
    d.DT[0, :] = (110, 110, 1.0, 3.0, 1.0, 0.0, 0.01, 1000, 50, 0.0, 0, 0, 0.3, 0.0)
    d.DT[1, :] = d.DT[0, :]
    d.DT[1, 0] = d.DT[1, 1] = 165.0
    return d


def _hit_fast(d, declick=True, hits=120, every=6, types=(0, 1), vels=(100,)):
    mix = np.zeros((N, 2))
    send = np.zeros(N)
    ev = np.zeros((4, 2), dtype=np.int64)
    out = []
    for b in range(hits * every):
        mix[:] = 0.0
        nev = 0
        if b % every == 0:
            k = b // every
            ev[0] = (types[k % len(types)], vels[k % len(vels)])
            nev = 1
        if not declick:
            d.DS[:] = 0.0                       # como era antes: voz roubada some na hora
        render_drums(mix, send, N, ev, nev, d.DV, d.DT, FS, 1.0, d.DS)
        if not declick:
            d.DS[:] = 0.0
        d.ghosts_used = max(getattr(d, "ghosts_used", 0), int((d.DV[-GHOSTS:, DV_ACTIVE] > 0.5).sum()))
        out.append(mix[:, 0].copy())
    return np.concatenate(out)


# 3 vozes, cauda enorme: três batidas audíveis ocupam tudo; as seguintes têm velocidade 0
# (silenciosas), então qualquer degrau medido vem só da voz roubada ou abafada
STEAL = dict(hits=40, every=40, types=(0, 0, 0, 1, 1, 1, 1, 1), vels=(100, 100, 100, 0, 0, 0, 0, 0))
CHOKE = dict(hits=40, every=40, types=(0,), vels=(100, 0, 0, 0))


def _long_tail(voices=3):
    d = _sine_drum_synth(voices)
    d.DT[:, 3] = 30.0
    return d


def test_stolen_drum_voices_do_not_click():
    d = _long_tail()
    x = _hit_fast(d, **STEAL)
    assert d.ghosts_used > 0                     # houve roubo de voz de verdade
    onsets = [k * 40 * N for k in range(40) if STEAL["vels"][k % 8]]
    assert click_score(x, skip=onsets) < LIMIT


def test_hard_cut_would_be_detected():
    """O mesmo cenário cortando a voz na hora (como era antes) precisa ser acusado."""
    d = _long_tail()
    x = _hit_fast(d, **STEAL)
    cut = x.copy()
    k = 3 * 40 * N                              # 1º roubo: tira a voz mais baixa de uma vez
    cut[k:] -= 0.3 * np.sin(2 * np.pi * 110 * np.arange(len(x) - k) / FS + 0.7) * 0.5
    onsets = [i * 40 * N for i in range(40) if STEAL["vels"][i % 8]]
    assert click_score(cut, skip=onsets) > LIMIT


def test_choked_drum_voices_do_not_click():
    x = _hit_fast(_long_tail(8), **CHOKE)
    onsets = [k * 40 * N for k in range(40) if CHOKE["vels"][k % 4]]
    assert click_score(x, skip=onsets) < LIMIT


def test_rapid_pads_keep_free_voices():
    """Pads alternados a cada ~35 ms por 8 s: o abafamento mantém as vozes livres (sem roubo)."""
    e = fresh_engine()
    out = np.zeros((N, 2), np.float32)
    worst = 0
    for b in range(int(FS * 8 / N)):
        if b % 13 == 0:
            e.instruments.pad_hit((0, 1, 2, 6)[(b // 13) % 4], 110)
        e._render(None, out, N)
        worst = max(worst, int((e.drums.DV[:, DV_ACTIVE] > 0.5).sum()))
    assert worst <= 16


@pytest.mark.parametrize("name", DRUM_TYPE_NAMES)
def test_every_drum_retrigger_is_smooth(name):
    """Cada som da bateria batido em rajada (a cada 60 ms) sem degrau entre as batidas."""
    d = DrumSynth(FS)
    k = DRUM_TYPE_NAMES.index(name)
    x = _hit_fast(d, hits=30, every=22, types=(k,))
    assert np.isfinite(x).all() and np.abs(x).max() > 1e-3
    # o ataque de cada batida é transiente de propósito; o resto (cauda e abafamento) não pode
    # ter degraus. Bumbos/toms (tonais) passam no limite normal; caixas/palmas são ruído e só
    # precisam não ter nada absurdo
    noisy = d.DT[k, 5] > 0.3
    assert click_score(x, skip=[i * 22 * N for i in range(30)]) < (25 if noisy else LIMIT)


# ------------------------------------------------------------------ teclas e pad contínuo (FluidSynth)
needs_sf = pytest.mark.skipif(not available(), reason="timbres não baixados (tools/baixar_extras.py)")


@needs_sf
@pytest.mark.parametrize("ready", ["Piano + Cordas", "Piano Brilhante", "Pad Quente Contínuo (nas teclas)",
                                   "Órgão Gospel (rotação)", "Baixo | Piano (divisão em C3)"])
def test_alternating_keys_no_click(ready):
    e = fresh_engine()
    inst = e.instruments
    inst.set_ready(ready)
    notes = [60, 62, 64, 65, 67, 65, 64, 62, 40, 43]
    held = []
    onsets = []
    out = np.zeros((N, 2), np.float32)
    buf = []
    for b in range(int(FS * 3 / N)):           # solta a nota e 10 ms depois toca a próxima
        if b % 20 == 0 and held:
            inst.key_off(held.pop())
        if b % 20 == 4:
            n = notes[(b // 20) % len(notes)]
            inst.key_on(n, 100)
            held.append(n)
            onsets.append(b * N)
        e._render(None, out, N)
        buf.append(out[:, 0].copy())
    x = np.concatenate(buf)
    assert np.abs(x).max() > 0.01
    # o ataque do timbre (ex.: "key click" do órgão) é do instrumento; soltar nota não pode estalar
    assert click_score(x, skip=onsets) < LIMIT


@needs_sf
def test_continuous_pad_key_changes_no_click():
    e = fresh_engine()
    inst = e.instruments
    keys = ["C", "D", "E", "Parar", "G", "A", "B", "C", "Parar"]

    def step(k):
        key = keys[k % len(keys)]
        if key == "Parar":
            inst.stop_cont_pad()
        else:
            inst.start_cont_pad(key)

    x = play(e, step, 375, 9.0)                # troca de tom a cada 1 s
    assert np.abs(x).max() > 0.005
    assert click_score(x) < LIMIT


@needs_sf
def test_rapid_mixed_pads_no_click_on_tonal_parts():
    """Pads da bateria (sintetizados + SoundFont) alternados rápido junto com o pad contínuo."""
    e = fresh_engine()
    inst = e.instruments
    inst.start_cont_pad("D")

    def step(k):
        inst.pad_hit(k % 8, 100)

    x = play(e, step, 13, 4.0)
    assert np.isfinite(x).all() and np.abs(x).max() < 1.0
