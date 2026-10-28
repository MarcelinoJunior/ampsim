"""Cenas/presets compartilháveis, EQ do pad contínuo e taps do RTA."""
import numpy as np
import pytest

from ampsim import sharing
from ampsim.audio.engine import RTA_N, AudioEngine, _ring_write
from ampsim.audio.soundfont import available
from ampsim.dsp.kernels import warmup
from ampsim.dsp.padeq import DEFAULT_PAD_EQ, PadEQ, clean_pad_eq


@pytest.fixture(scope="module")
def engine():
    warmup()
    return AudioEngine()


def test_text_code_roundtrip(engine):
    data = engine.tracks["guitar"].get_state()
    doc = sharing.make_doc("preset", data, "Limpo de domingo", "Ministério X", trilha="guitar")
    code = sharing.to_text(doc)
    assert code.startswith(sharing.TEXT_PREFIX) and "\n" not in code
    # mensagens costumam quebrar a linha e juntar texto antes/depois
    pasted = "olha esse timbre:\n" + code[:40] + "\n " + code[40:] + "  "
    back = sharing.from_text(pasted)
    assert back["nome"] == "Limpo de domingo" and back["dados"]["values"] == data["values"]


def test_file_roundtrip(tmp_path, engine):
    doc = sharing.make_doc("cena", {"tracks": {}}, "Culto", "")
    path = tmp_path / ("c" + sharing.EXTENSION)
    sharing.save_file(path, doc)
    assert sharing.load_file(path)["tipo"] == "cena"


@pytest.mark.parametrize("bad", ["", "AMPSIM1:", "AMPSIM1:abc$$", "oi tudo bem"])
def test_bad_codes_raise(bad):
    with pytest.raises(sharing.ShareError):
        sharing.from_text(bad)


def test_bad_docs_raise(tmp_path):
    p = tmp_path / "x.ampsim"
    for content in ("{", '{"formato": "outro"}', '{"formato": "ampsim", "versao": 99, "tipo": "cena", "dados": {}}',
                    '{"formato": "ampsim", "versao": 1, "tipo": "preset", "trilha": "x", "dados": {}}'):
        p.write_text(content, encoding="utf-8")
        with pytest.raises(sharing.ShareError):
            sharing.load_file(p)


def test_sanitize_track_drops_foreign_paths_and_bad_types():
    st = {"values": {"amp": {"gain": "muito", "bass": 7.0, "hack": 1},
                     "vst": {"path": r"C:\Users\outro\malware.vst3", "state": "AAAA", "on": True},
                     "nam": {"file": r"..\..\segredo", "on": True},
                     "efeito_inexistente": {"x": 1}},
          "ir_path": r"\\servidor\ir.wav"}
    out = sharing.sanitize_track(st)
    v = out["values"]
    assert v["amp"] == {"bass": 7.0}
    assert "path" not in v["vst"] and "state" not in v["vst"] and v["vst"]["on"] is True
    assert "\\" not in v["nam"]["file"] and "/" not in v["nam"]["file"]
    assert "efeito_inexistente" not in v and out["ir_path"] is None


def test_sanitize_instruments_and_scene(engine):
    cur = engine.instruments.get_state()
    st = {"keys": {"sound1": "Pad Quente", "vol1": "alto", "hack": 3}, "levels": {"reverb": 999},
          "pad_sounds": ["x"], "pad_eq": {"lowcut": 5000.0, "voicing": "rm -rf"}, "bpm": 9999}
    out = sharing.sanitize_instruments(st, cur)
    assert out["keys"] == {"sound1": "Pad Quente"}
    assert out["levels"]["reverb"] == 127 and "pad_sounds" not in out and out["bpm"] == 300
    assert out["pad_eq"]["lowcut"] == 800.0 and out["pad_eq"]["voicing"] == "cheio"
    scene = sharing.sanitize_scene({"tracks": {"guitar": {"values": {}}, "evil": {}}, "master_db": 99}, cur)
    assert list(scene["tracks"]) == ["guitar"] and scene["master_db"] == 6.0


def test_clean_pad_eq_clamps():
    out = clean_pad_eq({"highcut": -5, "width": float("nan"), "on": "sim", "gain": True})
    assert out == {"highcut": 1000.0}


def test_pad_eq_cuts_highs():
    eq = PadEQ(48000.0)
    v = dict(DEFAULT_PAD_EQ)
    eq.configure(v)
    flat = eq.response([100.0, 1000.0, 10000.0])
    assert np.allclose(flat, 0.0, atol=0.05)                 # padrão = sem mudança
    v.update(lowcut=300.0, highcut=3000.0)
    eq.configure(v)
    lo, mid, hi = eq.response([60.0, 1000.0, 12000.0])
    assert lo < -24 and abs(mid) < 1.5 and hi < -24


@pytest.mark.skipif(not available(), reason="timbres não baixados (tools/baixar_extras.py)")
def test_pad_eq_in_audio_path(engine):
    inst = engine.instruments
    out = np.zeros((128, 2), np.float32)

    def energy_hi():
        inst.stop_cont_pad(immediate=True)
        engine.pad_eq.reset()
        inst.start_cont_pad("C")
        for _ in range(40):
            inst.tick(0.1)                   # fade-in completo
        buf = []
        for _ in range(200):
            engine._render(None, out, 128)
            buf.append(out[:, 0].copy())
        x = np.concatenate(buf)
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        f = np.fft.rfftfreq(len(x), 1 / 48000)
        return spec[f > 4000].sum() / (spec.sum() + 1e-12)

    inst.set_pad_eq(**DEFAULT_PAD_EQ)
    open_hi = energy_hi()
    inst.set_pad_eq(highcut=1500.0)
    cut_hi = energy_hi()
    inst.set_pad_eq(**DEFAULT_PAD_EQ)
    inst.stop_cont_pad(immediate=True)
    assert open_hi > 0 and cut_hi < open_hi * 0.2


def test_ring_write_wraps():
    buf = np.zeros(8)
    pos = _ring_write(buf, 6, np.arange(1.0, 5.0))
    assert pos == 2 and list(buf) == [3, 4, 0, 0, 0, 0, 1, 2]


def test_rta_taps_only_selected_track(engine):
    engine.rta_track = "guitar"
    engine.tracks["guitar"].set_param("track", "on", True)
    x = np.zeros((256, 2), np.float32)
    x[:, 0] = 0.3 * np.sin(np.arange(256) * 0.2)
    out = np.zeros((256, 2), np.float32)
    p0 = engine.rta_pos_in
    engine._render(x, out, 256)
    assert (engine.rta_pos_in - p0) % RTA_N == 256
    assert np.abs(engine.rta_in).max() > 0.2
    engine.rta_track = None


def test_vocal_preset_from_outside_is_cleaned():
    """Preset/cena de Vocal vindo de fora: faixas conferidas, plugin de outro PC fora, e nunca liga nem
    muta o microfone de quem abre."""
    from ampsim.dsp.vocal import default_values as vocal_defaults
    bad = {"values": {"comp": {"amount": 500, "on": True, "x": 1}, "reverb": {"type": "hall", "mix": float("nan")},
                      "track": {"on": True, "mute": True, "volume": -6, "input_gain": 99},
                      "amp": {"gain": 10}},
           "fx_chain": [{"path": r"Z:\outro_pc\Plugin.vst3", "on": True, "mix": 100}]}
    out = sharing.sanitize_kind("vocal", bad)
    v = out["values"]
    assert v["comp"]["amount"] == 100 and v["comp"]["on"] is True and "x" not in v["comp"]
    assert v["reverb"] == vocal_defaults()["reverb"]
    assert "on" not in v["track"] and "mute" not in v["track"]
    assert v["track"]["volume"] == -6 and v["track"]["input_gain"] == 36
    assert "amp" not in v and out["fx_chain"] == []
    doc = sharing.make_doc("preset", out, "Voz", trilha="vocal")
    assert sharing.from_text(sharing.to_text(doc))["trilha"] == "vocal"
    assert sharing.KIND_TITLES["vocal"].startswith("Vocal")
