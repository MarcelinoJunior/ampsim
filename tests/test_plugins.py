"""Plugins VST3 nas camadas do teclado (L1–L4), no Master e nas trilhas: slot estéreo, thread dos plugins,
erros que desligam só o slot, salvar/restaurar, presets compartilhados e a tela de downloads.

Os testes que usam o Dragonfly Reverb de verdade são pulados se ele não estiver instalado (tela
"Downloads: timbres e plugins"); os demais usam um plugin falso."""
import base64
import hashlib
import json
import os
import threading
import time
import zipfile

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ampsim.audio import packs, vst  # noqa: E402

FS = 48000.0
MB = 4096


@pytest.fixture(autouse=True)
def _app_dir(monkeypatch, tmp_path):
    """Nada vai para a pasta AmpSim de verdade (plugins escolhidos, plugins que não abrem)."""
    from ampsim import storage
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "appdir")
    vst.reset_caches()
    yield
    vst.reset_caches()


# ------------------------------------------------------------------ plugin falso
class FakePlugin:
    """Imita um pedalboard.VST3Plugin: ganho fixo por canal, estado em JSON, erros sob encomenda."""

    def __init__(self, path, channels=(2,), gain=0.5, instrument=False, fail=False, nan=False, slow=0.0,
                 load_delay=0.0):
        if load_delay:
            time.sleep(load_delay)
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.is_instrument = instrument
        self.is_effect = not instrument
        self.channels = channels
        self.gain = gain
        self.fail, self.nan, self.slow = fail, nan, slow
        self.calls = 0
        self.resets = 0
        self.threads = {"load": threading.current_thread().name}
        self.editor_event = None

    @property
    def raw_state(self):
        return json.dumps({"gain": self.gain}).encode()

    @raw_state.setter
    def raw_state(self, b):
        self.gain = json.loads(b.decode())["gain"]

    def process(self, x, fs, buffer_size=8192, reset=True):
        if x.shape[0] not in self.channels:
            raise RuntimeError(f"does not support {x.shape[0]}-channel output")
        if reset:
            self.threads["reset"] = threading.current_thread().name
        self.calls += 1
        if self.fail and self.calls > 3:
            raise RuntimeError("falha de teste")
        if self.slow:
            time.sleep(self.slow)
        y = np.array(x, dtype=np.float32) * self.gain
        if self.nan and self.calls > 3:
            y[:] = np.nan
        return y

    def reset(self):
        self.resets += 1
        self.threads["reset"] = threading.current_thread().name

    def show_editor(self, ev=None):
        self.threads["editor"] = threading.current_thread().name
        self.editor_event = ev
        ev.wait(5.0)


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    """Registra plugins falsos: fake(nome, **opções) -> caminho de um "pacote .vst3" de mentira."""
    made = {}
    specs = {}

    def load(path):
        p = FakePlugin(path, **specs[os.path.basename(path)])
        made.setdefault(os.path.basename(path), []).append(p)
        return p
    monkeypatch.setattr(vst, "_load_plugin", load)

    def add(name, folder=None, **opts):
        d = (folder or tmp_path) / f"{name}.vst3"
        (d / "Contents" / "x86_64-win").mkdir(parents=True, exist_ok=True)
        (d / "Contents" / "x86_64-win" / f"{name}.vst3").write_bytes(b"x")
        specs[d.name] = opts
        return str(d)
    add.made = made
    return add


def stereo_block(n=256, seed=0):
    rng = np.random.default_rng(seed)
    kb = np.zeros((MB, 2))
    kb[:n, 0] = rng.standard_normal(n) * 0.1
    kb[:n, 1] = rng.standard_normal(n) * 0.05          # lados diferentes: o slot não pode somar L+R
    return kb


def loaded_slot(path, on=True):
    s = vst.PluginSlot(FS, MB, "L1")
    s.load(path, wait=True)
    s.set_on(on, wait=True)
    return s


# ------------------------------------------------------------------ lista de plugins
def test_find_plugins_in_system_and_user_dirs(monkeypatch, tmp_path):
    sysd, user = tmp_path / "sys", tmp_path / "user"
    for d in (sysd / "B.vst3", user / "a.vst3", sysd / "Fabricante" / "C.vst3", user / "x.txt"):
        d.parent.mkdir(parents=True, exist_ok=True)
        d.mkdir() if d.suffix == ".vst3" else d.write_text("")
    monkeypatch.setattr(vst, "SYSTEM_VST3_DIR", str(sysd))
    monkeypatch.setenv("AMPSIM_USER_VST3_DIR", str(user))
    names = [vst.display_name(p) for p in vst.find_plugins()]
    assert names == ["a", "B", "C"]
    assert vst.user_vst3_dir() == str(user)


def test_trusted_plugin_outside_standard_dirs(monkeypatch, tmp_path, fake):
    from ampsim import sharing, storage
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(vst, "SYSTEM_VST3_DIR", str(tmp_path / "sys"))
    monkeypatch.setenv("AMPSIM_USER_VST3_DIR", str(tmp_path / "user"))
    p = fake("Meu", folder=tmp_path / "D")
    assert not vst.is_local(p) and not sharing._local_plugin(p)
    vst.trust_plugin(p)                                   # escolhido em "Procurar arquivo…"
    assert vst.is_local(p) and sharing._local_plugin(p)
    std = fake("Padrao", folder=tmp_path / "user")
    assert vst.is_local(std)
    assert not vst.is_local(str(tmp_path / "sumiu.vst3"))


# ------------------------------------------------------------------ slot estéreo
def test_stereo_slot_mix_and_on_off(fake):
    s = loaded_slot(fake("Ganho", gain=0.5))
    assert s.ok and s.inst.stereo and "estéreo" in s.status()
    kb = stereo_block()
    ref = kb.copy()
    s.set_mix(100)
    s.process(kb, 256)
    assert np.allclose(kb[:256], ref[:256] * 0.5, atol=1e-6)          # L e R separados (sem somar)
    assert np.allclose(kb[256:], 0.0)
    kb = ref.copy()
    s.set_mix(50)
    s.process(kb, 256)
    assert np.allclose(kb[:256], ref[:256] * 0.75, atol=1e-6)
    kb = ref.copy()
    s.set_mix(0)                                                        # mix 0 = sem efeito
    s.process(kb, 256)
    assert np.array_equal(kb, ref)
    s.set_mix(100)
    s.set_on(False)
    kb = ref.copy()
    s.process(kb, 256)
    assert np.array_equal(kb, ref) and "desligado" in s.status()
    s.set_on(True, wait=True)
    s.process(kb, 256)
    assert np.allclose(kb[:256], ref[:256] * 0.5, atol=1e-6)


def test_mono_only_plugin_runs_one_copy_per_side(fake):
    path = fake("Mono", channels=(1,), gain=2.0)
    s = loaded_slot(path)
    assert len(s.inst.plugins) == 2 and "mono" in s.status()
    kb = stereo_block()
    ref = kb.copy()
    s.process(kb, 256)
    assert np.allclose(kb[:256], ref[:256] * 2.0, atol=1e-6)             # cada lado no seu plugin
    a, b = fake.made["Mono.vst3"][-2:]
    assert a.calls == b.calls and a.calls > 0


def test_instrument_is_refused(fake):
    s = loaded_slot(fake("Synth", instrument=True))
    assert s.inst is None and "instrumento" in s.load_error and "VSTi" in s.status()
    kb = stereo_block()
    ref = kb.copy()
    s.process(kb, 256)
    assert np.array_equal(kb, ref)


def test_missing_plugin_keeps_config(tmp_path):
    s = vst.PluginSlot(FS, MB)
    s.apply(dict(path=str(tmp_path / "Sumiu.vst3"), state="AAAA", on=True, mix=40))
    assert s.missing and s.inst is None and "não encontrado" in s.status() and "Sumiu" in s.status()
    assert s.to_dict() == dict(path=str(tmp_path / "Sumiu.vst3"), state="AAAA", on=True, mix=40)
    kb = stereo_block()
    ref = kb.copy()
    s.process(kb, 256)
    assert np.array_equal(kb, ref)


def test_plugin_error_disables_only_that_slot(fake):
    bad = loaded_slot(fake("Quebra", fail=True))
    good = loaded_slot(fake("Bom", gain=0.5))
    for _ in range(6):
        kb = stereo_block()
        ref = kb.copy()
        bad.process(kb, 256)
        good.process(kb, 256)
    assert bad.run_error == "falha de teste" and "desligado após erro" in bad.status()
    assert not good.run_error
    assert np.allclose(kb[:256], ref[:256] * 0.5, atol=1e-6)            # o bom continua; o quebrado passa direto
    plug = bad.inst.plugins[0]
    plug.fail = False
    bad.set_on(True, wait=True)                                         # ligar de novo: reseta e volta
    assert not bad.run_error and plug.resets >= 1 and plug.threads["reset"] == "AmpSim-plugins"
    kb = stereo_block()
    ref = kb.copy()
    bad.process(kb, 256)
    assert np.allclose(kb[:256], ref[:256] * 0.5, atol=1e-6)


def test_nan_output_disables_slot(fake):
    s = loaded_slot(fake("NaN", nan=True))
    for _ in range(6):
        kb = stereo_block()
        s.process(kb, 256)
        assert np.isfinite(kb).all()
    assert "inválido" in s.run_error


def test_slow_plugin_is_switched_off(fake, monkeypatch):
    monkeypatch.setattr(vst, "SLOW_BLOCKS", 4)
    s = loaded_slot(fake("Lento", slow=0.008))           # 8 ms para um bloco de 5,3 ms
    for _ in range(6):
        s.process(stereo_block(), 256)
    assert "pesado demais" in s.run_error


def test_load_runs_on_plugin_thread_without_blocking(fake):
    path = fake("Demora", load_delay=0.4)
    s = vst.PluginSlot(FS, MB)
    s.on = True
    t0 = time.perf_counter()
    s.load(path)
    assert time.perf_counter() - t0 < 0.1                                 # a interface não espera
    assert s.loading and "Carregando" in s.status()
    kb = stereo_block()
    ref = kb.copy()
    s.process(kb, 256)                                                    # enquanto carrega: passa direto
    assert np.array_equal(kb, ref)
    assert s.wait(5.0) and s.ok
    p = s.inst.plugins[0]
    assert p.threads["load"] == "AmpSim-plugins" and p.threads["reset"] == "AmpSim-plugins"


def test_last_load_wins(fake):
    a, b = fake("A", load_delay=0.2), fake("B")
    s = vst.PluginSlot(FS, MB)
    s.load(a)
    s.load(b)
    s.wait(5.0)
    assert s.inst is not None and s.inst.path == b and s.name == "B"


def test_state_roundtrip(fake):
    path = fake("Estado", gain=0.5)
    s = loaded_slot(path)
    s.inst.plugins[0].gain = 0.25                                         # mexeu no painel do plugin
    s.set_mix(70)
    d = s.to_dict()
    assert d["path"] == path and d["on"] is True and d["mix"] == 70
    assert json.loads(base64.b64decode(d["state"]))["gain"] == 0.25
    s2 = vst.PluginSlot(FS, MB)
    s2.apply(json.loads(json.dumps(d)), wait=True)
    assert s2.ok and s2.inst.plugins[0].gain == 0.25 and s2.on and s2.mix == pytest.approx(0.7)
    n = len(fake.made["Estado.vst3"])
    s2.apply(d, wait=True)                                                # mesma config: não recarrega
    assert len(fake.made["Estado.vst3"]) == n


def test_clean_plugin_rejects_junk():
    c = vst.clean_plugin({"path": 3, "state": "não é base64!", "on": "sim", "mix": 1e9, "x": 1})
    assert c == dict(path="", state="", on=False, mix=100)
    c = vst.clean_plugin({"path": "C:\\a.vst3", "state": "AAAA", "on": True, "mix": -5})
    assert c == dict(path="C:\\a.vst3", state="AAAA", on=True, mix=0)
    assert vst.clean_plugin("lixo") == vst.EMPTY_PLUGIN


def test_editor_opens_on_plugin_thread_without_blocking(fake):
    s = loaded_slot(fake("Painel"))
    closed = []
    t0 = time.perf_counter()
    assert s.show_editor(on_closed=closed.append)
    assert time.perf_counter() - t0 < 0.1
    end = time.time() + 3
    while not s.editor_open and time.time() < end:
        time.sleep(0.01)
    plug = s.inst.plugins[0]
    assert s.editor_open and plug.threads["editor"] == "AmpSim-plugins"
    kb = stereo_block()
    s.process(kb, 256)                                                   # o áudio continua com o painel aberto
    assert not s.run_error
    other = fake("Outro")
    s2 = vst.PluginSlot(FS, MB)
    s2.load(other, wait=True)                                            # carregar outro fecha o painel antes
    assert s2.ok and closed == [""] and not s.editor_open
    assert not vst.PluginSlot(FS, MB).show_editor()                      # sem plugin: nada a abrir


def test_mono_plugin_editor_syncs_right_side(fake):
    s = loaded_slot(fake("MonoPainel", channels=(1,)))
    s.show_editor()
    end = time.time() + 3
    while not s.editor_open and time.time() < end:
        time.sleep(0.01)
    s.inst.plugins[0].gain = 3.0
    vst.host().close_editor()
    s.wait()
    assert s.inst.plugins[1].gain == 3.0


# ------------------------------------------------------------------ trilha (mono) e thread dos plugins
def test_track_vst_slot_loads_on_plugin_thread(fake):
    from ampsim.dsp.track import TrackDSP
    path = fake("Trilha", channels=(1, 2), gain=0.5)
    t = TrackDSP(FS)
    assert t.load_vst(path), t.vst_error
    assert t.vst.channels == 1 and t.vst.plugin.threads["load"] == "AmpSim-plugins"
    x = np.ones(MB)
    t.vst.process(x, 128, 1.0)
    assert np.allclose(x[:128], 0.5) and np.allclose(x[128:], 1.0)
    t.reset_dsp_state()
    assert t.vst.plugin.resets == 1 and t.vst.plugin.threads["reset"] == "AmpSim-plugins"
    assert t.load_vst(fake("VSTi", instrument=True)) is False and "instrumento" in t.vst_error


# ------------------------------------------------------------------ cadeia (vários plugins em série)
def test_chain_order_move_remove_and_restore(fake):
    a, b, c = fake("A", gain=0.5), fake("B", gain=0.25), fake("C", gain=2.0)
    ch = vst.PluginChain(FS, MB, "L1")
    for p in (a, b, c):
        ch.add(p, wait=True)
    assert [s.name for s in ch.slots] == ["A", "B", "C"] and ch.active
    calls = []
    for s in ch.slots:
        orig = s.inst.plugins[0].process

        def spy(x, fs, buffer_size=8192, reset=True, orig=orig, name=s.name):
            calls.append(name)
            return orig(x, fs, buffer_size, reset)
        s.inst.plugins[0].process = spy
    kb = stereo_block()
    ref = kb.copy()
    ch.process(kb, 256)
    assert calls == ["A", "B", "C"]                                     # em série, na ordem
    assert np.allclose(kb[:256], ref[:256] * 0.25, atol=1e-6)
    ch.move(2, -2)                                                      # C vai para o começo
    assert [s.name for s in ch.slots] == ["C", "A", "B"]
    calls.clear()
    ch.process(stereo_block(), 256)
    assert calls == ["C", "A", "B"]
    ch.remove(1)                                                        # tira o A
    assert [s.name for s in ch.slots] == ["C", "B"]
    ch.slots[1].set_mix(40)
    saved = json.loads(json.dumps(ch.to_list()))
    assert [vst.display_name(d["path"]) for d in saved] == ["C", "B"] and saved[1]["mix"] == 40
    other = vst.PluginChain(FS, MB, "L1")
    other.apply(saved, wait=True)
    assert [s.name for s in other.slots] == ["C", "B"] and other.slots[1].mix == pytest.approx(0.4)
    assert ch.add() is not None and ch.add() is not None and ch.add() is None      # no máximo 4
    assert len(ch.slots) == 4 and len(ch.to_list()) == 2                # slots vazios não são salvos
    ch.clear()
    assert ch.slots == () and not ch.active


def test_chain_accepts_old_single_slot_format(fake):
    a = fake("Velho", gain=0.5)
    assert vst.clean_chain({"path": a, "on": True, "mix": 70}) == [dict(path=a, state="", on=True, mix=70)]
    assert vst.clean_chain([{"path": ""}, "lixo", {"path": a}]) == [dict(path=a, state="", on=False, mix=100)]
    assert vst.clean_chain(None) == [] and vst.clean_chain("x") == []
    ch = vst.PluginChain(FS, MB)
    ch.apply({"path": a, "on": True, "mix": 70}, wait=True)
    assert len(ch.slots) == 1 and ch.slots[0].ok and ch.slots[0].mix == pytest.approx(0.7)


def test_trust_only_after_the_plugin_opens(fake, tmp_path):
    bad = fake("Synth", folder=tmp_path / "D", instrument=True)
    good = fake("Bom", folder=tmp_path / "D")
    s = vst.PluginSlot(FS, MB)
    s.load(bad, wait=True, trust=True)
    assert s.load_error and not vst.is_local(bad) and vst.trusted_plugins() == []
    s.load(good, wait=True, trust=True)
    assert s.ok and vst.is_local(good) and vst.trusted_plugins() == [good]


def test_not_a_plugin_message_and_remembered(fake, monkeypatch, tmp_path):
    d = tmp_path / "Lixo.vst3"
    d.mkdir()

    def broken(path):
        raise ImportError("VST3Plugin: Unable to scan plugin C:/x: unsupported plugin format or scan failure.")
    monkeypatch.setattr(vst, "_load_plugin", broken)
    s = vst.PluginSlot(FS, MB)
    s.load(str(d), wait=True)
    assert s.load_error == vst.NOT_A_PLUGIN and "scan failure" in s.load_detail
    assert s.status() == vst.NOT_A_PLUGIN and s.failed
    assert vst.bad_reason(str(d)) == vst.NOT_A_PLUGIN                   # a lista marca "(não abre)"
    vst.reset_caches()
    assert vst.bad_reason(str(d)) == vst.NOT_A_PLUGIN                   # lembrado em arquivo
    monkeypatch.setattr(vst, "_load_plugin", lambda p: FakePlugin(p))
    s.load(str(d), wait=True)                                           # agora abre: esquece a falha
    assert s.ok and vst.bad_reason(str(d)) == ""


def test_mix_back_from_zero_resets_the_plugin(fake):
    s = loaded_slot(fake("Cauda", gain=0.5))
    plug = s.inst.plugins[0]
    n0 = plug.resets
    s.set_mix(0)
    s.process(stereo_block(), 256)
    assert plug.resets == n0                                            # Mix 0: nem processa
    s.set_mix(30, wait=True)                                            # voltou: zera a cauda parada
    assert plug.resets == n0 + 1 and plug.threads["reset"] == "AmpSim-plugins" and s.active
    s.set_mix(60)
    assert plug.resets == n0 + 1                                        # 30 -> 60: sem reset


def test_state_read_on_plugin_thread_flushes_when_idle(fake):
    """Mexeu no painel com o áudio parado: salvar processa antes um bloco de silêncio (o estado do
    plugin só muda depois de um bloco), na thread dos plugins."""
    path = fake("Lento", gain=0.5)
    s = loaded_slot(path)
    plug = s.inst.plugins[0]
    flushed = []
    orig = plug.process

    def proc(x, fs, buffer_size=8192, reset=True):
        if not reset and x.shape[1] == 32:
            flushed.append(threading.current_thread().name)
        return orig(x, fs, buffer_size, reset)
    plug.process = proc
    s.to_dict()
    assert flushed == ["AmpSim-plugins"]
    s.process(stereo_block(), 256)                                      # o áudio está passando: não precisa
    s.to_dict()
    assert flushed == ["AmpSim-plugins"]


def test_portable_paths(monkeypatch, tmp_path, fake):
    user = tmp_path / "user"
    monkeypatch.setenv("AMPSIM_USER_VST3_DIR", str(user))
    monkeypatch.setattr(vst, "SYSTEM_VST3_DIR", str(tmp_path / "sys"))
    local = fake("Sala", folder=user)
    vendor = fake("Eq", folder=tmp_path / "sys" / "Fabricante")
    outside = fake("Fora", folder=tmp_path / "D")
    assert vst.portable_ref(local) == "vst3:Sala.vst3"
    assert vst.portable_ref(vendor) == "vst3:Fabricante/Eq.vst3"
    assert vst.portable_ref(outside) == outside                          # fora das pastas padrão: só local
    assert os.path.normcase(vst.resolve_ref("vst3:Sala.vst3")) == os.path.normcase(local)
    assert os.path.normcase(vst.resolve_ref("vst3:Fabricante/Eq.vst3")) == os.path.normcase(vendor)
    # preset antigo de outro PC, com o caminho completo da pasta do usuário de lá
    other = r"C:\Users\Fulano\AppData\Local\Programs\Common\VST3\Sala.vst3"
    assert os.path.normcase(vst.resolve_ref(other)) == os.path.normcase(local)
    assert vst.resolve_ref(r"C:\Program Files\Common Files\VST3\Fabricante\Eq.vst3").lower() == vendor.lower()
    assert vst.resolve_ref("vst3:Sumiu.vst3") == "vst3:Sumiu.vst3"       # não instalado aqui
    for evil in ("vst3:../x.vst3", "vst3:C:/Windows/x.vst3", "vst3:a/../../b.vst3"):
        assert vst.resolve_ref(evil) == evil and not vst.is_local(evil)
    s = vst.PluginSlot(FS, MB)
    s.apply({"path": "vst3:Sala.vst3", "on": True}, wait=True)
    assert s.ok and s.to_dict()["path"] == "vst3:Sala.vst3"
    s.apply({"path": "vst3:Sumiu.vst3", "on": True})
    assert s.missing and "Sumiu" in s.status() and s.to_dict()["path"] == "vst3:Sumiu.vst3"


# ------------------------------------------------------------------ motor, camadas e persistência
@pytest.fixture()
def engine():
    from ampsim.audio.engine import AudioEngine
    e = AudioEngine()
    e.tracks["pads"].set_param("track", "use_amp", False)          # teclas limpas (como na janela)
    yield e
    if e.instruments.sf is not None:
        e.instruments.sf.close()


def _play(e, note=60, blocks=60, tail=150):
    inst = e.instruments
    out = np.zeros((256, 2), np.float32)
    peak = 0.0
    inst.key_on(note, 110)
    for _ in range(blocks):
        e._render(None, out, 256)
        peak = max(peak, float(np.abs(out).max()))
    inst.key_off(note)
    for _ in range(tail):
        e._render(None, out, 256)
    assert np.isfinite(out).all()
    return peak


def _mute_chain(chain, fake, name):
    chain.clear()
    chain.add(fake(name, gain=0.0), wait=True)
    assert chain.active


def test_engine_master_chain_before_limiter(engine, fake):
    e = engine
    out = np.zeros((256, 2), np.float32)
    mc = e.master_chain
    s = mc.add(fake("DC", gain=0.0), wait=True)
    plug = s.inst.plugins[0]
    orig = plug.process

    def dc(x, fs, buffer_size=8192, reset=True):
        y = orig(x, fs, buffer_size, reset)
        y[:] = 3.0                                    # bem acima do teto: o limitador tem que segurar
        return y
    plug.process = dc
    for _ in range(40):
        e._render(None, out, 256)
    assert plug.calls >= 40 and 0.3 < np.abs(out).max() <= 1.0
    s.set_mix(0)
    for _ in range(40):
        e._render(None, out, 256)
    assert np.abs(out).max() < 0.05


needs_sf = pytest.mark.skipif(not __import__("ampsim.audio.soundfont", fromlist=["available"]).available(),
                              reason="timbres não baixados")


@needs_sf
def test_engine_layer_chains_process_each_layer(engine, fake):
    e, inst = engine, engine.instruments
    inst.set_ready("Piano de Concerto")
    inst.levels["shimmer"] = 0
    dry = _play(e)
    for k in range(4):
        _mute_chain(e.layer_chains[k], fake, f"Mudo{k}")
    muted = _play(e)
    assert dry > 0.01 and muted < dry * 0.1
    assert all(c.slots[0].inst.plugins[0].calls > 0 for c in e.layer_chains)


@needs_sf
def test_synth_timbre_layer_goes_through_its_chain(engine, fake):
    """QA: plugin da camada era ignorado nos timbres "Synth AmpSim"."""
    e, inst = engine, engine.instruments
    inst.set_ready("Baixo Pulsante (BPM)")
    assert inst.synth_layer_index() == 0
    inst.levels["shimmer"] = 0
    dry = _play(e, 40)
    _mute_chain(e.layer_chains[0], fake, "MudoSynth")
    muted = _play(e, 40)
    assert dry > 0.01 and muted < dry * 0.1
    assert e.layer_chains[0].slots[0].inst.plugins[0].calls > 0


@needs_sf
def test_layer_chain_with_amp_on_goes_before_the_amp(engine, fake):
    """QA: com "Amp e efeitos" das teclas ligado o plugin da camada era ignorado; agora entra antes do amp."""
    e, inst = engine, engine.instruments
    e.tracks["pads"].set_param("track", "use_amp", True)
    inst.set_ready("Piano de Concerto")
    inst.levels["shimmer"] = 0
    dry = _play(e)
    _mute_chain(e.layer_chains[0], fake, "MudoAmp")
    _mute_chain(e.layer_chains[1], fake, "MudoAmp2")               # o timbre tem duas camadas
    muted = _play(e)
    assert dry > 0.01 and muted < dry * 0.1
    e.layer_chains[0].clear()
    e.layer_chains[1].clear()
    again = _play(e)
    assert again > dry * 0.3                                           # sem plugin: o caminho de sempre


def test_guitar_and_bass_chains_process(engine, fake):
    e = engine
    for name in ("guitar", "bass"):
        t = e.tracks[name]
        t.set_on("reverb", False)
        src = np.zeros((256, 2), np.float32)
        src[:, 0] = 0.2
        mix = np.zeros((4096, 2))
        e._run_track(t, src, 0, 256, mix)
        dry = float(np.abs(mix[:256]).max())
        ch = t.fx_chain
        s = ch.add(fake(f"Trilha{name}", gain=0.0), wait=True)
        mix[:] = 0.0
        e._run_track(t, src, 0, 256, mix)
        assert dry > 0.0 and float(np.abs(mix[:256]).max()) < dry * 1e-3, name
        assert s.inst.plugins[0].calls > 0
        st = t.get_state()
        assert [vst.display_name(d["path"]) for d in st["fx_chain"]] == [f"Trilha{name}"]
        from ampsim.dsp.track import TrackDSP
        t2 = TrackDSP(FS)
        t2.load_state(json.loads(json.dumps(st)))
        t2.fx_chain.wait()
        assert [s.name for s in t2.fx_chain.slots] == [f"Trilha{name}"]
        old = dict(st, fx_chain=None)
        old.pop("fx_chain")
        t2.load_state(old)                                             # preset antigo: trilha sem plugins
        assert t2.fx_chain.slots == ()


def test_instruments_state_presets_and_layers(engine, fake):
    from ampsim import sharing
    e, inst = engine, engine.instruments
    pa, pb, pm = fake("Room", gain=0.5), fake("Hall", gain=0.25), fake("Master", gain=0.9)
    inst.layer_chain(1).apply([dict(path=pa, on=True, mix=80), dict(path=pb, on=False)], wait=True)
    inst.layer_chain(2).apply([dict(path=pb, on=False, mix=100)], wait=True)
    e.master_chain.apply([dict(path=pm, on=True, mix=50)], wait=True)
    st = inst.get_state()
    assert [[d["path"] for d in c] for c in st["layer_chains"]] == [[pa, pb], [pb], [], []]
    assert st["layer_chains"][0][0]["mix"] == 80 and st["layer_chains"][0][0]["state"]
    assert st["master_chain"][0]["path"] == pm
    snd = sharing.sound_state(st)
    assert "layer_chains" in snd and "master_chain" not in snd          # Master: só a sessão
    json.dumps(st)
    for c in e.layer_chains + [e.master_chain]:
        c.clear()
    inst.load_state(json.loads(json.dumps(st)))
    for c in e.layer_chains + [e.master_chain]:
        c.wait()
    l1 = inst.layer_chain(1)
    assert [s.name for s in l1.slots] == ["Room", "Hall"] and l1.slots[0].on and l1.slots[0].mix == 0.8
    assert not l1.slots[1].on and inst.layer_chain(2).slots[0].name == "Hall"
    assert e.master_chain.slots[0].ok and e.master_chain.slots[0].mix == 0.5
    # formato de 1 plugin por camada (fase anterior)
    for c in e.layer_chains + [e.master_chain]:
        c.clear()
    inst.load_state({"layer_plugins": [dict(path=pa, on=True, mix=60), dict(path="")],
                     "master_plugin": dict(path=pm, on=True)})
    for c in e.layer_chains + [e.master_chain]:
        c.wait()
    assert [s.name for s in inst.layer_chain(1).slots] == ["Room"] and inst.layer_chain(2).slots == ()
    assert e.master_chain.slots[0].name == "Master"
    # timbre pronto: tira os plugins das camadas (fazem parte do timbre), os do Master ficam
    inst.set_ready("Piano de Concerto")
    assert all(not c.slots for c in e.layer_chains) and e.master_chain.slots


def test_add_and_remove_layer_move_chains(engine, fake):
    inst = engine.instruments
    inst.set_ready("Piano de Concerto")
    assert inst.add_layer() == 3 and inst.add_layer() == 4
    p3, p4 = fake("P3"), fake("P4")
    inst.layer_chain(3).add(p3, wait=True)
    inst.layer_chain(4).add(p4, wait=True)
    inst.remove_layer(3)                                                  # a camada 4 vira 3, com os plugins
    assert inst.layer_chain(3).slots[0].path == p4 and inst.layer_chain(3).label == "L3"
    assert inst.layer_chain(4).slots == () and len(engine.layer_chains) == 4
    assert inst.add_layer() == 4 and inst.layer_chain(4).slots == ()


def test_shared_preset_rule(engine, fake, monkeypatch, tmp_path):
    from ampsim import sharing
    monkeypatch.setattr(vst, "SYSTEM_VST3_DIR", str(tmp_path / "sys"))
    monkeypatch.setenv("AMPSIM_USER_VST3_DIR", str(tmp_path / "user"))
    local = fake("Local", folder=tmp_path / "user")
    inst = engine.instruments
    long_state = base64.b64encode(os.urandom(3000)).decode()                # bem mais que 200 letras
    st = {"keys": dict(inst.keys), "layer_chains": [
        [{"path": local, "state": long_state, "on": True, "mix": 60},
         {"path": r"C:\Users\outro\malware.vst3", "state": "AAAA", "on": True, "mix": 100}],
        "lixo", [{"path": r"C:\Users\outro\AppData\Local\Programs\Common\VST3\Local.vst3", "on": True}]],
        "master_chain": [{"path": local, "on": True}]}
    out = sharing.sanitize_instruments(st, inst.get_state())
    lc = out["layer_chains"]
    assert len(lc) == 4 and lc[0] == [dict(path="vst3:Local.vst3", state=long_state, on=True, mix=60)]
    assert lc[1] == [] and lc[3] == []
    assert lc[2] == [dict(path="vst3:Local.vst3", state="", on=True, mix=100)]   # mesmo plugin baixado aqui
    assert "master_chain" not in out                                        # preset nunca mexe no Master
    assert sharing.sanitize_instruments({"keys": dict(inst.keys)}, inst.get_state())["layer_chains"] == []
    old = sharing.sanitize_instruments({"layer_plugins": [{"path": local, "on": True}]}, inst.get_state())
    assert old["layer_chains"][0] == [dict(path="vst3:Local.vst3", state="", on=True, mix=100)]
    tr = sharing.sanitize_track({"values": {"vst": {"path": local, "state": long_state, "on": True}},
                                 "fx_chain": [{"path": local, "on": True}, {"path": r"C:\x\y.vst3"}]})
    assert tr["values"]["vst"]["path"] == "vst3:Local.vst3" and tr["values"]["vst"]["state"] == long_state
    assert tr["fx_chain"] == [dict(path="vst3:Local.vst3", state="", on=True, mix=100)]
    inst.load_state(out)
    inst.layer_chain(1).wait()
    assert inst.layer_chain(1).slots[0].ok and os.path.normcase(inst.layer_chain(1).slots[0].path) == \
        os.path.normcase(local)


def test_web_remote_state_ignores_plugins(engine, fake):
    """A tela remota não controla plugin, mas o estado com plugins não pode quebrá-la."""
    from ampsim import sharing
    inst = engine.instruments
    inst.layer_chain(1).add(fake("Web"), wait=True)
    doc = sharing.make_doc("preset", sharing.sound_state(inst.get_state()), "x", trilha="teclas")
    back = sharing.from_text(sharing.to_text(doc))
    assert back["dados"]["layer_chains"][0][0]["path"]


def test_qt_dialog_texts_in_portuguese():
    from ampsim.ui.i18n import load_translator
    tr = load_translator()
    assert tr is not None
    for en, pt in (("Close", "Fechar"), ("Cancel", "Cancelar"), ("&Yes", "&Sim"), ("&No", "&Não"),
                   ("Restore Defaults", "Restaurar padrões")):
        assert tr.translate("QPlatformTheme", en) == pt


def test_download_without_internet_message(monkeypatch, tmp_path):
    import urllib.error
    import urllib.request
    monkeypatch.setenv("AMPSIM_PACKS_DIR", str(tmp_path / "timbres"))
    monkeypatch.setenv("AMPSIM_USER_VST3_DIR", str(tmp_path / "VST3"))

    def offline(*a, **k):
        raise urllib.error.URLError("getaddrinfo failed")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(packs.PackError) as err:
        packs.install_plugin_pack(packs.PLUGIN_PACKS[0])
    assert str(err.value) == packs.NET_ERROR and "internet" in str(err.value)
    assert not list((tmp_path / "VST3").iterdir())


# ------------------------------------------------------------------ downloads (pacote de plugins)
def fake_plugin_zip(tmp_path, bundles):
    path = tmp_path / "plugins.zip"
    with zipfile.ZipFile(path, "w") as z:
        for b in bundles:
            z.writestr(f"pacote-1.0/{b}/Contents/x86_64-win/{b}", b"MZ" + os.urandom(100))
            z.writestr(f"pacote-1.0/{b}/Contents/Resources/x.txt", b"ok")
        z.writestr("pacote-1.0/Plugin.clap", b"clap")
        z.writestr("pacote-1.0/Plugin-vst.dll", b"vst2")
        z.writestr("pacote-1.0/Plugin.lv2/manifest.ttl", b"lv2")
        z.writestr(f"pacote-1.0/{bundles[0]}/../../fora.txt", b"x")
    data = path.read_bytes()
    return path, hashlib.sha256(data).hexdigest(), len(data)


@pytest.fixture()
def vdirs(monkeypatch, tmp_path):
    monkeypatch.setenv("AMPSIM_PACKS_DIR", str(tmp_path / "timbres"))
    monkeypatch.setenv("AMPSIM_USER_VST3_DIR", str(tmp_path / "VST3"))
    monkeypatch.setattr(vst, "SYSTEM_VST3_DIR", str(tmp_path / "sys"))
    return tmp_path / "VST3"


def test_plugin_pack_install_and_remove(vdirs, tmp_path):
    bundles = ("Um.vst3", "Dois.vst3")
    src, sha, size = fake_plugin_zip(tmp_path, bundles)
    p = packs.PluginPack("teste", "Teste", "", "GPL-3.0 · Alguém", 1, 1, "https://exemplo/p.zip", sha, size, bundles)
    assert not packs.plugin_installed(p) and not packs.plugin_removable(p)
    paths = packs.install_plugin_pack(p, source=src)
    assert [x.name for x in paths] == list(bundles) and packs.plugin_installed(p)
    found = sorted(os.listdir(vdirs))
    assert found == ["Dois.vst3", "Um.vst3"]                               # nada de CLAP/LV2/VST2/temporário
    assert not (tmp_path / "fora.txt").exists() and not (vdirs.parent / "fora.txt").exists()
    assert (vdirs / "Um.vst3" / "Contents" / "Resources" / "x.txt").exists()
    assert sorted(vst.display_name(x) for x in vst.find_plugins()) == ["Dois", "Um"]
    packs.install_plugin_pack(p, source=src)                               # reinstalar por cima
    packs.remove_plugin_pack(p)
    assert not packs.plugin_installed(p) and os.listdir(vdirs) == []


def test_plugin_pack_checks_size_and_sha(vdirs, tmp_path):
    bundles = ("Um.vst3",)
    src, sha, size = fake_plugin_zip(tmp_path, bundles)
    for bad_sha, bad_size in ((sha, size + 1), ("0" * 64, size)):
        p = packs.PluginPack("teste", "Teste", "", "", 1, 1, "https://exemplo/p.zip", bad_sha, bad_size, bundles)
        with pytest.raises(packs.PackError):
            packs.install_plugin_pack(p, source=src)
        assert not packs.plugin_installed(p)
    p = packs.PluginPack("teste", "Teste", "", "", 1, 1, "u", sha, size, ("Um.vst3", "Falta.vst3"))
    with pytest.raises(packs.PackError, match="Falta"):
        packs.install_plugin_pack(p, source=src)
    assert not (vdirs / "Um.vst3").exists() and [x for x in os.listdir(vdirs) if x.startswith(".")] == []


def test_dragonfly_catalog_entry():
    p = packs.PLUGIN_PACK_BY_ID["dragonfly-reverb"]
    assert p.url.startswith("https://github.com/michaelwillis/dragonfly-reverb/releases/download/3.2.10/")
    assert len(p.sha256) == 64 and p.tamanho == 22447365 and "GPL-3.0" in p.licenca
    assert "DragonflyRoomReverb.vst3" in p.bundles and "DragonflyPlateReverb.vst3" in p.bundles
    credits = open(os.path.join(os.path.dirname(__file__), "..", "CREDITS.md"), encoding="utf-8").read()
    assert "Dragonfly Reverb" in credits and "GPL-3.0" in credits


def test_downloads_dialog_lists_plugins(vdirs, tmp_path):
    from PySide6.QtWidgets import QApplication, QWidget
    from ampsim.ui.packs_dialog import TITLE, PacksDialog
    app = QApplication.instance() or QApplication([])
    bundles = ("Um.vst3",)
    src, sha, size = fake_plugin_zip(tmp_path, bundles)
    fakepack = packs.PluginPack("dragonfly-reverb", "Plugin Teste", "desc", "GPL-3.0 · Alguém", 1, 1, "u",
                                sha, size, bundles)

    class Win(QWidget):
        refreshed = 0

        class engine:  # noqa: N801
            class instruments:  # noqa: N801
                sf = None

        def refresh_sounds(self):
            pass

        def refresh_plugins(self):
            Win.refreshed += 1
    import ampsim.audio.packs as P
    old = P.PLUGIN_PACKS, dict(P.PLUGIN_PACK_BY_ID)
    P.PLUGIN_PACKS = (fakepack,)
    P.PLUGIN_PACK_BY_ID["dragonfly-reverb"] = fakepack
    try:
        w = Win()
        dlg = PacksDialog(w)
        assert dlg.windowTitle() == TITLE == "Downloads: timbres e plugins"
        status, bar, btn = dlg.rows["dragonfly-reverb"]
        assert btn.text() == "Baixar" and "Não instalado" in status.text()
        dlg.download(fakepack, source=src, wait=True)
        app.processEvents()
        assert btn.text() == "Remover" and "Instalado" in status.text() and Win.refreshed == 1
        dlg.reject()
    finally:
        P.PLUGIN_PACKS = old[0]
        P.PLUGIN_PACK_BY_ID.clear()
        P.PLUGIN_PACK_BY_ID.update(old[1])


# ------------------------------------------------------------------ Dragonfly Reverb de verdade
DRAGONFLY = packs.PLUGIN_PACK_BY_ID["dragonfly-reverb"]
_DF = {p.name: str(p) for p in packs.plugin_paths(DRAGONFLY)}
needs_df = pytest.mark.skipif(not (vst.available() and "DragonflyRoomReverb.vst3" in _DF
                                   and "DragonflyPlateReverb.vst3" in _DF),
                              reason="Dragonfly Reverb não instalado (tela Downloads: timbres e plugins)")


def impulse_response(slot, blocks=60, n=256):
    """Um clique no começo e silêncio depois: devolve a saída [blocos*n, 2]."""
    out = []
    for b in range(blocks):
        kb = np.zeros((MB, 2))
        if b == 0:
            kb[0, 0] = 1.0
            kb[3, 1] = 0.5
        slot.process(kb, n)
        out.append(kb[:n].copy())
    return np.concatenate(out)


@needs_df
def test_dragonfly_room_reverb_tail_mix_on_off():
    s = loaded_slot(_DF["DragonflyRoomReverb.vst3"])
    assert s.ok and s.inst.stereo and s.name == "Dragonfly Room Reverb"
    s.set_mix(100)
    y = impulse_response(s)
    tail = y[int(0.1 * FS):]                                               # depois de 100 ms
    assert np.isfinite(y).all() and np.sqrt(np.mean(tail ** 2)) > 1e-4      # cauda de reverb
    assert np.abs(y[:, 0] - y[:, 1]).max() > 1e-3                           # estéreo de verdade
    s.set_mix(0)
    y0 = impulse_response(s)
    assert y0[0, 0] == 1.0 and np.abs(y0[1:]).max() <= 0.5 and np.abs(y0[int(0.1 * FS):]).max() == 0.0
    s.set_mix(100)
    s.set_on(False)
    yoff = impulse_response(s)
    assert np.abs(yoff[int(0.1 * FS):]).max() == 0.0
    s.set_on(True, wait=True)
    yon = impulse_response(s)
    assert np.sqrt(np.mean(yon[int(0.1 * FS):] ** 2)) > 1e-4
    assert not s.run_error


@needs_df
def test_dragonfly_state_roundtrip():
    s = loaded_slot(_DF["DragonflyPlateReverb.vst3"])
    plug = s.inst.plugins[0]
    plug.decay_s = 6.0
    impulse_response(s, blocks=2)          # o pedalboard só passa o parâmetro ao plugin no próximo bloco
    d = s.to_dict()
    s2 = vst.PluginSlot(FS, MB)
    s2.apply(d, wait=True)
    assert s2.ok and s2.inst.plugins[0].decay_s == pytest.approx(plug.decay_s, abs=0.05)
    assert s2.inst.plugins[0].decay_s > 5.0


@needs_df
def test_dragonfly_on_l1_and_master_in_engine(engine):
    e, inst = engine, engine.instruments
    from ampsim.audio.soundfont import available
    l1, mc = e.layer_chains[0], e.master_chain
    mc.apply([dict(path=_DF["DragonflyPlateReverb.vst3"], on=True, mix=50)], wait=True)
    out = np.zeros((256, 2), np.float32)
    if available() and inst.sf is not None:
        inst.set_ready("Piano de Concerto")
    l1.apply([dict(path=_DF["DragonflyRoomReverb.vst3"], on=True, mix=100),
              dict(path=_DF["DragonflyHallReverb.vst3"], on=True, mix=30)], wait=True)
    assert all(s.ok for s in l1.slots + mc.slots)
    if inst.sf is not None:
        inst.key_on(60, 110)
    peak = 0.0
    for b in range(200):
        if b == 30 and inst.sf is not None:
            inst.key_off(60)
        e._render(None, out, 256)
        peak = max(peak, float(np.abs(out).max()))
        assert np.isfinite(out).all()
    assert not any(s.run_error for s in l1.slots + mc.slots)
    if inst.sf is not None:
        assert peak > 0.01
    st = inst.get_state()
    assert st["layer_chains"][0][0]["path"] == "vst3:DragonflyRoomReverb.vst3" or \
        st["layer_chains"][0][0]["path"].endswith("DragonflyRoomReverb.vst3")
    assert st["layer_chains"][0][1]["state"] and st["master_chain"][0]["state"]


@needs_df
def test_dragonfly_panel_edit_saved_without_audio():
    """QA: com o áudio parado, mexer no plugin e salvar perdia a mudança (o Dragonfly só atualiza o
    estado depois de processar um bloco)."""
    s = loaded_slot(_DF["DragonflyPlateReverb.vst3"])
    s.set_on(False)                                       # nem o áudio passaria por ele
    plug = s.inst.plugins[0]
    plug.decay_s = 7.0
    d = s.to_dict()                                       # sem nenhum bloco de áudio
    s2 = vst.PluginSlot(FS, MB)
    s2.apply(d, wait=True)
    assert s2.inst.plugins[0].decay_s == pytest.approx(plug.decay_s, abs=0.05) and plug.decay_s > 6.0


@needs_df
def test_dragonfly_swaps_do_not_leak():
    """QA: a memória crescia a cada troca de plugin (ciclo de referências segurando o plugin)."""
    import gc
    import weakref
    s = vst.PluginSlot(FS, MB)
    paths = [_DF["DragonflyRoomReverb.vst3"], _DF["DragonflyHallReverb.vst3"]]
    refs = []
    gc.disable()
    try:
        for i in range(12):
            if s.inst is not None:
                refs.append(weakref.ref(s.inst))
            s.load(paths[i % 2], wait=True)
        vst.host().call(lambda: vst.host()._sweep(force=True))
        alive = [r for r in refs if r() is not None]
        assert alive == []                                # destruídos sem precisar do coletor de lixo
        gc.set_debug(gc.DEBUG_SAVEALL)
        gc.collect()
        stuck = [o for o in gc.garbage if type(o).__name__ in ("VST3Plugin", "AudioProcessorParameter")]
        assert stuck == []                                # nenhum plugin preso em ciclo esperando o coletor
    finally:
        gc.set_debug(0)
        gc.garbage.clear()
        gc.enable()


@needs_df
def test_dragonfly_on_guitar_track_slot():
    from ampsim.dsp.track import TrackDSP
    t = TrackDSP(FS)
    assert t.load_vst(_DF["DragonflyRoomReverb.vst3"]), t.vst_error
    t.set_on("vst", True)
    x = np.zeros(MB)
    x[0] = 1.0
    t.vst.process(x, 256, 1.0)
    tail = []
    for _ in range(30):
        x[:] = 0.0
        t.vst.process(x, 256, 1.0)
        tail.append(x[:256].copy())
    assert t.vst.error is None and np.sqrt(np.mean(np.concatenate(tail) ** 2)) > 1e-5
    state = t.get_state()
    assert state["values"]["vst"]["state"]
    t.reset_dsp_state()
    assert t.vst.error is None


# ------------------------------------------------------------------ controles do slot (widget)
def test_bundle_of():
    p = os.path.join("C:\\", "VST3", "Room.vst3", "Contents", "x86_64-win", "Room.vst3")
    assert vst.bundle_of(p) == os.path.join("C:\\", "VST3", "Room.vst3")
    assert vst.bundle_of(r"C:\VST3\Room.vst3") == r"C:\VST3\Room.vst3"


def test_plugin_slot_widget(fake, vdirs, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from ampsim.ui.plugin_slot import BROWSE, NONE, PluginSlotWidget
    app = QApplication.instance() or QApplication([])
    good = fake("Bom", folder=vdirs, gain=0.5)
    synth = fake("Synth", folder=vdirs, instrument=True)
    slot = vst.PluginSlot(FS, MB, "L1")
    opened = []
    w = PluginSlotWidget(lambda: slot, "1.", on_downloads=lambda: opened.append(1))
    datas = [w.combo.itemData(i) for i in range(w.combo.count())]
    assert datas[0] == NONE and good in datas and synth in datas and BROWSE in datas
    assert "Escolha" in w.status.text() and not w.editor_btn.isEnabled()
    w.combo.setCurrentIndex(w.combo.findData(good))
    w.combo.activated.emit(w.combo.currentIndex())
    slot.wait()
    app.processEvents()
    w.refresh()
    assert slot.ok and slot.on and w.switch.isChecked() and w.editor_btn.isEnabled()
    assert "Bom" in w.status.text() and "estéreo" in w.status.text()
    w.mix.setValue(40)
    assert slot.mix == pytest.approx(0.4)
    w.switch.click()
    assert not slot.on
    # VSTi: aviso visível e a chave fica desligada e inativa
    w.combo.setCurrentIndex(w.combo.findData(synth))
    w.combo.activated.emit(w.combo.currentIndex())
    slot.wait()
    w.refresh()
    assert "instrumento" in w.status.text() and C_RED in w.status.styleSheet()
    assert not w.switch.isChecked() and not w.switch.isEnabled()
    w.fill()
    assert "(não abre)" in w.combo.itemText(w.combo.findData(synth))
    # plugin que sumiu do disco
    slot.apply(dict(path=str(tmp_path / "Sumiu.vst3"), on=True))
    w.refresh()
    assert "não encontrado" in w.status.text() and "não encontrado" in w.combo.currentText()
    assert not w.switch.isChecked()
    # downloads
    w.combo.setCurrentIndex(w.combo.findData("\x00downloads"))
    w.combo.activated.emit(w.combo.currentIndex())
    assert opened == [1]


def test_fx_chain_window_and_button(fake, vdirs):
    from PySide6.QtWidgets import QApplication
    from ampsim.ui.plugin_slot import FxButton, FxChainWindow, FxLine
    app = QApplication.instance() or QApplication([])
    a, b = fake("Primeiro", folder=vdirs), fake("Segundo", folder=vdirs, instrument=True)
    chain = vst.PluginChain(FS, MB, "L1")
    opened = []
    btn = FxButton(lambda: chain, lambda: opened.append(1))
    line = FxLine(lambda: chain, lambda: opened.append(2))
    assert btn.state == "off" and "Nenhum plugin" in line.summary.toolTip()
    win = FxChainWindow(lambda: chain, "Plugins — Layer 1", note_fn=lambda: "")
    assert win.windowTitle() == "Plugins — Layer 1" and not win.isModal() and win.rows == []
    win.add_btn.click()
    assert len(chain.slots) == 1 and len(win.rows) == 1
    r = win.rows[0]
    r.combo.setCurrentIndex(r.combo.findData(a))
    r.combo.activated.emit(r.combo.currentIndex())
    chain.wait()
    app.processEvents()
    btn.sync()
    line.sync()
    assert chain.slots[0].ok and btn.state == "on" and C_GREEN in btn.styleSheet()
    assert "Primeiro" in line.summary.toolTip()
    win.add_btn.click()
    r2 = win.rows[1]
    r2.combo.setCurrentIndex(r2.combo.findData(b))
    r2.combo.activated.emit(r2.combo.currentIndex())
    chain.wait()
    app.processEvents()
    btn.sync()
    assert btn.state == "err" and C_RED in btn.styleSheet()
    up = [x for x in win.rows[1].findChildren(type(win.add_btn)) if x.objectName() == "fx_up"][0]
    up.click()                                                        # sobe o segundo
    assert [s.name for s in chain.slots] == ["Segundo", "Primeiro"]
    rm = [x for x in win.rows[0].findChildren(type(win.add_btn)) if x.objectName() == "fx_close"][0]
    rm.click()
    app.processEvents()
    assert [s.name for s in chain.slots] == ["Primeiro"] and len(win.rows) == 1
    for _ in range(3):
        win.add_btn.click()
    assert len(chain.slots) == 4 and not win.add_btn.isEnabled() and "4 de 4" in win.count_lab.text()
    btn.click()
    line.button.click()
    assert opened == [1, 2]
    win.close()


C_RED = "#e5394a"
C_GREEN = "#2fd67b"
