"""Controlador MIDI nas abas Guitarra, Baixo e Vocal e nos plugins (midi_map.py, ui/ctl_map_ui.py): aprender
um CC e mexer no efeito, nota/CC liga-desliga, parâmetro interno de plugin, sessão, conflito de controle e
o Pad/Piano continuando igual."""
import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ampsim import midi_map as MM  # noqa: E402
from ampsim import storage  # noqa: E402
from ampsim.audio import vst  # noqa: E402
from ampsim.audio.engine import AudioEngine  # noqa: E402


# ------------------------------------------------------------------ plugin falso com parâmetros
class FakeParam:
    def __init__(self, name, raw):
        self.name, self.raw_value, self.label = name, raw, "%"
        self.threads = []

    def get_text_for_raw_value(self, r, maximum_string_length=512):
        return f"{r * 100:.0f}"


class FakePlugin:
    is_effect, is_instrument = True, False

    def __init__(self, path):
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.gain = 0.5
        self._parameters = [FakeParam("Dry Level", 0.8), FakeParam("Wet Level", 0.3), FakeParam("Decay", 0.5),
                            FakeParam("MIDI CC 0|1", 0.0)]

    @property
    def raw_state(self):
        return json.dumps({"g": self.gain}).encode()

    @raw_state.setter
    def raw_state(self, b):
        self.gain = json.loads(b.decode())["g"]

    def process(self, x, fs, buffer_size=8192, reset=True):
        return np.array(x, dtype=np.float32) * self.gain

    def reset(self):
        pass

    def show_editor(self, ev=None):
        ev.wait(5.0)

    def param(self, name):
        return next(p for p in self._parameters if p.name == name)


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    """fake(nome) -> caminho de um pacote .vst3 de mentira numa pasta de VST3 do usuário de mentira."""
    user = tmp_path / "VST3"
    monkeypatch.setenv("AMPSIM_USER_VST3_DIR", str(user))
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "appdir")
    vst.reset_caches()
    made = []

    def load(path):
        p = FakePlugin(path)
        made.append(p)
        return p
    monkeypatch.setattr(vst, "_load_plugin", load)

    def add(name):
        d = user / f"{name}.vst3"
        (d / "Contents" / "x86_64-win").mkdir(parents=True, exist_ok=True)
        (d / "Contents" / "x86_64-win" / f"{name}.vst3").write_bytes(b"x")
        return str(d)
    add.made = made
    yield add
    vst.reset_caches()


@pytest.fixture(scope="module")
def engine():
    return AudioEngine()


@pytest.fixture()
def inst(engine):
    i = engine.instruments
    saved = (dict(i.free_map), dict(i.ctl_map), {k: list(v) for k, v in i.mapping.items()}, list(i.button_latch))
    i.ctl_map = {}
    i.ctl.wake = None
    i.capture = False
    i.learn_steps = []
    for name in ("guitar", "bass", "vocal"):
        engine.tracks[name].fx_chain.clear()
    yield i
    i.free_map, i.ctl_map = saved[0], saved[1]
    i.mapping = saved[2]
    i.button_latch = saved[3]
    for name in ("guitar", "bass", "vocal"):
        engine.tracks[name].fx_chain.clear()
    i.ctl.wake = None


def mapit(inst, tid, key, plugin=""):
    inst.ctl_map[tid] = MM.make_entry(tid, key, plugin=plugin)


# ------------------------------------------------------------------ ids e valores
def test_every_screen_control_has_a_valid_id():
    for track in MM.TRACKS:
        ids = MM.track_targets(track)
        assert ids and all(MM.target_info(t) is not None for t in ids), track
    assert MM.target_info("guitar/amp/model") is None              # o seletor do amp não é um knob
    assert MM.target_info("guitar/delay/naoexiste") is None
    assert MM.target_info("fx/L1/1/param:Wet Level")["name"] == "Wet Level"
    assert MM.target_info("fx/master/5/mix") is None
    assert MM.kinds_for("guitar/delay/mix") == ("cc",)
    assert "note" in MM.kinds_for("guitar/delay/on")
    info = MM.target_info("vocal/reverb/mix")
    assert info["group"] == "Vocal" and info["label"] == "Vocal › Reverb › Mix"


def test_cc_value_follows_the_knob_curve():
    p = MM.track_param("guitar", "delay", "time")                   # 20-2000 ms, logarítmico
    assert MM.cc_to_value(p, 0) == pytest.approx(20) and MM.cc_to_value(p, 127) == pytest.approx(2000)
    assert MM.cc_to_value(p, 64) == pytest.approx(20 * 100 ** (64 / 127))
    p = MM.track_param("guitar", "comp", "makeup")
    assert MM.cc_to_value(p, 127) == 24


# ------------------------------------------------------------------ sem janela (aplica na hora)
def test_learned_cc_moves_a_guitar_effect(inst, engine):
    g = engine.tracks["guitar"]
    mapit(inst, "guitar/delay/mix", ["cc", 0, 21])
    inst.handle_midi(0xB0, 21, 127)
    assert g.values["delay"]["mix"] == 100
    inst.handle_midi(0xB0, 21, 0)
    assert g.values["delay"]["mix"] == 0
    mapit(inst, "bass/amp/gain", ["cc", 0, 22])
    inst.handle_midi(0xB0, 22, 127)
    assert engine.tracks["bass"].values["amp"]["gain"] == 10
    mapit(inst, "vocal/track/volume", ["cc", 1, 23])
    inst.handle_midi(0xB1, 23, 0)
    assert engine.tracks["vocal"].values["track"]["volume"] == -60
    assert "Guitarra › Delay › Mix" in inst.describe_midi("cc", 0, 21, 5)


def test_note_and_cc_toggle_on_off_and_note_does_not_play(inst, engine, monkeypatch):
    g = engine.tracks["guitar"]
    keys = []
    monkeypatch.setattr(inst, "key_on", lambda n, v=100: keys.append(n))
    mapit(inst, "guitar/reverb/on", ["note", 0, 60])
    was = g.values["reverb"]["on"]
    inst.handle_midi(0x90, 60, 100)
    inst.handle_midi(0x80, 60, 0)                 # soltar não alterna de novo
    inst.handle_midi(0x90, 60, 0)
    assert g.values["reverb"]["on"] is (not was) and keys == []
    inst.handle_midi(0x90, 61, 100)               # outra tecla continua tocando
    assert keys == [61]
    # CC de botão: 127 ao apertar e 0 ao soltar (o 0 logo depois não conta)
    mapit(inst, "guitar/chorus/on", ["cc", 0, 80])
    was = g.values["chorus"]["on"]
    inst.handle_midi(0xB0, 80, 127)
    inst.handle_midi(0xB0, 80, 0)
    assert g.values["chorus"]["on"] is (not was)
    inst.handle_midi(0xB0, 80, 127)
    inst.handle_midi(0xB0, 80, 0)
    assert g.values["chorus"]["on"] is was
    # programa (PC) também serve para liga/desliga
    mapit(inst, "bass/overdrive/on", ["pc", 0, 5])
    was = engine.tracks["bass"].values["overdrive"]["on"]
    inst.handle_midi(0xC0, 5, 0)
    assert engine.tracks["bass"].values["overdrive"]["on"] is (not was)


class _Clock:
    """time.monotonic de mentira: "segurar o botão" X segundos sem esperar de verdade."""

    def __init__(self, monkeypatch):
        self.t = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: self.t)

    def wait(self, s):
        self.t += s


@pytest.mark.parametrize("held", [0.05, 2.0, 5.0])
def test_momentary_button_held_long_toggles_once(inst, engine, monkeypatch, held):
    """Pedal/botão momentâneo segurado: o 0 da soltura nunca alterna de novo (o microfone não liga e desliga)."""
    clock = _Clock(monkeypatch)
    v = engine.tracks["vocal"]
    v.set_switch("on", False)
    mapit(inst, "vocal/track/on", ["cc", 0, 64])
    for n in range(1, 4):
        inst.handle_midi(0xB0, 64, 127)                   # aperta
        clock.wait(held)
        inst.handle_midi(0xB0, 64, 0)                     # solta depois de `held` s
        clock.wait(0.3)
        assert v.values["track"]["on"] is (n % 2 == 1), (held, n)
    v.set_switch("on", False)


def test_latching_button_toggles_on_every_message(inst, engine, monkeypatch):
    clock = _Clock(monkeypatch)
    g = engine.tracks["guitar"]
    inst.ctl_map["guitar/delay/on"] = MM.make_entry("guitar/delay/on", ["cc", 0, 85], latch=True)
    assert inst.ctl_map["guitar/delay/on"]["latch"] is True
    was = g.values["delay"]["on"]
    inst.handle_midi(0xB0, 85, 127)                       # 1º toque: trava (manda 127)
    assert g.values["delay"]["on"] is (not was)
    clock.wait(4.0)
    inst.handle_midi(0xB0, 85, 0)                         # 2º toque: destrava (manda 0)
    assert g.values["delay"]["on"] is was
    for _ in range(6):                                    # toques rápidos: cada um alterna
        inst.handle_midi(0xB0, 85, 127)
        clock.wait(0.05)
        inst.handle_midi(0xB0, 85, 0)
        clock.wait(0.05)
    assert g.values["delay"]["on"] is was
    # momentâneo com toques rápidos: um por toque
    mapit(inst, "guitar/chorus/on", ["cc", 0, 86])
    was = g.values["chorus"]["on"]
    for _ in range(3):
        inst.handle_midi(0xB0, 86, 127)
        clock.wait(0.03)
        inst.handle_midi(0xB0, 86, 0)
        clock.wait(0.03)
    assert g.values["chorus"]["on"] is (not was)
    # o tipo só vale para liga/desliga e ação num CC; vai na sessão
    assert "latch" not in MM.make_entry("guitar/delay/mix", ["cc", 0, 1], latch=True)
    assert "latch" not in MM.make_entry("guitar/delay/on", ["note", 0, 1], latch=True)
    st = json.loads(json.dumps(inst.get_state()))
    inst.ctl_map = {}
    inst.load_state(st)
    assert inst.ctl_map["guitar/delay/on"].get("latch") is True
    assert "latch" not in inst.ctl_map["guitar/chorus/on"]          # sem o campo: momentâneo


@pytest.mark.parametrize("held", [0.05, 2.0, 5.0])
def test_pad_piano_button_same_rule(inst, monkeypatch, held):
    clock = _Clock(monkeypatch)
    pressed = []
    monkeypatch.setattr(inst, "button", lambda i: pressed.append(i))
    inst.mapping["buttons"][3] = ["cc", 0, 115]
    inst.button_latch[3] = False
    inst.handle_midi(0xB0, 115, 127)
    clock.wait(held)
    inst.handle_midi(0xB0, 115, 0)
    assert pressed == [3]                                 # momentâneo: um toque, segurando o quanto for
    inst.button_latch[3] = True
    inst.handle_midi(0xB0, 115, 127)
    clock.wait(held)
    inst.handle_midi(0xB0, 115, 0)
    assert pressed == [3, 3, 3]                           # que trava: os dois toques
    inst.button_latch[3] = False


def test_choice_by_knob_and_by_button(inst, engine):
    v = engine.tracks["vocal"]
    mapit(inst, "vocal/reverb/type", ["cc", 0, 30])
    inst.handle_midi(0xB0, 30, 0)
    assert v.values["reverb"]["type"] == 0
    inst.handle_midi(0xB0, 30, 127)
    assert v.values["reverb"]["type"] == 2
    mapit(inst, "vocal/reverb/type", ["note", 0, 90])
    inst.handle_midi(0x90, 90, 100)
    assert v.values["reverb"]["type"] == 0                        # passa para a próxima (dá a volta)


def test_microphone_only_turns_on_from_the_controller(inst, engine):
    v = engine.tracks["vocal"]
    v.set_switch("on", False)
    mapit(inst, "vocal/track/on", ["note", 0, 99])
    st = inst.get_state()
    inst.load_state(st)                                           # abrir a sessão não liga o microfone
    assert v.values["track"]["on"] is False and "vocal/track/on" in inst.ctl_map
    inst.handle_midi(0x90, 99, 100)                               # o toque no controle mapeado liga
    assert v.values["track"]["on"] is True
    inst.handle_midi(0x90, 99, 100)
    assert v.values["track"]["on"] is False


def test_preset_buttons_call_the_screen(inst):
    got = []
    inst.ctl.on_preset = lambda track, d: got.append((track, d))
    mapit(inst, "bass/preset/next", ["cc", 0, 40])
    mapit(inst, "bass/preset/prev", ["cc", 0, 41])
    inst.handle_midi(0xB0, 40, 127)
    inst.handle_midi(0xB0, 41, 127)
    assert got == [("bass", 1), ("bass", -1)]
    inst.ctl.on_preset = lambda track, d: None


def test_knob_turning_is_coalesced_until_the_interface_applies(inst, engine):
    g = engine.tracks["guitar"]
    woke = []
    inst.ctl.wake = lambda: woke.append(threading.current_thread().name)
    mapit(inst, "guitar/delay/feedback", ["cc", 0, 21])
    for v in range(0, 128, 8):
        inst.handle_midi(0xB0, 21, v)
    assert len(woke) == 1                                          # um aviso só para a interface
    assert inst.ctl.flush() == ["guitar/delay/feedback"]           # só o último valor é aplicado
    assert g.values["delay"]["feedback"] == pytest.approx(95 * 120 / 127)


# ------------------------------------------------------------------ parâmetros de plugin
def test_plugin_parameter_mapping(inst, engine, fake):
    path = fake("Room Reverb")
    chain = engine.tracks["guitar"].fx_chain
    slot = chain.add(path, wait=True)
    chain.wait()
    names = [p["name"] for p in slot.param_list()]
    assert names == ["Dry Level", "Wet Level", "Decay"]           # "MIDI CC 0|1" do JUCE fica de fora
    mapit(inst, "fx/guitar/1/param:Wet Level", ["cc", 0, 50], plugin=vst.portable_ref(path))
    mapit(inst, "fx/guitar/1/mix", ["cc", 0, 51], plugin=vst.portable_ref(path))
    mapit(inst, "fx/guitar/1/on", ["note", 0, 52], plugin=vst.portable_ref(path))
    inst.handle_midi(0xB0, 50, 127)
    chain.wait()
    plug = fake.made[-1]
    assert plug.param("Wet Level").raw_value == pytest.approx(1.0)
    inst.handle_midi(0xB0, 51, 0)
    assert slot.mix == 0
    on = slot.on
    inst.handle_midi(0x90, 52, 100)
    assert slot.on is (not on)
    # outro plugin na frente: o mapeamento segue o plugin (agora no lugar 2)
    chain.add(fake("Outro"), wait=True)
    chain.move(1, -1)
    chain.wait()
    inst.handle_midi(0xB0, 50, 0)
    chain.wait()
    assert plug.param("Wet Level").raw_value == pytest.approx(0.0)
    assert fake.made[-1].param("Wet Level").raw_value == pytest.approx(0.3)     # o outro não mexe
    # plugin ausente: o mapeamento fica inativo, sem erro
    chain.clear()
    chain.wait()
    inst.handle_midi(0xB0, 50, 64)
    assert not inst.ctl.active("fx/guitar/1/param:Wet Level", inst.ctl_map["fx/guitar/1/param:Wet Level"])
    assert "inativo" in inst.describe_midi("cc", 0, 50, 64)


def test_plugin_parameter_goes_through_the_plugin_thread_coalesced(engine, fake, monkeypatch):
    path = fake("Room Reverb")
    chain = engine.tracks["bass"].fx_chain
    slot = chain.add(path, wait=True)
    chain.wait()
    posted = []
    orig = vst.host().post
    monkeypatch.setattr(vst.host(), "post", lambda fn: (posted.append(fn), orig(fn)))
    plug = fake.made[-1]
    seen = []
    p = plug.param("Decay")

    class Spy:
        name = "Decay"

        @property
        def raw_value(self):
            return p.raw_value

        @raw_value.setter
        def raw_value(self, v):
            seen.append((v, threading.current_thread().name))
            p.raw_value = v
    vst._param_index(slot.inst, plug)["Decay"] = Spy()
    gate = threading.Event()
    orig(lambda: gate.wait(2.0))                    # thread dos plugins ocupada: os valores se juntam
    for i in range(20):
        assert slot.set_param("Decay", i / 19)
    assert len(posted) == 1                         # um trabalho só na fila, com o último valor
    gate.set()
    chain.wait()
    assert seen == [(1.0, "AmpSim-plugins")]
    chain.clear()
    chain.wait()
    assert slot.set_param("Decay", 0.5) is False                   # sem plugin: nada


# ------------------------------------------------------------------ sessão e perfil do controlador
def test_session_and_device_profile_keep_the_mappings(inst, engine):
    mapit(inst, "guitar/delay/mix", ["cc", 0, 21])
    mapit(inst, "fx/master/1/param:Wet", ["cc", 0, 22], plugin="vst3:Dragonfly.vst3")
    st = json.loads(json.dumps(inst.get_state()))
    inst.ctl_map = {}
    inst.load_state(st)
    assert inst.ctl_map["guitar/delay/mix"]["key"] == ["cc", 0, 21]
    assert inst.ctl_map["fx/master/1/param:Wet"] == {"key": ["cc", 0, 22], "label": "Plugins Master › 1 › Wet",
                                                    "plugin": "vst3:Dragonfly.vst3", "param": "Wet"}
    # lixo do arquivo é ignorado
    bad = {"guitar/amp/model": {"key": ["cc", 0, 1]}, "x/y/z": {"key": ["cc", 0, 2]},
           "guitar/delay/mix": {"key": ["note", 0, 3]},             # knob só por CC
           "guitar/delay/on": {"key": ["cc", 99, 3]}, "guitar/reverb/mix": "abc"}
    assert MM.clean_ctl_map(bad) == {}
    # cada controlador tem os seus (como o mapeamento do Pad/Piano)
    old_dev, old_maps = inst.midi_device, dict(inst.device_maps)
    try:
        inst.midi_device, inst.device_maps = "", {}
        inst.use_midi_device("Teclado A")
        assert "guitar/delay/mix" in inst.ctl_map
        inst.use_midi_device("Teclado B")
        assert inst.ctl_map == {}
        mapit(inst, "bass/reverb/mix", ["cc", 0, 7])
        inst.use_midi_device("Teclado A")
        assert "guitar/delay/mix" in inst.ctl_map and "bass/reverb/mix" not in inst.ctl_map
        assert "bass/reverb/mix" in inst.get_state()["device_maps"]["Teclado B"]["ctl_map"]
    finally:
        inst.midi_device, inst.device_maps = old_dev, old_maps


BAD_ITEMS = [["cc", 0, 40], "x", 7, None, [0], [0, 200], [16, 3], [True, 3], [0, 3.5], {"a": 1}, [0, "1"], []]


def test_malformed_mappings_are_dropped_on_load(inst, engine):
    """state.json mexido/estragado (ex.: knobs com ["cc", 0, 40]) não derruba a abertura: o item vira None."""
    st = inst.get_state()
    st["mapping"] = {"knobs": BAD_ITEMS[:8], "pads": BAD_ITEMS[4:12], "pads_b": "lixo",
                     "buttons": [["cc", 0, 20], ["xx", 0, 1], ["note", 99, 1], ["pc", 0, 300], ["cc", 0],
                                 [None, 0, 1], ["note", 0, True], 5]}
    st["free_map"] = {"Reverb": ["cc", 0, 74], "Shimmer": ["note", 0, 60], "Inventada": ["cc", 0, 1],
                      "BPM": "cc", "Próximo timbre": ["note", 0, 200], "Oitava +": ["pc", 0, 3]}
    st["ctl_map"] = {"guitar/delay/mix": {"key": ["cc", 0, "21"]}, "guitar/delay/on": {"key": ["cc", 0, 21],
                     "latch": "sim"}, 5: {}, "bass/reverb/mix": []}
    st["button_latch"] = [1, 0]
    old_pads_b = [list(x) if x else None for x in inst.mapping["pads_b"]]
    inst.load_state(st)
    m = inst.mapping
    assert m["knobs"] == [None] * 8
    assert m["pads"] == [None] * 8
    assert m["pads_b"] == old_pads_b                     # lista estragada: fica o que estava
    assert m["buttons"] == [["cc", 0, 20]] + [None] * 7
    assert inst.free_map == {"Reverb": ["cc", 0, 74], "Oitava +": ["pc", 0, 3]}
    assert inst.ctl_map == {"guitar/delay/on": {"key": ["cc", 0, 21], "label": "Guitarra › Delay › liga/desliga"}}
    assert inst.button_latch == [False] * 8
    from ampsim.ui.midi_learn import key_text
    for bad in BAD_ITEMS + [["cc", "x", 1], ("cc", 0, 1, 2)]:
        key_text(bad)                                     # nunca derruba a tela


def test_malformed_controller_profiles_are_cleaned(inst):
    old_dev, old_maps = inst.midi_device, dict(inst.device_maps)
    try:
        st = inst.get_state()
        st["midi_device"] = "Teclado A"
        st["device_maps"] = {"Teclado B": {"mapping": {"knobs": BAD_ITEMS[:8], "buttons": "x"},
                                           "free_map": {"Reverb": ["cc", 0, "1"]}, "button_latch": "x",
                                           "ctl_map": {"vocal/track/on": {"key": ["cc", 0, 9], "latch": True}}},
                             "Ruim": 5, 7: {}}
        inst.load_state(st)
        assert set(inst.device_maps) == {"Teclado B"}
        inst.use_midi_device("Teclado B")
        assert inst.mapping["knobs"] == [None] * 8
        assert inst.mapping["buttons"] == inst.default_mapping("Teclado B")["buttons"]
        assert inst.free_map == {} and inst.button_latch == [False] * 8
        assert inst.ctl_map["vocal/track/on"]["latch"] is True
    finally:
        inst.midi_device, inst.device_maps = old_dev, old_maps


def test_pad_piano_mapping_is_unchanged(inst, engine, monkeypatch):
    inst.free_map = {"Reverb": ["cc", 0, 74]}
    inst.mapping["knobs"][0] = [0, 75]
    inst.knob_funcs[0] = "Shimmer"
    mapit(inst, "guitar/delay/mix", ["cc", 0, 21])
    inst.handle_midi(0xB0, 74, 127)
    assert inst.levels["reverb"] == 127
    inst.handle_midi(0xB0, 75, 0)
    assert inst.levels["shimmer"] == 0
    keys = []
    monkeypatch.setattr(inst, "key_on", lambda n, v=100: keys.append(n))
    inst.handle_midi(0x90, 64, 90)
    assert keys == [64]
    # conflito: o mesmo CC já usado no Pad/Piano aparece para a pessoa decidir
    found = [d for d, _ in MM.conflicts(inst, ["cc", 0, 74])]
    assert found == ["Pad/Piano: Reverb"]
    assert [d for d, _ in MM.conflicts(inst, ["cc", 3, 75])] == ["Pad/Piano: knob 1 da tela (Shimmer)"]
    assert MM.is_plain_key(inst, ["note", 0, 64])
    assert not MM.is_plain_key(inst, ["note", 9, 40])               # pad do banco A


# ------------------------------------------------------------------ interface
@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from ampsim.ui.theme import STYLE
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture()
def win(app, tmp_path, monkeypatch, fake):
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "app" / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "app" / "presets")
    monkeypatch.setattr(storage, "SHARE_DIR", tmp_path / "Documentos" / "AmpSim")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    w.resize(1536, 800)
    w.show()
    app.processEvents()
    yield w
    w.timer.stop()
    w.close()
    w.deleteLater()
    app.processEvents()


def _fake_dialog(monkeypatch, choice, seen=None):
    from ampsim.ui import ctl_map_ui

    class Fake:
        def __init__(self, inst, bridge, func, parent=None, kinds=None, current=None, want=None, latch=None):
            if seen is not None:
                seen.append(dict(func=func, kinds=kinds, current=current))
            self.choice = choice

        def exec(self):
            return True
    monkeypatch.setattr(ctl_map_ui, "MidiLearnDialog", Fake)


def test_right_click_on_track_controls_maps_and_controller_moves_the_screen(win, app, monkeypatch):
    from ampsim.ui import ctl_map_ui
    page = win.pages["guitar"]
    assert {"guitar/delay/mix", "guitar/delay/on", "guitar/amp/gain", "guitar/track/volume", "guitar/track/on",
            "guitar/cab/model"} <= set(page.control_ids())
    assert all(MM.target_info(t) for t in page.control_ids())
    assert all(MM.target_info(t) for t in win.pages["vocal"].control_ids())
    knob = page.controls_by_id["guitar/delay/mix"]
    assert knob.property("ctrl_id") == "guitar/delay/mix"
    texts = [a.text() for a in ctl_map_ui.menu(win, "guitar/delay/mix", knob).actions()]
    assert texts[0] == "Guitarra › Delay › Mix" and any(t.startswith("Mapear controle físico") for t in texts)
    seen = []
    _fake_dialog(monkeypatch, ["cc", 0, 21], seen)
    assert ctl_map_ui.learn(win, "guitar/delay/mix", knob)
    assert seen[0]["kinds"] == ("cc",) and seen[0]["func"] == "Guitarra › Delay › Mix"
    assert win.inst.ctl_map["guitar/delay/mix"]["key"] == ["cc", 0, 21]
    assert knob.midi_tag == "CC21" and "CC 21" in knob.toolTip()
    texts = [a.text() for a in ctl_map_ui.menu(win, "guitar/delay/mix", knob).actions()]
    assert "Remover mapeamento (CC 21 · canal 1)" in texts
    # o controlador (thread do MIDI) mexe; a tela acompanha depois que a interface aplica
    win.inst.handle_midi(0xB0, 21, 127)
    app.processEvents()
    assert win.engine.tracks["guitar"].values["delay"]["mix"] == 100 and knob.value() == 100
    # liga/desliga pelo LED da aba Vocal (outra aba aberta: o mapeamento é global)
    _fake_dialog(monkeypatch, ["note", 0, 98])
    led = win.pages["vocal"].panel_by_key["reverb"].led
    assert ctl_map_ui.learn(win, "vocal/reverb/on", led)
    was = win.engine.tracks["vocal"].values["reverb"]["on"]
    win.inst.handle_midi(0x90, 98, 100)
    app.processEvents()
    assert win.engine.tracks["vocal"].values["reverb"]["on"] is (not was)
    # remover
    ctl_map_ui.unmap(win, "guitar/delay/mix")
    assert "guitar/delay/mix" not in win.inst.ctl_map and knob.midi_tag == ""


def test_learn_dialog_detects_latching_button_and_menu_switches(win, app, monkeypatch):
    from ampsim.ui import ctl_map_ui
    from ampsim.ui.midi_learn import MidiLearnDialog
    br = win.inst_bridge
    dlg = MidiLearnDialog(win.inst, br, "x", win, kinds=MM.KINDS, latch=False)
    br.monitor.emit("cc", 0, 64, 127)                  # momentâneo: 127 ao apertar e 0 ao soltar
    br.monitor.emit("cc", 0, 64, 0)
    assert dlg.latch_box.isVisible() is False or not dlg.latch_box.isChecked()
    dlg._accept()
    assert dlg.choice == ["cc", 0, 64] and dlg.latch is False
    dlg = MidiLearnDialog(win.inst, br, "x", win, kinds=MM.KINDS, latch=False)
    dlg.show()
    br.monitor.emit("cc", 0, 65, 127)                  # trava: só o 127, o 0 não vem ao soltar
    app.processEvents()
    assert dlg.latch_box.isVisible() and dlg.latch_box.isChecked()
    dlg._accept()
    assert dlg.latch is True
    dlg = MidiLearnDialog(win.inst, br, "x", win, kinds=MM.KINDS, latch=False)
    br.monitor.emit("note", 0, 60, 100)                # nota: sem a opção
    dlg._accept()
    assert dlg.latch is False
    # mapeado sem tipo (antigo): o botão direito oferece trocar
    ctl_map_ui.assign(win, "vocal/track/on", ["cc", 0, 66])
    m = ctl_map_ui.menu(win, "vocal/track/on", win)
    acts = {a.text(): a for a in m.actions()}
    a = acts[ctl_map_ui.LATCH_TEXT]
    assert a.isCheckable() and not a.isChecked()
    a.trigger()
    assert win.inst.ctl_map["vocal/track/on"]["latch"] is True
    m2 = ctl_map_ui.menu(win, "guitar/delay/mix", win)
    assert ctl_map_ui.LATCH_TEXT not in [x.text() for x in m2.actions()]
    # Pad/Piano: botão por CC também tem a opção
    pv = win.pad_view
    pv.assign_physical("button", 2, ["cc", 0, 70], latch=True)
    assert win.inst.button_latch[2] is True
    m3 = pv.context_menu("button", 2)
    texts = {x.text(): x for x in m3.actions()}
    assert texts[ctl_map_ui.LATCH_TEXT].isChecked()
    texts[ctl_map_ui.LATCH_TEXT].trigger()
    assert win.inst.button_latch[2] is False


def test_malformed_state_json_opens_the_window(app, tmp_path, monkeypatch, fake):
    """Abrir o AmpSim com mapping.knobs estragado no state.json (antes: TypeError em key_text)."""
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "app" / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "app" / "presets")
    monkeypatch.setattr(storage, "SHARE_DIR", tmp_path / "Documentos" / "AmpSim")
    (tmp_path / "app").mkdir()
    st = {"instruments": {"mapping": {"knobs": BAD_ITEMS[:8], "buttons": BAD_ITEMS[:8], "pads": BAD_ITEMS[4:12]},
                          "free_map": {"Reverb": "x"}, "ctl_map": {"guitar/delay/mix": 3},
                          "device_maps": {"X": {"mapping": {"knobs": 4}}}, "button_latch": None},
          "ui": {"dock_tab": 2}}
    (tmp_path / "app" / "state.json").write_text(json.dumps(st), encoding="utf-8")
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    try:
        w.show()
        app.processEvents()
        w.dock.refresh()
        assert w.inst.mapping["knobs"] == [None] * 8 and w.inst.free_map == {}
        assert "não mapeado" in w.dock.knob_combos[0].toolTip()
    finally:
        w.timer.stop()
        w.close()
        w.deleteLater()
        app.processEvents()


def test_conflict_asks_before_replacing(win, monkeypatch):
    from ampsim.ui import ctl_map_ui
    inst = win.inst
    inst.free_map["Reverb"] = ["cc", 0, 74]
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    assert not ctl_map_ui.assign(win, "bass/reverb/mix", ["cc", 0, 74])
    assert "Pad/Piano: Reverb" in asked[0] and "bass/reverb/mix" not in inst.ctl_map
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes))
    assert ctl_map_ui.assign(win, "bass/reverb/mix", ["cc", 0, 74])
    assert "Reverb" not in inst.free_map and inst.ctl_map["bass/reverb/mix"]["key"] == ["cc", 0, 74]
    # e entre abas: o mesmo CC em outro controle
    assert ctl_map_ui.assign(win, "guitar/reverb/mix", ["cc", 0, 74])
    assert "Baixo › Reverb › Mix" in asked[-1] and "bass/reverb/mix" not in inst.ctl_map
    # uma tecla do teclado: avisa que deixa de tocar
    assert ctl_map_ui.assign(win, "guitar/reverb/on", ["note", 0, 64])
    assert "não toca som" in asked[-1]
    # o Pad/Piano pegando um CC de uma aba também pergunta e tira de lá
    from ampsim.ui import pad_piano
    monkeypatch.setattr(pad_piano, "MidiLearnDialog", lambda *a, **k: type(
        "D", (), {"choice": ["cc", 0, 74], "exec": lambda self: True})())
    win.pad_view.learn("Shimmer")
    assert inst.free_map["Shimmer"] == ["cc", 0, 74] and "guitar/reverb/mix" not in inst.ctl_map


def test_midi_tab_lists_mappings_grouped_with_remove(win, app):
    from ampsim.ui import ctl_map_ui
    inst = win.inst
    inst.free_map["Reverb"] = ["cc", 0, 74]
    ctl_map_ui.assign(win, "guitar/delay/mix", ["cc", 0, 21])
    ctl_map_ui.assign(win, "vocal/track/mute", ["note", 9, 50])
    ctl_map_ui.assign(win, "bass/amp/gain", ["cc", 0, 22])
    inst.ctl_map["fx/master/1/param:Wet"] = MM.make_entry("fx/master/1/param:Wet", ["cc", 0, 23],
                                                          plugin="vst3:Sumiu.vst3")
    d = win.dock
    d.show_tab(2)
    d.show_midi_view(1)
    app.processEvents()
    t = d.map_tree
    groups = [t.topLevelItem(i).text(0) for i in range(t.topLevelItemCount())]
    assert groups == ["Pad/Piano", "Guitarra", "Baixo", "Vocal", "Plugins"]
    plug = t.topLevelItem(4).child(0)
    assert "plugin ausente" in plug.text(0)
    g = t.topLevelItem(1).child(0)
    assert g.text(0) == "Delay › Mix" and g.text(1) == "CC 21 c1"
    assert "(5)" in d.view_maps.text()
    t.setCurrentItem(g)
    d.remove_selected_map()
    assert "guitar/delay/mix" not in inst.ctl_map
    d.remove_map("free:Reverb")
    assert "Reverb" not in inst.free_map
    groups = [t.topLevelItem(i).text(0) for i in range(t.topLevelItemCount())]
    assert groups == ["Baixo", "Vocal", "Plugins"]


def test_fx_window_maps_mix_switch_and_plugin_parameters(win, app, fake, monkeypatch):
    from ampsim.ui import ctl_map_ui
    from ampsim.ui.plugin_slot import PluginSlotWidget
    path = fake("Room Reverb")
    chain = win.engine.tracks["vocal"].fx_chain
    chain.add(path, wait=True)
    chain.wait()
    dlg = win.open_fx("track", "vocal")
    app.processEvents()
    row = dlg.findChildren(PluginSlotWidget)[0]
    assert row.switch.property("ctrl_id") == "fx/vocal/1/on" and row.mix.property("ctrl_id") == "fx/vocal/1/mix"
    texts = [a.text() for a in ctl_map_ui.menu(win, "fx/vocal/1/mix", row.mix).actions()]
    assert texts[0] == "Plugins Vocal › 1. Room Reverb › Mix"
    assert row.params_btn.isEnabled()
    pd = ctl_map_ui.PluginParamsDialog(win, "vocal", 0, dlg)
    names = [pd.tree.topLevelItem(i).text(0) for i in range(pd.tree.topLevelItemCount())]
    assert names == ["Dry Level", "Wet Level", "Decay"]
    pd.tree.setCurrentItem(pd.tree.topLevelItem(2))
    _fake_dialog(monkeypatch, ["cc", 0, 60])
    pd.map_current()
    e = win.inst.ctl_map["fx/vocal/1/param:Decay"]
    assert e["plugin"] == vst.portable_ref(path) and e["param"] == "Decay"
    assert pd.tree.topLevelItem(2).text(2) == "CC 60 · canal 1"
    win.inst.handle_midi(0xB0, 60, 0)
    app.processEvents()
    chain.wait()
    assert fake.made[-1].param("Decay").raw_value == 0.0
    pd.close()
    # mapear sem plugin no lugar: avisa e não mapeia
    assert not ctl_map_ui.assign(win, "fx/vocal/3/mix", ["cc", 0, 61])
    chain.clear()
    chain.wait()


def test_preset_buttons_menu_and_controller_step(win, app, monkeypatch):
    from ampsim.ui import ctl_map_ui
    win.tabs.setCurrentIndex(1)                    # Baixo
    app.processEvents()
    texts = [a.text() for a in win.preset_button_menu("next").actions()]
    assert texts[0] == "Baixo › próximo preset"
    ctl_map_ui.assign(win, "bass/preset/next", ["cc", 0, 33])
    page = win.pages["bass"]
    i = page.preset.currentIndex()
    win.tabs.setCurrentIndex(0)                    # vale de qualquer aba
    app.processEvents()
    win.inst.handle_midi(0xB0, 33, 127)
    app.processEvents()
    assert page.preset.currentIndex() == (i + 1) % page.preset.count()
    win.tabs.setCurrentIndex(2)
    app.processEvents()
    texts = [a.text() for a in win.preset_button_menu("prev").actions()]
    assert texts[0] == "Pad/Piano › Timbre anterior"


# ------------------------------------------------------------------ pendências pequenas (QA rodada 7)
def test_no_room_warning_is_a_readable_balloon(win, app):
    msg = "Sem espaço para encaixar “Faders” aqui: feche ou estreite outra subjanela."
    win.notify(msg)
    app.processEvents()
    t = win._toast
    assert t.isVisible() and t.text() == msg and t.wordWrap()
    assert t.height() >= t.heightForWidth(t.width())                 # texto inteiro, sem cortar
    assert t.geometry().right() <= win.width() and t.geometry().left() >= 0


def test_failed_plugin_label_and_try_again(win, app, fake, tmp_path, monkeypatch):
    from ampsim.ui.plugin_slot import RETRY, PluginSlotWidget
    bad = fake("Quebrado")
    monkeypatch.setattr(vst, "_load_plugin", lambda p: (_ for _ in ()).throw(ImportError("scan failure")))
    chain = win.engine.tracks["guitar"].fx_chain
    slot = chain.add(bad, wait=True)
    chain.wait()
    assert vst.bad_info(bad) == (vst.NOT_A_PLUGIN, True)
    w = PluginSlotWidget(lambda: slot, "1.", chain_id="guitar", index=0)
    assert w.combo.itemText(w.combo.findData(bad)).endswith("(não abre)")
    # outra abertura do AmpSim: a marca diz que foi da última vez
    monkeypatch.setattr(vst, "_RUN", "outra")
    w.fill()
    assert w.combo.itemText(w.combo.findData(bad)).endswith("(não abriu da última vez)")
    w.combo.setCurrentIndex(w.combo.findData(RETRY))
    w.combo.activated.emit(w.combo.currentIndex())
    assert vst.bad_reason(bad) == "" and w.combo.findData(RETRY) < 0
    assert w.combo.itemText(w.combo.findData(bad)) == "Quebrado"
    chain.clear()
    chain.wait()


def test_full_chain_add_button_looks_disabled(win, app, fake):
    path = fake("Room Reverb")
    dlg = win.open_fx("track", "bass")
    for _ in range(4):
        dlg.add_btn.click()
    app.processEvents()
    assert not dlg.add_btn.isEnabled() and "4 de 4" in dlg.count_lab.text()
    assert ":disabled" in dlg.add_btn.styleSheet()
    img = dlg.add_btn.grab().toImage()
    c = img.pixelColor(img.width() // 2, 3)
    assert c.blue() < 120                                           # não fica azul "primário"
    win.engine.tracks["bass"].fx_chain.clear()
    assert path


def test_layer_fx_tag_bigger_without_growing_the_header(win, app):
    pv = win.pad_view
    b = pv.layer_buttons[0]
    fx = b.fx_button
    assert fx.size().toTuple() == (32, 19)
    assert fx.y() + fx.height() <= b.height() - 4


def test_vocal_gate_indicator_is_neutral_without_microphone(win, app):
    page = win.pages["vocal"]
    v = win.engine.tracks["vocal"]
    v.set_on("gate", True)
    win.tabs.setCurrentIndex(3)
    app.processEvents()
    v.set_switch("on", False)
    page.update_meters()
    assert page.gate_state.text() == ""
    v.set_switch("on", True)
    page.update_meters()                                              # ligado, mas sem áudio/sinal
    assert page.gate_state.text() == "sem sinal"
    from ampsim.ui.theme import C
    assert C["green"] not in page.gate_state.styleSheet()
    v.set_switch("on", False)
