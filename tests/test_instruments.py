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
    assert [s.name for s, *_ in low] == ["Baixo Finger"]
    assert [s.name for s, *_ in high] == ["Piano de Cauda"]


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
    engine.instruments.stop_cont_pad(immediate=True)
    inst = engine.instruments
    inst.set_ready("Rhodes + Pad")
    inst.knob_funcs[0] = "Reverb"
    st = inst.get_state()
    inst.set_ready("Piano Brilhante")
    inst.load_state(st)
    assert inst.ready == "Rhodes + Pad" and inst.knob_funcs[0] == "Reverb"
    assert SOUND_BY_NAME[inst.keys["sound1"]].name == "Rhodes com Chorus"


def test_all_pad_sounds_and_presets(engine):
    from ampsim.instruments import PAD_PRESETS, PAD_SOUND_BY_NAME, PAD_SOUNDS

    inst = engine.instruments
    for p, names in PAD_PRESETS.items():
        assert all(n in PAD_SOUND_BY_NAME for n in names), p
    for s in PAD_SOUNDS:
        if s.kind == "sf2":
            assert (s.bank, s.prog) in inst.sf.presets, s.name
    for name in PAD_PRESETS:
        inst.set_pad_preset(name)
        for i in range(8):
            inst.pad_hit(i, 110)
        assert 0.05 < render(engine, 0.4) <= 1.0, name
        render(engine, 1.0)


def test_continuous_pad_fades_and_stops(engine):
    inst = engine.instruments

    def run(sec):
        peak = 0.0
        for _ in range(int(sec / 0.033)):
            peak = max(peak, render(engine, 0.033))
            inst.tick(0.033)
        return peak

    inst.pad_hit(8, 100)                      # banco B, pad 1 = C
    assert inst.cont_key == "C"
    assert run(3.0) > 0.02
    inst.pad_hit(9, 100)                      # troca para D (crossfade)
    assert inst.cont_key == "D"
    run(4.0)
    assert len(inst._cp) == 1                 # o C já saiu
    inst.pad_hit(15, 100)                     # Parar
    assert inst.cont_key is None
    run(4.5)
    assert not inst._cp and render(engine, 0.3) < 0.02


def test_synth_drums_and_shimmer_are_finite(engine):
    import numpy as np

    from ampsim.dsp.worship import DRUM_TYPE_NAMES, DrumSynth, ShimmerDSP, render_drums

    d = DrumSynth(48000.0)
    mix = np.zeros((48000, 2))
    send = np.zeros(48000)
    for i in range(len(DRUM_TYPE_NAMES)):
        d.ev[i] = (i, 120)
    render_drums(mix, send, 48000, d.ev, len(DRUM_TYPE_NAMES), d.DV, d.DT, 48000.0, 1.0, d.DS)
    sh = ShimmerDSP(48000.0)
    out = np.zeros((48000, 2))
    sh.process(send, 48000, out, 1.0, 0.7)
    assert np.all(np.isfinite(mix)) and np.all(np.isfinite(out))
    assert np.abs(out).max() > 1e-3


def test_learning_bank_b(engine):
    inst = engine.instruments
    inst.start_learning(("pads_b",))
    assert inst.screen_bank in (0, 1)
    inst.handle_midi(0xB0, 30, 127)           # o botão PAD-B (CC): ignorado
    inst.handle_midi(0x99, 60, 100)
    assert inst.mapping["pads_b"][0] == [9, 60]
    inst.stop_learning()


def test_shimmer_tail_dies_out_even_at_max():
    """O laço do Shimmer tem ganho < 1: depois de um impulso, o rastro some (sem disparar)."""
    import numpy as np

    from ampsim.dsp.worship import ShimmerDSP

    sh = ShimmerDSP(48000.0)
    n = 512
    x = np.zeros(n)
    peaks = []
    for blk in range(int(48000 * 60 / n)):
        x[:] = 0.0
        if blk == 0:
            x[0] = 1.0
        out = np.zeros((n, 2))
        sh.process(x, n, out, 1.0, 0.9)            # mais realimentação do que o app usa
        peaks.append(np.abs(out).max())
    peaks = np.array(peaks)
    assert np.all(np.isfinite(peaks))
    assert peaks[-200:].max() < peaks[:200].max() * 0.01


def test_shimmer_recovers_from_nan_and_output_never_nan():
    import numpy as np

    from ampsim.dsp.kernels import write_output
    from ampsim.dsp.worship import ShimmerDSP

    sh = ShimmerDSP(48000.0)
    sh.B[100] = np.nan
    x = np.full(256, 0.1)
    for _ in range(50):
        out = np.zeros((256, 2))
        sh.process(x, 256, out, 1.0, 0.6)
    assert np.all(np.isfinite(out)) and np.abs(out).max() > 0
    mix = np.full((64, 2), np.nan)
    dev = np.zeros((64, 2), dtype=np.float32)
    write_output(mix, 64, dev, 0, 1.0)
    assert np.all(dev == 0) and np.all(mix == 0)


def test_long_worship_session_stays_stable(engine):
    """Notas longas + pad contínuo + Shimmer no máximo por 60 s: nível estável."""
    import numpy as np

    inst = engine.instruments
    engine.master = 1.0
    inst.set_ready("Coral Etéreo")
    inst.levels.update(keys=80, pad=70, drums=85, shimmer=100)
    for k in (48, 55, 60, 64, 67):
        inst.key_on(k, 127)
    inst.pad_hit(8, 120)
    n = 256
    out = np.zeros((n, 2), np.float32)
    peaks = []
    for blk in range(int(48000 * 60 / n)):
        engine._render(None, out, n)
        inst.tick(n / 48000)
        peaks.append(float(np.abs(out).max()))
    inst.all_off()
    inst.stop_cont_pad(immediate=True)
    peaks = np.array(peaks)
    assert np.all(np.isfinite(peaks))
    third = len(peaks) // 3
    assert peaks[-third:].max() < 0.9                       # não encosta no limitador
    assert peaks[-third:].max() < peaks[third:2 * third].max() * 1.5   # não cresce sozinho


def test_pulse_bass_follows_bpm_and_tap(engine):
    import time

    import numpy as np

    inst = engine.instruments
    inst.all_off()
    inst.set_bpm(120)
    inst.set_ready("Baixo Pulsante (BPM)")
    inst.key_on(40, 110)
    n = 128
    out = np.zeros((n, 2), np.float32)
    env = []
    for _ in range(int(48000 * 4 / n)):
        engine._render(None, out, n)
        env.append(float(np.sqrt((out[:, 0] ** 2).mean())))
    inst.all_off()
    x = np.array(env[len(env) // 4:])
    x -= x.mean()
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    period = (np.argmax(ac[40:200]) + 40) * n / 48000
    assert abs(period - 0.25) < 0.02            # 1/8 a 120 BPM
    for _ in range(4):
        inst.tap_tempo()
        time.sleep(0.4)
    assert abs(inst.bpm - 150) <= 3


def test_default_pads_match_controller_rows(engine):
    """Fileira de baixo do SMK-25 = notas 36-39; na tela os pads 1-4 são a fileira de cima."""
    inst = engine.instruments
    inst.mapping["pads"] = [[9, n] for n in (40, 41, 42, 43, 36, 37, 38, 39)]
    hits = []
    inst.on_pad = lambda i, v: hits.append(i)
    inst.handle_midi(0x99, 40, 100)            # pad de cima à esquerda
    inst.handle_midi(0x99, 36, 100)            # pad de baixo à esquerda
    assert hits == [0, 4]


def test_old_inverted_pad_default_is_fixed_on_load(engine):
    from ampsim.instruments import DEFAULT_PADS, DEFAULT_PADS_B, OLD_DEFAULT_PADS, OLD_DEFAULT_PADS_B
    inst = engine.instruments
    inst.load_state({"mapping": {"pads": OLD_DEFAULT_PADS, "pads_b": OLD_DEFAULT_PADS_B}})
    assert inst.mapping["pads"] == DEFAULT_PADS and inst.mapping["pads_b"] == DEFAULT_PADS_B
    mine = [[9, n] for n in (60, 61, 62, 63, 64, 65, 66, 67)]          # mapeamento feito pelo usuário
    inst.load_state({"mapping": {"pads": mine}})
    assert inst.mapping["pads"] == mine


def test_unmapped_knob_is_reported_and_knob_learning(engine):
    inst = engine.instruments
    inst.mapping["knobs"] = [None] * 8
    seen, moved = [], []
    inst.on_unmapped = lambda ch, cc: seen.append(cc)
    inst.on_knob = lambda i, v: moved.append((i, v))
    inst.handle_midi(0xB0, 74, 50)             # knob ainda sem mapeamento
    inst.handle_midi(0xB0, 64, 127)            # sustain: não é knob
    assert seen == [74] and moved == []
    inst.start_learning(("knobs",))            # "Só os knobs"
    assert [k for k, _ in inst.learn_steps] == ["knobs"] * 8
    inst.handle_midi(0xB0, 74, 51)
    inst.stop_learning()
    inst.handle_midi(0xB0, 74, 99)
    assert moved and moved[-1] == (0, 99) and seen == [74]   # agora mexe o knob 1 da tela


def test_describe_midi_for_monitor(engine):
    inst = engine.instruments
    inst.mapping["pads"] = [[9, n] for n in (40, 41, 42, 43, 36, 37, 38, 39)]
    inst.mapping["knobs"] = [[0, 70]] + [None] * 7
    inst.knob_funcs[0] = "Reverb"
    assert inst.describe_midi("note", 9, 36, 100).endswith("pad 5 do banco A")
    assert inst.describe_midi("note", 0, 60, 90).endswith("tecla C4")
    assert inst.describe_midi("cc", 0, 70, 10).endswith("knob 1 (Reverb)")
    assert inst.describe_midi("cc", 0, 99, 10).endswith("NÃO MAPEADO")
    assert inst.describe_midi("cc", 0, 64, 127).endswith("sustain")
    assert "Pitch bend" in inst.describe_midi("bend", 0, 0, 64)


SAME = [[9, n] for n in (40, 41, 42, 43, 36, 37, 38, 39)]


def test_pad_b_button_switches_bank_when_pads_send_same_notes(engine):
    """M-VAVE: os pads mandam as mesmas notas nos dois bancos; o PAD-B é que troca."""
    inst = engine.instruments
    inst.stop_learning()
    inst.mapping["pads"] = [list(p) for p in SAME]
    inst.mapping["pads_b"] = [list(p) for p in SAME]
    inst.mapping["buttons"] = [None] * 7 + [["cc", 0, 30]]
    inst.button_funcs[7] = "Banco de pads A/B (tela)"
    hits = []
    inst.on_pad = lambda i, v: hits.append(i)
    inst.handle_midi(0x99, 40, 100)
    assert hits[-1] == 0                                 # banco A: bateria
    inst.handle_midi(0xB0, 30, 127)                      # aperta PAD-B
    assert inst.screen_bank == 1
    inst.handle_midi(0x99, 40, 100)
    assert hits[-1] == 8                                 # mesmo pad agora é o 1º do banco B
    inst.handle_midi(0xB0, 30, 0)                        # soltou logo: não troca de novo
    assert inst.screen_bank == 1
    inst.handle_midi(0xB0, 30, 127)                      # aperta de novo: volta para o A
    inst.handle_midi(0x99, 40, 100)
    assert inst.screen_bank == 0 and hits[-1] == 0
    inst.stop_cont_pad(immediate=True)


def test_latching_button_toggles_on_both_values(engine, monkeypatch):
    import ampsim.instruments as ins
    inst = engine.instruments
    inst.mapping["buttons"] = [None] * 7 + [["cc", 0, 31]]
    inst.button_funcs[7] = "Banco de pads A/B (tela)"
    inst.screen_bank = 0
    t = [100.0]
    monkeypatch.setattr(ins.time, "monotonic", lambda: t[0])
    inst.handle_midi(0xB0, 31, 127)                      # botão que trava: 1º toque manda 127
    assert inst.screen_bank == 1
    t[0] += 5.0
    inst.handle_midi(0xB0, 31, 0)                        # 2º toque (bem depois) manda 0
    assert inst.screen_bank == 0


def test_learning_pads_with_same_notes_in_both_banks_and_pc_button(engine):
    inst = engine.instruments
    inst.start_learning(("pads", "pads_b"))
    for bank in range(2):
        for _, n in SAME:
            inst.handle_midi(0x99, n, 100)
    assert not inst.learn_steps                          # o banco B aceitou as mesmas notas
    assert inst.mapping["pads_b"] == SAME
    inst.start_learning(("buttons",))
    for _ in range(7):
        inst.skip_learning_step()
    inst.handle_midi(0xC0, 5, 0)                         # PAD-B que manda Program Change
    assert inst.mapping["buttons"][7] == ["pc", 0, 5]
    inst.button_funcs[7] = "Banco de pads A/B (tela)"
    inst.screen_bank = 0
    inst.handle_midi(0xC0, 5, 0)
    assert inst.screen_bank == 1
    assert "botão PAD-B" in inst.describe_midi("pc", 0, 5, 0)
    inst.screen_bank = 0
