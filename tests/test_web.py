"""Tela remota (ampsim/web): configuração e senhas, página servida, login, permissões por tela,
cada comando da página fazendo a mesma coisa que na tela do PC, estado só do que mudou e latência."""
import json
import os
import re
import time
import urllib.request

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from ampsim import storage  # noqa: E402
from ampsim.web import config as wcfg  # noqa: E402
from ampsim.web.server import COMMAND_PANEL, STATIC  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from ampsim.ui.theme import STYLE
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "app" / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "app" / "presets")
    monkeypatch.setattr(storage, "SHARE_DIR", tmp_path / "Documentos" / "AmpSim")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    return tmp_path


@pytest.fixture()
def win(app, dirs):
    from ampsim.audio.engine import AudioEngine
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    w.resize(1536, 800)
    w.show()
    app.processEvents()
    yield w
    w.remote.stop()
    w.timer.stop()
    w.close()
    w.deleteLater()
    app.processEvents()


def serve(win, **cfg):
    """Liga a tela remota em 127.0.0.1 numa porta livre."""
    c = wcfg.default()
    c.update(cfg, ligado=True)
    win.remote.cfg = c
    assert win.remote.start(host="127.0.0.1", port=0), win.remote.server.error
    return win.remote.server.port


def wait(app, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


class Page:
    """Faz o papel do navegador do celular."""

    def __init__(self, port):
        self.ws = connect(f"ws://127.0.0.1:{port}/ws", open_timeout=5).__enter__()
        self.state = {}

    def recv(self, timeout=3.0):
        m = json.loads(self.ws.recv(timeout=timeout))
        if m["t"] == "estado":
            self.state.update(m["telas"])
        return m

    def until(self, t, timeout=3.0):
        """Espera a mensagem `t`, processando a interface (comandos rodam na thread dela)."""
        end = time.monotonic() + timeout
        while True:
            QApplication.processEvents()
            try:
                m = self.recv(0.02)
            except TimeoutError:
                if time.monotonic() > end:
                    raise
                continue
            if m["t"] == t:
                return m

    def send(self, **msg):
        self.ws.send(json.dumps(msg))

    def cmd(self, c, **kw):
        self.send(t="cmd", c=c, **kw)

    def close(self):
        self.ws.close()


def drain(app, page, secs=0.3):
    """Processa a interface e lê tudo que chegou (o estado novo)."""
    end = time.monotonic() + secs
    while time.monotonic() < end:
        app.processEvents()
        try:
            page.recv(0.02)
        except TimeoutError:
            pass


# ------------------------------------------------------------------ configuração
def test_users_passwords_are_hashed_and_checked(dirs):
    cfg = wcfg.default()
    wcfg.set_user(cfg, "Baterista", "1234", ["pads", "baixo", "xyz"])
    assert cfg["usuarios"][0]["telas"] == ["pads", "baixo"]
    assert "1234" not in json.dumps(cfg)
    assert wcfg.check(cfg, "baterista", "1234") == ["pads", "baixo"]
    assert wcfg.check(cfg, "baterista", "errada") is None
    assert wcfg.check(cfg, "ninguem", "1234") is None
    wcfg.set_user(cfg, "Baterista", "", ["pads"])            # senha vazia mantém a atual
    assert wcfg.check(cfg, "Baterista", "1234") == ["pads"]
    with pytest.raises(ValueError):
        wcfg.set_user(cfg, "Novo", "", ["pads"])
    wcfg.save(cfg)
    assert wcfg.load() == cfg
    wcfg.remove_user(cfg, "BATERISTA")
    assert cfg["usuarios"] == []


def test_config_file_with_junk_falls_back(dirs):
    wcfg.path().parent.mkdir(parents=True, exist_ok=True)
    wcfg.path().write_text('{"ligado": 1, "porta": 80, "aberto": ["pads", "?"], "usuarios": [{"nome": 3}]}',
                           encoding="utf-8")
    c = wcfg.load()
    assert c["ligado"] is True and c["porta"] == wcfg.DEFAULT_PORT
    assert c["aberto"] == ["pads"] and c["usuarios"] == []
    wcfg.path().write_text("isto não é json", encoding="utf-8")
    assert wcfg.load() == wcfg.default()


def _write_old_config(cfg):
    """webserver.json de uma versão antiga (sem "versao"): é o que dispara a migração das telas."""
    d = {k: v for k, v in cfg.items() if k != "versao"}
    wcfg.path().parent.mkdir(parents=True, exist_ok=True)
    wcfg.path().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_old_config_with_removed_panels_still_loads(dirs):
    """Tempo e Mute saíram da página: configurações antigas carregam sem eles (o resto continua)."""
    assert {"guitarra", "baixo"} <= set(wcfg.default()["aberto"])
    assert "tempo" not in wcfg.PANEL_IDS and "emergencia" not in wcfg.PANEL_IDS
    old = wcfg.default()
    wcfg.set_user(old, "mesa", "1234", ["faders"])
    old["usuarios"][0]["telas"] = ["tempo", "emergencia", "faders"]
    old["aberto"] = ["pads", "tempo", "emergencia", "timbre"]
    _write_old_config(old)
    c = wcfg.load()
    assert c["aberto"] == ["pads", "timbre"]
    assert c["usuarios"][0]["telas"] == ["faders"]
    assert wcfg.check(c, "mesa", "1234") == ["faders"]
    # quem via todas as telas antigas (sem senha ou "espelho") passa a ver também Guitarra e Baixo
    old["aberto"] = ["pads", "faders", "setlist", "tempo", "emergencia", "timbre"]
    old["usuarios"][0]["telas"] = list(old["aberto"])
    _write_old_config(old)
    c = wcfg.load()
    assert c["aberto"] == list(wcfg.PANEL_IDS) and c["usuarios"][0]["telas"] == list(wcfg.PANEL_IDS)
    assert json.loads(wcfg.path().read_text(encoding="utf-8"))["versao"] == wcfg.VERSION    # migrou 1 vez


def test_page_only_sends_known_commands():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    used = set(re.findall(r'\b(?:cmd|tc)\("(\w+)"', js))
    assert used and used <= set(COMMAND_PANEL), used - set(COMMAND_PANEL)
    assert {"trilha_volume", "efeito_on", "efeito_param", "trilha_salvar", "timbre_salvar"} <= used
    for gone in ("tap", "click", "bpm", "mute_geral", "panico"):         # telas Tempo e Mute saíram
        assert gone not in COMMAND_PANEL
    assert set(re.findall(r"^  (\w+)\(sec\)", js, re.M)) == set(wcfg.PANEL_IDS)
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert "http" not in html.replace('lang="pt-BR"', "")                 # nada de CDN: funciona sem internet


# ------------------------------------------------------------------ servidor
def test_serves_page_and_files(win):
    port = serve(win)
    base = f"http://127.0.0.1:{port}"
    r = urllib.request.urlopen(base + "/", timeout=5)
    assert r.status == 200 and "text/html" in r.headers["Content-Type"]
    assert b"AmpSim Remoto" in r.read()
    for f, kind in (("/app.js", "javascript"), ("/app.css", "css"), ("/icone.svg", "svg")):
        r = urllib.request.urlopen(base + f, timeout=5)
        assert kind in r.headers["Content-Type"] and r.read()
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/../ampsim/storage.py", timeout=5)
    assert e.value.code == 404
    assert win.remote.server.urls()


def test_other_sites_cannot_connect(win):
    port = serve(win)
    ok = connect(f"ws://127.0.0.1:{port}/ws", origin=f"http://127.0.0.1:{port}", open_timeout=5)
    ok.close()
    from websockets.exceptions import InvalidStatus
    with pytest.raises(InvalidStatus):
        connect(f"ws://127.0.0.1:{port}/ws", origin="http://site-qualquer.com", open_timeout=5)


def test_port_in_use_gives_clear_error(win):
    port = serve(win)
    from ampsim.web.server import WebServer
    other = WebServer(lambda *a: None, dict)
    c = wcfg.default()
    c["porta"] = port
    assert not other.start(c, host="127.0.0.1")
    assert "em uso" in other.error


def test_open_mode_sees_only_open_panels(win, app):
    port = serve(win, aberto=["pads", "baixo"])
    p = Page(port)
    m = p.until("auth")
    assert m["ok"] and m["telas"] == ["pads", "baixo"] and not m["login"]
    p.until("estado")
    assert {k.split(".")[0] for k in p.state} == {"pads", "baixo"}
    assert "baixo.presets" in p.state and "guitarra" not in p.state
    assert "pads.sons" in p.state and "timbre.sons" not in p.state      # catálogo só de tela liberada
    assert len(p.state["pads"]["tons"]) == 12 and len(p.state["pads"]["bateria"]) == 8
    # sem permissão: o fader não muda
    before = win.inst.fx["drive"]
    p.cmd("fader", id="Drive", valor=90)
    drain(app, p)
    assert win.inst.fx["drive"] == before
    p.close()


def test_login_token_and_wrong_password(win, app):
    cfg = wcfg.default()
    wcfg.set_user(cfg, "mesa", "segredo", ["faders", "guitarra"])
    port = serve(win, login=True, usuarios=cfg["usuarios"])
    p = Page(port)
    assert p.recv()["t"] == "precisa_login"
    p.cmd("trilha_on", trilha="guitar", on=False)       # antes de entrar: ignorado
    p.send(t="login", nome="mesa", senha="errada")
    m = p.until("auth")
    assert not m["ok"] and "errad" in m["erro"]
    assert win.engine.tracks["guitar"].values["track"]["on"]
    p.send(t="login", nome="Mesa", senha="segredo")
    m = p.until("auth")
    assert m["ok"] and m["telas"] == ["faders", "guitarra"] and m["token"]
    p.until("estado")
    assert {k.split(".")[0] for k in p.state} == {"faders", "guitarra"}
    p.close()
    # o celular volta (recarregou a página): o token basta
    q = Page(port)
    assert q.recv()["t"] == "precisa_login"
    q.send(t="token", token=m["token"])
    assert q.until("auth")["ok"]
    q.send(t="token", token="inventado")
    assert not q.until("auth")["ok"]
    q.close()


def test_changing_users_kicks_connected_pages(win, app):
    cfg = wcfg.default()
    wcfg.set_user(cfg, "a", "1234", ["pads"])
    port = serve(win, login=True, usuarios=cfg["usuarios"])
    p = Page(port)
    p.recv()
    p.send(t="login", nome="a", senha="1234")
    assert p.until("auth")["ok"]
    new = json.loads(json.dumps(win.remote.cfg))
    new["usuarios"][0]["telas"] = ["baixo"]
    win.remote.set_config(new, host="127.0.0.1")
    assert p.until("precisa_login")["t"] == "precisa_login"
    p.close()


# ------------------------------------------------------------------ comandos = mesmas ações da tela
def test_commands_do_what_the_screen_does(win, app):
    port = serve(win)
    inst = win.engine.instruments
    hits = []
    orig = inst.pad_hit
    inst.pad_hit = lambda i, v=110: hits.append((i, v))
    p = Page(port)
    p.until("auth")
    p.until("estado")

    p.cmd("pad", i=3, vel=100)
    assert wait(app, lambda: hits == [(3, 100)])
    p.cmd("pad", i=99)                                    # pad que não existe
    p.cmd("pad_cont", tom="D")
    assert wait(app, lambda: inst.cont_key == "D")
    drain(app, p)
    assert p.state["pads"]["tom"] == "D"
    p.cmd("pad_timbre", nome="Pad Órgão")
    assert wait(app, lambda: inst.cont_sound == "Pad Órgão")
    p.cmd("pad_parar")
    assert wait(app, lambda: inst.cont_key in (None, ""))

    # fader e mute iguais aos da barra inferior
    p.cmd("fader", id="Delay (mix)", valor=50)
    slider = [s for s in win.dock.strips if s[0] == ("func", "Delay (mix)")][0][1]
    assert wait(app, lambda: slider.value() == 50)
    assert win.inst.fx["delay_mix"] == 50
    drain(app, p)
    ch = {c["id"]: c for c in p.state["faders"]["canais"]}
    assert ch["Delay (mix)"]["valor"] == 50 and ch["Delay (mix)"]["nome"] == "Delay"
    assert "guitar" not in ch and "Volume do metrônomo" not in ch            # Click saiu, Master entrou
    ids = [c["id"] for c in p.state["faders"]["canais"]]
    assert ids[-2:] == ["Master", "Compressor"]                             # Compressor logo depois do Master
    mutable = next(c["id"] for c in p.state["faders"]["canais"] if c["pode_mutar"])
    p.cmd("mute", id=mutable, on=True)
    assert wait(app, lambda: mutable in inst.mutes)
    drain(app, p)
    assert {c["id"]: c for c in p.state["faders"]["canais"]}[mutable]["mudo"]
    p.cmd("mute", id=mutable, on=False)
    assert wait(app, lambda: mutable not in inst.mutes)
    p.cmd("fader", id="nao-existe", valor=10)

    # telas Tempo e Mute saíram da página: os comandos delas não fazem mais nada
    bpm = inst.bpm
    for c, kw in (("bpm", {"valor": 97}), ("click", {"on": True}), ("tap", {}), ("mute_geral", {"on": True}),
                  ("panico", {})):
        p.cmd(c, **kw)
    drain(app, p)
    assert inst.bpm == bpm and not win.engine.metronome.on and not win.engine.muted
    assert "tempo" not in p.state and "emergencia" not in p.state

    # preset do Pad/Piano muda sem trocar a aba do PC
    win.tabs.setCurrentIndex(0)
    before = win.pad_view.title.text()
    p.cmd("preset_passo", d=1)
    assert wait(app, lambda: win.pad_view.title.text() != before)
    assert win.tabs.currentIndex() == 0
    drain(app, p)
    assert p.state["timbre"]["preset"] == win.pad_view.title.text()

    # comando estranho não derruba nada
    p.send(t="cmd", c="trilha_volume", trilha="guitar", valor="abc")
    p.send(t="cmd", c="efeito_param", trilha="guitar", efeito="delay", param="mix", valor=float("nan"))
    p.send(t="cmd", c=["lista"], trilha={"x": 1})
    p.ws.send("{lixo")
    p.send(t="ping", id=1)
    assert p.until("pong")["id"] == 1
    inst.pad_hit = orig
    p.close()


def test_setlist_from_the_phone(win, app):
    port = serve(win)
    sl = win.setlist
    win.inst.start_cont_pad("E")
    sl.add_song("Primeira")
    win.inst.start_cont_pad("G")
    sl.add_song("Segunda")
    p = Page(port)
    p.until("auth")
    drain(app, p)
    songs = p.state["setlist"]["musicas"]
    assert [s["nome"] for s in songs] == ["Primeira", "Segunda"]
    p.cmd("musica", i=0)
    assert wait(app, lambda: sl.current == 0)
    p.cmd("musica_passo", d=1)
    assert wait(app, lambda: sl.current == 1)
    drain(app, p)
    assert p.state["setlist"]["tocando"] == 1
    sl.new_list("Domingo")
    drain(app, p)
    assert "Domingo" in p.state["setlist"]["listas"]
    p.cmd("setlist", nome=p.state["setlist"]["listas"][0])
    assert wait(app, lambda: sl.data["atual"] == p.state["setlist"]["listas"][0])
    p.close()


def test_only_changes_are_sent(win, app):
    port = serve(win)
    p = Page(port)
    p.until("auth")
    p.until("estado")
    drain(app, p)
    # nada mudou: nada chega mesmo com a tela empurrando o estado
    for _ in range(5):
        win.remote.push()
    app.processEvents()
    with pytest.raises(TimeoutError):
        while p.recv(0.3)["t"] == "vu":          # medidor (mensagem própria, 1x/s mesmo parado) não conta
            pass
    win.engine.tracks["guitar"].set_param("track", "volume", -12.0)
    win.remote.push()
    m = p.until("estado")
    assert set(m["telas"]) == {"guitarra"}
    p.close()


def test_two_devices_at_once(win, app):
    port = serve(win)
    a, b = Page(port), Page(port)
    a.until("auth")
    b.until("auth")
    assert wait(app, lambda: len(win.remote.server.connected()) == 2)
    drain(app, b)
    a.cmd("trilha_volume", trilha="bass", valor=25)
    assert wait(app, lambda: abs(win.engine.tracks["bass"].values["track"]["volume"] - (-42.0)) < 1e-6)
    drain(app, b)
    assert b.state["baixo"]["volume"] == 25
    a.close()
    b.close()


def test_latency_on_the_network_path(win, app):
    """Ida e volta pelo servidor (sem a rede Wi-Fi): tem que ser bem abaixo de 1 bloco de áudio."""
    port = serve(win)
    p = Page(port)
    p.until("auth")
    times = []
    for i in range(50):
        t0 = time.perf_counter()
        p.send(t="ping", id=i)
        p.until("pong")
        times.append(time.perf_counter() - t0)
    times.sort()
    assert times[len(times) // 2] < 0.005, times[len(times) // 2]
    # e o pad toca direto da thread do servidor (não espera a interface)
    hits = []
    win.engine.instruments.pad_hit = lambda i, v=110: hits.append(time.perf_counter())
    t0 = time.perf_counter()
    p.cmd("pad", i=0, vel=110)
    end = time.monotonic() + 2
    while not hits and time.monotonic() < end:
        time.sleep(0.0005)                                 # sem processEvents: a interface está "ocupada"
    assert hits and hits[0] - t0 < 0.01
    p.close()


# ------------------------------------------------------------------ janela Webserver
def test_webserver_dialog(win, app, monkeypatch):
    from ampsim.ui.webserver_dialog import WebServerDialog
    import socket
    s = socket.socket()
    s.bind(("0.0.0.0", 0))
    free = s.getsockname()[1]
    s.close()
    d = WebServerDialog(win.remote, win)
    d.show()
    app.processEvents()
    assert not d.link.isVisibleTo(d)
    d.port.setValue(free)
    d.on.setChecked(True)
    app.processEvents()
    assert win.remote.server.running and win.remote.server.port == free
    assert d.link.isVisibleTo(d) and f":{free}" in d.current_url()
    assert d.qr.pixmap() is not None and not d.qr.pixmap().isNull()
    assert wcfg.load()["ligado"] is True
    # login com usuário
    d.login_mode.setChecked(True)
    app.processEvents()
    assert win.remote.cfg["login"] and "usuário" in d.warn.text()
    d.save_user("baterista", "1234", ["pads", "guitarra"])
    assert d.users.count() == 1 and "Pads" in d.users.item(0).text() and "Guitarra" in d.users.item(0).text()
    assert wcfg.check(wcfg.load(), "baterista", "1234") == ["pads", "guitarra"]
    assert set(d.open_checks) == set(wcfg.PANEL_IDS)
    with pytest.raises(ValueError):
        d.save_user("Baterista", "9999", ["pads"])
    d.save_user("batera", "", ["pads"], old_name="baterista")
    assert wcfg.check(wcfg.load(), "batera", "1234") == ["pads"]
    # sem senha: telas marcadas
    d.open_mode.setChecked(True)
    d.open_checks["faders"].setChecked(False)
    app.processEvents()
    assert "faders" not in wcfg.load()["aberto"] and not wcfg.load()["login"]
    d.users.setCurrentRow(0)
    d.remove_user()
    assert wcfg.load()["usuarios"] == []
    d.on.setChecked(False)
    app.processEvents()
    assert not win.remote.server.running and not wcfg.load()["ligado"]
    d.close()
    win._update_web_btn()
    assert win.topbar.web_btn.text().strip() == "Webserver"


def test_webserver_button_shows_connected(win, app):
    port = serve(win)
    p = Page(port)
    p.until("auth")
    assert wait(app, lambda: (win._update_web_btn(), "1 aparelho" in win.topbar.web_btn.toolTip())[1])
    p.close()
    assert wait(app, lambda: (win._update_web_btn(), "0 aparelho" in win.topbar.web_btn.toolTip())[1])


def test_starts_with_the_app_when_left_on(app, dirs, monkeypatch):
    import socket
    s = socket.socket()
    s.bind(("0.0.0.0", 0))
    free = s.getsockname()[1]
    s.close()
    c = wcfg.default()
    c.update(ligado=True, porta=free)
    wcfg.save(c)
    from ampsim.audio.engine import AudioEngine
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    try:
        assert w.remote.server.running and w.remote.server.port == free
    finally:
        w.timer.stop()
        w.close()
        assert not w.remote.server.running
        w.deleteLater()
        app.processEvents()


# ------------------------------------------------------------------ configurar pelo aparelho
def test_choose_layer_sounds_from_the_phone(win, app):
    port = serve(win)
    inst = win.inst
    p = Page(port)
    p.until("auth")
    drain(app, p)
    cats = p.state["timbre.sons"]
    assert any(s["nome"] == "Rhodes" for c in cats for s in c["sons"])
    p.cmd("timbre_camada", camada=1, nome="Rhodes")
    assert wait(app, lambda: inst.keys["sound1"] == "Rhodes")
    inst.keys["layer2_on"] = False
    p.cmd("timbre_camada", camada=2, nome="Cordas Lentas")      # escolher a L2 liga a L2
    assert wait(app, lambda: inst.keys["sound2"] == "Cordas Lentas" and inst.keys["layer2_on"])
    n = inst.layer_count()
    p.cmd("timbre_camada", camada=n + 1, nome="Coral")         # "+ L3": camada nova
    assert wait(app, lambda: inst.layer_count() == n + 1)
    assert inst.layer_sounds()[-1][1] == "Coral"
    p.cmd("timbre_camada", camada=n + 1, nome="Sinos")
    assert wait(app, lambda: inst.layer_sounds()[-1][1] == "Sinos")
    before = inst.layer_sounds()
    p.cmd("timbre_camada", camada=1, nome="Não existe")
    p.cmd("timbre_camada", camada=9, nome="Rhodes")
    drain(app, p)
    assert inst.layer_sounds() == before
    assert [x["som"] for x in p.state["timbre"]["lista"]] == [s for _, s, _ in before]
    p.close()


def test_choose_pad_sound_from_the_phone(win, app):
    port = serve(win)
    inst = win.inst
    p = Page(port)
    p.until("auth")
    drain(app, p)
    names = [s["nome"] for c in p.state["pads.sons"] for s in c["sons"]]
    assert "Chimbal Aberto (synth)" in names
    p.cmd("pad_som", i=2, nome="Chimbal Aberto (synth)")
    assert wait(app, lambda: inst.pad_sounds[2] == "Chimbal Aberto (synth)")
    drain(app, p)
    assert p.state["pads"]["bateria"][2]["som"] == "Chimbal Aberto (synth)"
    p.cmd("pad_som", i=2, nome="rec:não existe")
    p.cmd("pad_som", i=40, nome="Chimbal Aberto (synth)")
    drain(app, p)
    assert inst.pad_sounds[2] == "Chimbal Aberto (synth)"
    p.close()


def test_recorder_from_the_phone(win, app, monkeypatch):
    port = serve(win)
    e = win.engine
    p = Page(port)
    p.until("auth")
    p.cmd("rec")                                          # áudio desligado: avisa só o celular
    assert "desligado" in p.until("aviso")["texto"]
    assert not e.recorder.active
    # com áudio: grava, para e guarda no banco
    monkeypatch.setattr(type(e), "running", property(lambda self: True))
    p.cmd("rec")
    assert wait(app, lambda: e.recorder.active)
    drain(app, p)
    assert p.state["pads.gravador"]["gravando"]
    import numpy as np
    e.recorder.feed(np.full((4800, 2), 0.3, np.float32))
    p.cmd("rec_parar")
    assert "Gravado" in p.until("aviso")["texto"]
    assert not e.recorder.active
    drain(app, p, 2.5)                                    # o banco relê a pasta
    recs = p.state["pads.gravador"]["gravacoes"]
    assert len(recs) == 1
    played = []
    monkeypatch.setattr(e.sampler, "trigger", lambda name, vel=110: played.append(name))
    p.cmd("rec_ouvir", nome=recs[0])
    assert wait(app, lambda: played == [recs[0]])
    stopped = []
    monkeypatch.setattr(e.sampler, "stop_all", lambda: stopped.append(1))
    p.cmd("rec_parar")                                    # STOP sem gravar: para o que toca
    assert wait(app, lambda: stopped == [1])
    p.close()


def test_pad_volumes_on_the_pads_screen(win, app):
    """Quem só vê a aba Pads ajusta o volume do pad contínuo e dos pads (e só esses dois)."""
    port = serve(win, aberto=["pads"])
    inst = win.inst
    p = Page(port)
    p.until("auth")
    drain(app, p)
    assert [v["id"] for v in p.state["pads.volumes"]] == ["Volume pad contínuo", "Volume bateria"]
    p.cmd("pad_volume", id="Volume pad contínuo", valor=33)
    assert wait(app, lambda: inst.levels["pad"] == 33)
    p.cmd("pad_mute", id="Volume bateria", on=True)
    assert wait(app, lambda: "Volume bateria" in inst.mutes)
    drain(app, p)
    assert {v["id"]: v["mudo"] for v in p.state["pads.volumes"]}["Volume bateria"]
    before = inst.fx["drive"]
    p.cmd("pad_volume", id="Drive", valor=90)              # outros faders: só pela aba Faders
    p.cmd("fader", id="Drive", valor=90)
    drain(app, p)
    assert inst.fx["drive"] == before
    p.close()


# ------------------------------------------------------------------ telas Guitarra e Baixo
def factory_names(name):
    from ampsim.presets import FACTORY
    return list(FACTORY[name])


def _fx_panel(page, key):
    return next(p for p in page.panels if p.eff.key == key)


def test_track_commands_need_the_right_panel():
    from ampsim.web.server import command_panel
    assert command_panel({"c": "efeito_on", "trilha": "guitar"}) == "guitarra"
    assert command_panel({"c": "trilha_salvar", "trilha": "bass"}) == "baixo"
    assert command_panel({"c": "trilha_volume", "trilha": "pads"}) is None       # teclas: não por aqui
    assert command_panel({"c": "trilha_volume"}) is None
    assert command_panel({"c": "trilha_volume", "trilha": ["guitar"]}) is None
    assert command_panel({"c": ["pad"]}) is None
    assert command_panel({"c": "timbre_salvar"}) == "timbre"
    assert command_panel({"c": "pad", "trilha": "guitar"}) == "pads"


def test_guitar_screen_volume_pedals_and_params(win, app):
    import copy
    from ampsim.dsp.params import AMP_MODELS, CAB_IR_INDEX
    from ampsim.web.remote import REMOTE_EFFECTS
    port = serve(win)
    g = win.engine.tracks["guitar"]
    page = win.track_pages["guitar"]
    win.tabs.setCurrentWidget(win.pad_view)               # o PC está na aba Pad/Piano
    pc_tab = win.tabs.currentIndex()
    p = Page(port)
    p.until("auth")
    drain(app, p)
    st = p.state["guitarra"]
    assert [f["k"] for f in st["efeitos"]] == [e.key for e in REMOTE_EFFECTS]
    assert not {"nam", "vst"} & {f["k"] for f in st["efeitos"]}          # dependem de arquivos do PC
    assert st["preset"] == page.preset.currentText() and st["on"]
    names = [s["nome"] for c in p.state["guitarra.presets"] for s in c["sons"]]
    assert names == ["factory:" + n for n in factory_names("guitar")]
    assert "baixo" in p.state and p.state["baixo"]["efeitos"]

    # volume da trilha (0..100 = -60..+12 dB, como os faders das trilhas) e liga/desliga
    p.cmd("trilha_volume", trilha="guitar", valor=50)
    assert wait(app, lambda: abs(g.values["track"]["volume"] - (-24.0)) < 1e-6)
    p.cmd("trilha_volume", trilha="guitar", valor=500)
    assert wait(app, lambda: g.values["track"]["volume"] == 12.0)
    p.cmd("trilha_on", trilha="guitar", on=False)
    assert wait(app, lambda: not g.values["track"]["on"])
    drain(app, p)
    assert not p.state["guitarra"]["on"] and p.state["guitarra"]["volume"] == 100
    p.cmd("trilha_on", trilha="guitar", on=True)
    assert wait(app, lambda: g.values["track"]["on"])

    # pedais: liga/desliga e parâmetros (linear, logarítmico, escolha)
    was = g.values["delay"]["on"]
    p.cmd("efeito_on", trilha="guitar", efeito="delay", on=not was)
    assert wait(app, lambda: g.values["delay"]["on"] == (not was))
    p.cmd("efeito_param", trilha="guitar", efeito="delay", param="mix", valor=40)
    assert wait(app, lambda: g.values["delay"]["mix"] == 40.0)
    p.cmd("efeito_param", trilha="guitar", efeito="delay", param="time", valor=50)    # 20..2000 ms em log
    assert wait(app, lambda: abs(g.values["delay"]["time"] - 200.0) < 1e-6)
    p.cmd("efeito_param", trilha="guitar", efeito="delay", param="time", valor=-30)
    assert wait(app, lambda: g.values["delay"]["time"] == 20.0)
    p.cmd("efeito_param", trilha="guitar", efeito="amp", param="model", valor=2)
    assert wait(app, lambda: g.values["amp"]["model"] == 2.0)
    p.cmd("efeito_param", trilha="guitar", efeito="amp", param="model", valor=99)
    assert wait(app, lambda: g.values["amp"]["model"] == len(AMP_MODELS) - 1)
    p.cmd("efeito_param", trilha="guitar", efeito="cab", param="model", valor=CAB_IR_INDEX)
    assert wait(app, lambda: g.values["cab"]["model"] == CAB_IR_INDEX - 1)     # IR só escolhendo o .wav no PC
    drain(app, p)
    fx = {f["k"]: f for f in p.state["guitarra"]["efeitos"]}
    delay = {x["k"]: x for x in fx["delay"]["params"]}
    assert fx["delay"]["on"] == (not was)
    assert delay["mix"]["valor"] == 40 and delay["time"]["valor"] == 0 and delay["time"]["txt"] == "20.0 ms"
    assert delay["ping"]["opcoes"] == ["Não", "Sim"]
    cab = {x["k"]: x for x in fx["cab"]["params"]}
    assert len(cab["model"]["opcoes"]) == CAB_IR_INDEX and cab["model"]["i"] == CAB_IR_INDEX - 1

    # o que não existe (ou não é do celular) é ignorado
    before = copy.deepcopy(g.values)
    pads_before = copy.deepcopy(win.engine.tracks["pads"].values)
    for kw in ({"efeito": "nam", "param": "input", "valor": 100}, {"efeito": "vst", "param": "mix", "valor": 0},
               {"efeito": "delay", "param": "nao", "valor": 3}, {"efeito": "xyz", "param": "mix", "valor": 3},
               {"efeito": "track", "param": "volume", "valor": 3}):
        p.cmd("efeito_param", trilha="guitar", **kw)
    p.cmd("efeito_on", trilha="guitar", efeito="vst", on=True)
    p.cmd("efeito_on", trilha="guitar", efeito="track", on=False)
    p.cmd("trilha_volume", trilha="pads", valor=0)
    p.cmd("efeito_on", trilha="teclas", efeito="delay", on=True)
    drain(app, p)
    assert g.values == before and win.engine.tracks["pads"].values == pads_before
    assert win.tabs.currentIndex() == pc_tab                      # nada disso trocou a aba do PC

    # com a aba da guitarra aberta no PC, o knob acompanha o celular
    win.tabs.setCurrentWidget(page)
    p.cmd("efeito_param", trilha="guitar", efeito="delay", param="mix", valor=70)
    assert wait(app, lambda: _fx_panel(page, "delay").controls["mix"].value() == 70.0)
    p.cmd("efeito_on", trilha="guitar", efeito="chorus", on=True)
    assert wait(app, lambda: _fx_panel(page, "chorus").led.isChecked())
    p.close()


def test_guitar_presets_from_the_phone_keep_the_pc_tab(win, app):
    from ampsim.presets import FACTORY
    port = serve(win)
    page = win.track_pages["guitar"]
    g = win.engine.tracks["guitar"]
    win.tabs.setCurrentWidget(win.pad_view)
    pc_tab = win.tabs.currentIndex()
    p = Page(port)
    p.until("auth")
    drain(app, p)
    first = page.preset.currentIndex()
    p.cmd("trilha_preset_passo", trilha="guitar", d=1)
    assert wait(app, lambda: page.preset.currentIndex() == (first + 1) % page.preset.count())
    p.cmd("trilha_preset_passo", trilha="guitar", d=-1)
    assert wait(app, lambda: page.preset.currentIndex() == first)
    name = factory_names("guitar")[2]
    g.values["track"]["volume"] = -7.0                         # o volume da trilha não muda com preset
    p.cmd("trilha_preset", trilha="guitar", tipo="factory", nome=name)
    assert wait(app, lambda: tuple(page.preset.currentData()) == ("factory", name))
    for eff, vals in FACTORY["guitar"][name]["values"].items():
        if "on" in vals and eff in g.values and eff != "track":
            assert g.values[eff]["on"] == vals["on"], eff
    assert g.values["track"]["volume"] == -7.0
    p.cmd("trilha_preset", trilha="guitar", tipo="user", nome="não existe")
    p.cmd("trilha_preset", trilha="guitar", tipo="../x", nome=name)
    p.cmd("trilha_preset", trilha="guitar", tipo="factory", nome=["x"])
    drain(app, p)
    assert tuple(page.preset.currentData()) == ("factory", name)
    assert p.state["guitarra"]["preset"] == "★ " + name and p.state["guitarra"]["atual"] == "factory:" + name
    assert win.tabs.currentIndex() == pc_tab
    # baixo também
    bp = win.track_pages["bass"]
    b0 = bp.preset.currentIndex()
    p.cmd("trilha_preset_passo", trilha="bass", d=1)
    assert wait(app, lambda: bp.preset.currentIndex() == (b0 + 1) % bp.preset.count())
    assert win.tabs.currentIndex() == pc_tab
    p.close()


def test_guitar_user_cannot_touch_bass_and_vice_versa(win, app):
    port = serve(win, aberto=["baixo"])
    g, b = win.engine.tracks["guitar"], win.engine.tracks["bass"]
    p = Page(port)
    p.until("auth")
    drain(app, p)
    assert {k.split(".")[0] for k in p.state} == {"baixo"}
    gv = g.values["track"]["volume"]
    rv = g.values["reverb"]["on"]
    p.cmd("trilha_volume", trilha="guitar", valor=0)
    p.cmd("efeito_on", trilha="guitar", efeito="reverb", on=not rv)
    p.cmd("trilha_on", trilha="guitar", on=False)
    p.cmd("trilha_salvar", trilha="guitar", nome="Invasor")
    p.cmd("timbre_salvar", nome="Invasor")
    p.cmd("trilha_volume", trilha="bass", valor=0)             # o baixo pode
    assert wait(app, lambda: b.values["track"]["volume"] == -60.0)
    drain(app, p)
    assert g.values["track"]["volume"] == gv and g.values["reverb"]["on"] == rv and g.values["track"]["on"]
    assert storage.list_user_presets("guitar") == [] and storage.list_user_presets("teclas") == []
    p.close()


def test_save_track_preset_from_the_phone(win, app, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: pytest.fail("abriu janela no PC")))
    port = serve(win)
    page = win.track_pages["guitar"]
    g = win.engine.tracks["guitar"]
    p = Page(port)
    p.until("auth")
    drain(app, p)
    g.set_on("chorus", True)
    p.cmd("trilha_salvar", trilha="guitar", nome="  Meu Solo  ")
    assert p.until("aviso")["texto"] == "Salvo: Meu Solo"
    assert storage.list_user_presets("guitar") == ["Meu Solo"]
    saved = storage.load_user_preset("guitar", "Meu Solo")
    assert saved["values"]["chorus"]["on"] and "track" not in saved["values"]
    assert tuple(page.preset.currentData()) == ("user", "Meu Solo")
    drain(app, p)
    assert p.state["guitarra"]["preset"] == "Meu Solo" and p.state["guitarra"]["nome_salvar"] == "Meu Solo"
    assert p.state["guitarra.presets"][0]["sons"] == [{"nome": "user:Meu Solo", "curto": "Meu Solo"}]
    p.cmd("trilha_salvar", trilha="guitar", nome="   ")
    assert "nome" in p.until("aviso")["texto"]
    # volta para ele pelo celular
    g.set_on("chorus", False)
    page.preset_step(1)
    p.cmd("trilha_preset", trilha="guitar", tipo="user", nome="Meu Solo")
    assert wait(app, lambda: g.values["chorus"]["on"])
    p.close()


def test_save_setup_on_the_timbre_screen(win, app, monkeypatch):
    """💾 Salvar setup: o mesmo que salvar o timbre no PC (camadas, volumes, efeitos), sem janela no PC,
    e depois dá para voltar a ele com ◀ ▶ na tela Timbre."""
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: pytest.fail("abriu janela no PC")))
    port = serve(win)
    inst = win.inst
    p = Page(port)
    p.until("auth")
    drain(app, p)
    assert p.state["timbre"]["nome_salvar"]
    p.cmd("timbre_camada", camada=1, nome="Rhodes")
    assert wait(app, lambda: inst.keys["sound1"] == "Rhodes")
    win.tabs.setCurrentWidget(win.track_pages["bass"])
    pc_tab = win.tabs.currentIndex()
    p.cmd("timbre_salvar", nome="Culto Domingo")
    assert p.until("aviso")["texto"] == "Setup salvo: Culto Domingo"
    data = storage.load_user_preset("teclas", "Culto Domingo")
    assert data["keys"]["sound1"] == "Rhodes"
    assert win.pad_view.user_preset == "Culto Domingo"
    c = win.ready_combo
    assert ("keys_user", "Culto Domingo") in [tuple(c.itemData(i) or ()) for i in range(c.count())]
    assert win.tabs.currentIndex() == pc_tab
    drain(app, p)
    assert p.state["timbre"]["preset"] == "Culto Domingo" and p.state["timbre"]["nome_salvar"] == "Culto Domingo"
    p.cmd("timbre_salvar", nome="")
    assert "nome" in p.until("aviso")["texto"]
    # mexe no som e volta para o setup salvo com ▶
    p.cmd("timbre_camada", camada=1, nome="Coral")
    assert wait(app, lambda: inst.keys["sound1"] == "Coral" and not win.pad_view.user_preset)
    for _ in range(c.count() + 2):
        before = win.pad_view.title.text()
        p.cmd("preset_passo", d=1)
        assert wait(app, lambda: win.pad_view.title.text() != before)
        if win.pad_view.user_preset == "Culto Domingo":
            break
    assert win.pad_view.user_preset == "Culto Domingo" and inst.keys["sound1"] == "Rhodes"
    assert win.tabs.currentIndex() == pc_tab
    p.close()


def test_play_twice_loops_the_recording_until_stop(win, app):
    """PLAY na tela Pads: 1 toque toca uma vez na hora; o 2º toque logo depois faz a mesma gravação
    repetir em loop (a página mostra ⟳ LOOP) até o STOP."""
    import numpy as np
    from ampsim.audio import sampler as smp
    port = serve(win)
    e = win.engine
    data = np.full((4800, 2), 0.2, np.float32)
    name = smp.save_recording(data, 48000, "Intro")
    e.sampler.put(name, data, 48000)
    mix = np.zeros((256, 2))
    p = Page(port)
    p.until("auth")
    drain(app, p, 2.5)                                    # o banco relê a pasta
    assert name in p.state["pads.gravador"]["gravacoes"] and p.state["pads.gravador"]["loop"] == ""
    p.cmd("rec_ouvir", nome=name)                          # 1º toque: toca já
    assert wait(app, lambda: len(e.sampler.events) == 1)
    e.sampler.render(mix, 256, 1.0)                       # o callback começa a tocar
    assert len(e.sampler.voices) == 1 and e.sampler.looping == ""
    p.cmd("rec_ouvir", nome=name, loop=True)              # 2º toque: a mesma voz vira loop
    assert wait(app, lambda: len(e.sampler.events) == 1)
    for _ in range(60):                                   # bem mais que os 0,1 s da gravação
        e.sampler.render(mix, 256, 1.0)
    assert len(e.sampler.voices) == 1 and e.sampler.looping == name
    win.remote.push()
    drain(app, p)
    assert p.state["pads.gravador"]["loop"] == name
    p.cmd("rec_parar")                                    # STOP encerra o loop
    assert wait(app, lambda: e.sampler.looping == "")
    e.sampler.render(mix, 256, 1.0)
    assert not e.sampler.voices
    win.remote.push()
    drain(app, p)
    assert p.state["pads.gravador"]["loop"] == ""
    p.cmd("rec_ouvir", nome="não existe", loop=True)
    p.cmd("rec_ouvir", nome=name, loop="sim")             # só true de verdade liga o loop
    drain(app, p)
    e.sampler.render(mix, 256, 1.0)
    assert e.sampler.looping == ""
    p.close()


def test_master_and_compressor_faders(win, app):
    """Faders: Master no lugar do Click (na barra do PC e no celular) e o Compressor da saída
    logo depois do Master (só no celular), o mesmo knob "Compressor" do MIDI."""
    from ampsim.ui.dock import STRIPS
    from ampsim.ui.funcs import func_value
    assert [s[2] for s in STRIPS][-2:] == ["Master", "Compressor"] and "Volume do metrônomo" not in [s[2] for s in STRIPS]
    assert win.inst.levels["comp"] == 0                    # padrão: desligado (nenhum som muda)
    port = serve(win)
    p = Page(port)
    p.until("auth")
    drain(app, p)
    ch = {c["id"]: c for c in p.state["faders"]["canais"]}
    assert ch["Compressor"]["valor"] == 0 and not ch["Compressor"]["pode_mutar"]
    p.cmd("fader", id="Compressor", valor=60)
    assert wait(app, lambda: win.inst.levels["comp"] == 60)
    p.cmd("fader", id="Compressor", valor=500)
    assert wait(app, lambda: win.inst.levels["comp"] == 100)
    p.cmd("fader", id="Master", valor=50)
    assert wait(app, lambda: abs(func_value(win.engine, "Master") - 50) < 1.5)
    drain(app, p)
    ch = {c["id"]: c for c in p.state["faders"]["canais"]}
    assert ch["Compressor"]["valor"] == 100 and abs(ch["Master"]["valor"] - 50) <= 1
    p.cmd("mute", id="Compressor", on=True)                # sem mute
    p.cmd("pad_volume", id="Compressor", valor=0)          # só pela aba Faders
    drain(app, p)
    assert win.inst.levels["comp"] == 100
    # o motor usa a quantidade no compressor da saída, e ela é salva com o estado das teclas
    import numpy as np
    out = np.zeros((256, 2), np.float32)
    win.engine._render(None, out, 256)
    assert win.engine._lim[3] == 1.0
    assert win.inst.get_state()["levels"]["comp"] == 100
    p.close()


def test_turn_layer2_off_and_remove_extra_layers_from_the_phone(win, app):
    """Tela Timbre: desligar/ligar a L2 (como o interruptor do PC, o timbre dela fica guardado) e remover
    a L3/L4; a lista diz quais camadas estão soando."""
    port = serve(win)
    inst = win.inst
    p = Page(port)
    p.until("auth")
    drain(app, p)
    p.cmd("timbre_camada", camada=1, nome="Rhodes")
    p.cmd("timbre_camada", camada=2, nome="Cordas Lentas")
    assert wait(app, lambda: inst.keys["sound2"] == "Cordas Lentas" and inst.keys["layer2_on"])
    p.cmd("timbre_l2", on=False)
    assert wait(app, lambda: not inst.keys["layer2_on"])
    assert inst.keys["sound2"] == "Cordas Lentas"                  # só desligou
    drain(app, p)
    assert [x["ligada"] for x in p.state["timbre"]["lista"]][:2] == [True, False]
    assert p.state["timbre"]["camadas"] == ["Rhodes"]               # só a L1 soa
    p.cmd("timbre_l2", on=True)
    assert wait(app, lambda: inst.keys["layer2_on"])
    # L3 e L4: criar e remover
    n = inst.layer_count()
    p.cmd("timbre_camada", camada=n + 1, nome="Coral")
    assert wait(app, lambda: inst.layer_count() == n + 1)
    p.cmd("timbre_camada", camada=n + 2, nome="Sinos")
    assert wait(app, lambda: inst.layer_count() == n + 2)
    p.cmd("timbre_remover", camada=n + 1)                          # remove a L3: a L4 vira L3
    assert wait(app, lambda: inst.layer_count() == n + 1)
    assert inst.layer_sounds()[-1][1] == "Sinos"
    # o que não vale é ignorado: L1/L2 não saem, camada que não existe, tipos errados
    for kw in ({"camada": 1}, {"camada": 2}, {"camada": 9}, {"camada": "3"}, {"camada": True}):
        p.cmd("timbre_remover", **kw)
    for kw in ({"on": "nao"}, {"on": 0}, {}):
        p.cmd("timbre_l2", **kw)
    drain(app, p)
    assert inst.layer_count() == n + 1 and inst.keys["layer2_on"]
    assert [x["som"] for x in p.state["timbre"]["lista"]] == ["Rhodes", "Cordas Lentas", "Sinos"]
    p.close()


# ------------------------------------------------------------------ entradas ruins e casos da revisão
BAD_VALUES = ("abc", None, [], {}, [1], {"x": 1}, True, False, float("nan"), float("inf"), -float("inf"), 1e400,
              "1", "", "\x00", -1, 10 ** 12)


def _all_fields():
    return ("i", "vel", "tom", "nome", "id", "valor", "on", "d", "camada", "trilha", "tipo", "efeito", "param", "loop")


def _snapshot(win):
    """O que importa do estado (sem o que muda sozinho, como o tempo de gravação)."""
    st = json.loads(json.dumps(win.remote.state(), default=str))
    st.pop("timbre.sons", None)
    st.pop("pads.sons", None)
    return st


def test_wrong_types_never_raise_or_change_anything(win, app, monkeypatch):
    """Fuzz: todo comando, com cada campo de tipo errado (texto, lista, NaN, infinito, null...), não levanta
    exceção na interface (o Remote.apply roda num slot do Qt) e não muda nada."""
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: pytest.fail("abriu janela no PC")))
    hits = []
    win.engine.instruments.pad_hit = lambda i, v=110: hits.append((i, v))
    before = _snapshot(win)
    files = {k: storage.list_user_presets(k) for k in ("teclas", "guitar", "bass")}
    remote = win.remote
    for c in COMMAND_PANEL:
        if c in ("pad_parar", "rec", "rec_parar"):
            continue                                   # sem campos (e mexem no gravador/pad de propósito)
        for field in _all_fields():
            for bad in BAD_VALUES:
                for trilha in ("guitar", "bass"):
                    msg = {"t": "cmd", "c": c, "trilha": trilha, field: bad}
                    if c in ("timbre_salvar", "trilha_salvar") and field == "nome" and isinstance(bad, str) and bad.strip("\x00"):
                        continue                        # nomes de texto são válidos (testados abaixo)
                    if c == "rec_ouvir" and field != "loop" and field != "nome":
                        continue
                    if field in ("on", "loop") and isinstance(bad, bool):
                        continue                        # booleano é o valor certo desses campos
                    if field in ("d", "valor") and not isinstance(bad, bool) and isinstance(bad, (int, float))                             and bad == bad and abs(bad) != float("inf") and bad != 0:
                        continue                        # número de verdade é valor válido (só limitado)
                    remote._from_server(msg, list(wcfg.PANEL_IDS)) if c == "pad" else remote.apply(msg)
    app.processEvents()
    assert hits == []
    assert _snapshot(win) == before
    assert {k: storage.list_user_presets(k) for k in ("teclas", "guitar", "bass")} == files


def test_names_with_control_chars_are_cleaned_and_reserved_names_saved(win, app, monkeypatch):
    from ampsim.web.remote import clean_name
    assert clean_name("  Meu\x00 Set\nup\t ") == "Meu Set up"               # controle vira 1 espaço
    assert clean_name("linha\nnova") == "linha nova" and clean_name("a \t\t b") == "a b"
    assert clean_name("\x00\x01") == "" and clean_name(["x"]) == "" and clean_name("...") == ""
    assert clean_name("CON") == "_CON" and clean_name("x" * 200) == "x" * 60
    port = serve(win)
    p = Page(port)
    p.until("auth")
    p.cmd("trilha_salvar", trilha="guitar", nome="Solo\x00\n1")
    assert p.until("aviso")["texto"] == "Salvo: Solo 1"
    p.cmd("trilha_salvar", trilha="guitar", nome="a:b")
    assert p.until("aviso")["texto"] == "Salvo: a_b"                 # o nome como ficou na lista
    assert "a_b" in storage.list_user_presets("guitar")
    p.cmd("timbre_salvar", nome="AUX")
    assert p.until("aviso")["texto"] == "Setup salvo: _AUX"
    p.cmd("timbre_salvar", nome="\x07\x00")
    assert "nome" in p.until("aviso")["texto"]
    # disco recusou: avisa o celular em vez de quebrar
    monkeypatch.setattr(storage, "save_user_preset", lambda *a: (_ for _ in ()).throw(OSError("disco cheio")))
    p.cmd("trilha_salvar", trilha="bass", nome="Novo")
    assert "Não deu para salvar" in p.until("aviso")["texto"]
    p.close()


def test_invalid_numbers_are_ignored_not_zeroed(win, app):
    port = serve(win)
    g = win.engine.tracks["guitar"]
    page = win.track_pages["guitar"]
    p = Page(port)
    p.until("auth")
    drain(app, p)
    vol, mix, idx, comp = g.values["track"]["volume"], g.values["delay"]["mix"], page.preset.currentIndex(), win.inst.levels["comp"]
    for bad in ("abc", None, True, [3]):
        p.cmd("trilha_volume", trilha="guitar", valor=bad)
        p.cmd("efeito_param", trilha="guitar", efeito="delay", param="mix", valor=bad)
        p.cmd("trilha_preset_passo", trilha="guitar", d=bad)
        p.cmd("fader", id="Compressor", valor=bad)
    p.send(t="cmd", c="trilha_volume", trilha="guitar", valor=float("nan"))
    p.send(t="cmd", c="fader", id="Compressor", valor=float("inf"))
    drain(app, p)
    assert g.values["track"]["volume"] == vol and g.values["delay"]["mix"] == mix
    assert page.preset.currentIndex() == idx and win.inst.levels["comp"] == comp
    p.close()


def test_output_compressor_is_not_part_of_presets(win, app):
    """O Compressor é da saída (como o Master): salvar/carregar timbre, cena ou música não mexe nele."""
    from ampsim import sharing
    inst = win.inst
    inst.levels["comp"] = 70
    assert "comp" not in sharing.sound_state(inst.get_state())["levels"]
    assert win.save_keys_preset("Com comp") == "Com comp"
    assert "comp" not in storage.load_user_preset("teclas", "Com comp")["levels"]
    old = sharing.sound_state(inst.get_state())
    old["levels"]["comp"] = 5                                   # preset antigo que levou o comp junto
    storage.save_user_preset("teclas", "Antigo", old)
    win._rebuild_ready_combo()
    win.load_from_bank("keys_user", "Antigo")
    assert inst.levels["comp"] == 70
    win.load_from_bank("keys_user", "Com comp")
    assert inst.levels["comp"] == 70
    # a sessão guarda (como o master)
    assert inst.get_state()["levels"]["comp"] == 70


def test_auto_stop_at_the_limit_is_quiet_when_started_from_the_phone(win, app, monkeypatch):
    """A gravação começada no celular que chega nos 60 s para sozinha sem abrir janela no PC e avisa o celular."""
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a)))
    monkeypatch.setattr(type(win.engine), "running", property(lambda self: True))
    port = serve(win)
    e = win.engine
    p = Page(port)
    p.until("auth")
    p.cmd("rec")
    assert wait(app, lambda: e.recorder.active)
    e.recorder.active = False                                   # chegou no limite (o callback parou) com silêncio
    assert "limite" in p.until("aviso", timeout=3)["texto"]
    assert shown == [] and not win.dock.recorder._recording
    p.close()


def test_single_play_while_looping_stops_the_loop_and_plays_once(win, app):
    import numpy as np
    from ampsim.audio import sampler as smp
    port = serve(win)
    e = win.engine
    data = np.full((4800, 2), 0.2, np.float32)
    name = smp.save_recording(data, 48000, "Intro")
    e.sampler.put(name, data, 48000)
    mix = np.zeros((256, 2))
    p = Page(port)
    p.until("auth")
    win.remote._recs = ([], 0.0)
    p.cmd("rec_ouvir", nome=name, loop=True)
    assert wait(app, lambda: len(e.sampler.events) == 1)
    e.sampler.render(mix, 256, 1.0)
    assert e.sampler.looping == name
    p.cmd("rec_ouvir", nome=name)                                 # 1 toque com o loop tocando
    assert wait(app, lambda: len(e.sampler.events) >= 2)
    e.sampler.render(mix, 256, 1.0)
    assert e.sampler.looping == "" and len(e.sampler.voices) == 1     # parou o loop e tocou 1 vez
    # e o PC mostra o loop e o STOP de lá para
    p.cmd("rec_ouvir", nome=name, loop=True)
    assert wait(app, lambda: len(e.sampler.events) >= 1)
    e.sampler.render(mix, 256, 1.0)
    rec = win.dock.recorder
    rec._loop_tick()
    assert rec.stop_btn.isEnabled() and "loop" in rec.time.text()
    rec.stop()
    e.sampler.render(mix, 256, 1.0)
    rec._loop_tick()
    assert e.sampler.looping == "" and not rec.stop_btn.isEnabled() and rec.time.text() == ""
    p.close()


def test_restricted_old_profiles_stay_restricted(win, app):
    """Perfil antigo só com Tempo/Mute (telas que saíram) fica sem tela: não ganha Guitarra, Baixo nem
    Faders; o PC mostra "nenhuma tela" para o administrador ver. Quem tinha as 6 telas ganha todas."""
    assert wcfg.clean_panels(["tempo", "emergencia"]) == [] and wcfg.clean_panels(["tempo"]) == []
    assert wcfg.clean_panels([]) == [] and wcfg.clean_panels(["pads", "tempo"]) == ["pads"]
    old11 = ["pads", "faders", "setlist", "tempo", "emergencia", "timbre"]
    assert wcfg.clean_panels(old11, migrate=True) == list(wcfg.PANEL_IDS)
    assert wcfg.clean_panels(old11) == ["pads", "faders", "setlist", "timbre"]       # sem migrar: como está
    cfg = wcfg.default()
    wcfg.set_user(cfg, "mesa", "1234", ["faders"])
    cfg["usuarios"][0]["telas"] = ["tempo", "emergencia"]
    cfg["login"] = True
    wcfg.save(cfg)
    loaded = wcfg.load()
    assert loaded["usuarios"][0]["telas"] == []
    port = serve(win, login=True, usuarios=loaded["usuarios"])
    p = Page(port)
    assert p.recv()["t"] == "precisa_login"
    p.send(t="login", nome="mesa", senha="1234")
    m = p.until("auth")
    assert m["ok"] and m["telas"] == []
    g = win.engine.tracks["guitar"].values["track"]["volume"]
    p.cmd("trilha_volume", trilha="guitar", valor=0)
    p.cmd("trilha_volume", trilha="bass", valor=0)
    p.cmd("fader", id="Drive", valor=90)
    drain(app, p)
    assert win.engine.tracks["guitar"].values["track"]["volume"] == g and p.state == {}
    p.close()
    from ampsim.ui.webserver_dialog import WebServerDialog
    d = WebServerDialog(win.remote, win)
    assert "nenhuma tela" in d.users.item(0).text()
    d.close()


def test_track_screen_shows_nam_and_short_amp_names(win, app):
    from ampsim.dsp.params import AMP_MODELS
    port = serve(win)
    b = win.engine.tracks["bass"]
    p = Page(port)
    p.until("auth")
    drain(app, p)
    assert p.state["baixo"]["nam"] == ""
    amp = {x["k"]: x for x in next(f for f in p.state["baixo"]["efeitos"] if f["k"] == "amp")["params"]}
    assert amp["model"]["opcoes"] == [m["name"] for m in AMP_MODELS]          # sem o "(estilo …)"
    b.values["nam"]["file"] = "dUg DP3X"
    b.values["nam"]["on"] = True
    b.set_param("track", "volume", -60.0)
    win.remote.push()
    drain(app, p)
    assert p.state["baixo"]["nam"] == "dUg DP3X"
    assert p.state["baixo"]["txt"] == "-∞ dB" and p.state["baixo"]["on"]      # volume no mínimo não é "mudo"
    p.close()


def test_vu_messages_only_for_the_faders_screen(win, app):
    """Medidores do Master e do Compressor: mensagem curta {"t":"vu"} (~15x/s, só quando muda), só para
    quem vê a tela Faders; o estado grande não é reenviado por causa deles."""
    import numpy as np
    cfg = wcfg.default()
    wcfg.set_user(cfg, "mesa", "1", ["faders"])
    wcfg.set_user(cfg, "batera", "1", ["pads"])
    port = serve(win, login=True, usuarios=cfg["usuarios"])
    win.timer.stop()                                     # o tick de verdade chamaria meter() com silêncio
    pages = {}
    for nome in ("mesa", "batera"):
        p = Page(port)
        p.recv()
        p.send(t="login", nome=nome, senha="1")
        assert p.until("auth")["ok"]
        drain(app, p)
        pages[nome] = p
    # nível alto na saída e o compressor segurando 6 dB
    e = win.engine
    e._lim[9] = 0.5
    e._lim[10] = 10 ** (-6 / 20)
    peak, gr = e.read_output_meter()
    assert abs(peak - 0.5) < 1e-9 and abs(gr - 6.0) < 1e-6
    assert e.read_output_meter() == (0.0, 0.0)            # leu e zerou
    for _ in range(2):
        win.remote.meter(peak, gr)
    got = []
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        app.processEvents()
        try:
            m = pages["mesa"].recv(0.02)
        except TimeoutError:
            continue
        if m["t"] == "vu":
            got.append(m)
        assert m["t"] != "estado"                         # nada de estado por causa do medidor
    assert got and abs(got[-1]["m"] - round((20 * np.log10(0.5) + 60) / 60, 2)) < 0.011
    assert abs(got[-1]["c"] - 0.3) < 0.011
    other = []
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        app.processEvents()
        try:
            other.append(pages["batera"].recv(0.02)["t"])
        except TimeoutError:
            pass
    assert "vu" not in other
    # sem mudança: não manda de novo; silêncio cai aos poucos (com queda suave) até zerar
    n = len(got)
    for _ in range(4):
        win.remote.meter(0.0, 0.0)
    drain(app, pages["mesa"], 0.3)
    for p in pages.values():
        p.close()
    assert n >= 1


def test_vu_bandwidth_is_small(win, app):
    """~15 mensagens de ~25 bytes por segundo com o medidor mexendo o tempo todo."""
    import json as js
    sent = []
    win.remote.server.publish_vu = lambda msg: sent.append(js.dumps(msg, separators=(",", ":")))
    win.remote.server.server = object()                  # "ligado"
    win.remote.server.clients = {object()}
    for i in range(30):                                   # 1 s de ticks a 30/s
        win.remote.meter(0.1 + 0.8 * (i % 2), 0.0)
    win.remote.server.server = None
    win.remote.server.clients = set()
    assert len(sent) <= 15 and max(len(x) for x in sent) <= 30


def test_vu_is_resent_every_second_even_without_change(win, app):
    """Quem entra (ou recarrega) com o nível parado recebe o medidor em até 1 s."""
    sent = []
    srv = win.remote.server
    srv.publish_vu = lambda msg: sent.append(msg)
    srv.server, srv.clients = object(), {object()}
    try:
        for _ in range(65):                                # ~2 s de ticks a 30/s com o nível parado
            win.remote.meter(0.5, 3.0)
    finally:
        srv.server, srv.clients = None, set()
    assert len(sent) >= 3 and all(m == sent[0] for m in sent)


# ------------------------------------------------------------------ tela Vocal
def test_vocal_panel_permission_and_migration(dirs):
    from ampsim.web.server import command_panel
    assert "vocal" in wcfg.PANEL_IDS and wcfg.PANEL_IDS[-1] == "vocal"
    assert command_panel({"c": "trilha_on", "trilha": "vocal"}) == "vocal"
    assert command_panel({"c": "trilha_mute", "trilha": "vocal"}) == "vocal"
    assert command_panel({"c": "efeito_param", "trilha": "vocal"}) == "vocal"
    # perfil da 1.2 que via todas as telas passa a ver a Vocal; perfil restrito continua restrito
    v12 = ["pads", "faders", "setlist", "timbre", "guitarra", "baixo"]
    assert wcfg.clean_panels(v12, migrate=True) == list(wcfg.PANEL_IDS)
    assert wcfg.clean_panels(v12) == v12
    assert wcfg.clean_panels(["pads", "guitarra"], migrate=True) == ["pads", "guitarra"]
    p = wcfg.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ligado": True, "aberto": v12, "usuarios": [
        {"nome": "Líder", "sal": "00", "hash": "x", "telas": v12},
        {"nome": "Batera", "sal": "00", "hash": "x", "telas": ["pads", "faders"]}]}), encoding="utf-8")
    c = wcfg.load()
    assert "vocal" in c["aberto"] and "vocal" in c["usuarios"][0]["telas"]
    assert c["usuarios"][1]["telas"] == ["pads", "faders"]


def test_vocal_screen_state_and_commands(win, app):
    from ampsim.dsp.vocal import VOCAL_EFFECTS
    port = serve(win)
    v = win.engine.tracks["vocal"]
    page = win.track_pages["vocal"]
    win.tabs.setCurrentWidget(win.pad_view)               # o PC está em outra aba
    pc_tab = win.tabs.currentIndex()
    p = Page(port)
    p.until("auth")
    drain(app, p)
    st = p.state["vocal"]
    assert [f["k"] for f in st["efeitos"]] == [e.key for e in VOCAL_EFFECTS]
    assert {f["curto"] for f in st["efeitos"]} >= {"Filtro", "Comp", "Anti-S", "Dobra", "Reverb"}
    assert not st["on"] and not st["mudo"] and st["pode_mutar"] and st["aviso"] == ""
    names = [s["nome"] for c in p.state["vocal.presets"] for s in c["sons"]]
    assert names == ["factory:" + n for n in factory_names("vocal")]
    # liga o microfone, mudo, volume
    p.cmd("trilha_on", trilha="vocal", on=True)
    assert wait(app, lambda: v.on)
    p.cmd("trilha_mute", trilha="vocal", on=True)
    assert wait(app, lambda: v.values["track"]["mute"])
    drain(app, p)
    assert p.state["vocal"]["mudo"] and win.dock.mute_buttons["vocal"].isChecked()
    p.cmd("trilha_mute", trilha="vocal", on=False)
    assert wait(app, lambda: not v.values["track"]["mute"])
    p.cmd("trilha_volume", trilha="vocal", valor=50)
    assert wait(app, lambda: abs(v.values["track"]["volume"] - (-24.0)) < 1e-6)
    # pedais e parâmetros (número, log e escolha)
    p.cmd("efeito_on", trilha="vocal", efeito="deess", on=True)
    assert wait(app, lambda: v.values["deess"]["on"])
    p.cmd("efeito_param", trilha="vocal", efeito="comp", param="amount", valor=75)
    assert wait(app, lambda: v.values["comp"]["amount"] == 75.0)
    p.cmd("efeito_param", trilha="vocal", efeito="hpf", param="freq", valor=100)
    assert wait(app, lambda: v.values["hpf"]["freq"] == 200.0)
    p.cmd("efeito_param", trilha="vocal", efeito="reverb", param="type", valor=9)
    assert wait(app, lambda: v.values["reverb"]["type"] == 2.0)
    # preset de fábrica pela lista
    p.cmd("trilha_preset", trilha="vocal", tipo="factory", nome="Voz falada (pregação)")
    assert wait(app, lambda: page.preset.currentData() == ("factory", "Voz falada (pregação)"))
    assert v.on and v.values["comp"]["amount"] == 65
    # fader Vocal na tela Faders, com mudo
    drain(app, p)
    fv = {f["id"]: f for f in p.state["faders"]["canais"]}["vocal"]
    assert fv["pode_mutar"] and fv["nome"] == "Vocal"
    p.cmd("mute", id="vocal", on=True)
    assert wait(app, lambda: v.values["track"]["mute"])
    p.cmd("pad_mute", id="vocal", on=False)                   # a tela Pads não mexe na voz
    drain(app, p)
    assert v.values["track"]["mute"]
    # o que não existe é ignorado: pedal de guitarra na Vocal, mudo na guitarra
    before = dict(v.values["comp"])
    p.cmd("efeito_on", trilha="vocal", efeito="amp", on=True)
    p.cmd("efeito_param", trilha="vocal", efeito="comp", param="amount", valor="x")
    p.cmd("trilha_mute", trilha="guitar", on=True)
    drain(app, p)
    assert v.values["comp"] == before and "mute" not in win.engine.tracks["guitar"].values["track"]
    assert win.tabs.currentIndex() == pc_tab                  # o celular não troca a aba do PC
    p.close()


def test_vocal_screen_needs_its_permission(win, app):
    port = serve(win, aberto=["guitarra"])
    v = win.engine.tracks["vocal"]
    p = Page(port)
    p.until("auth")
    drain(app, p)
    assert "vocal" not in p.state
    p.cmd("trilha_on", trilha="vocal", on=True)
    drain(app, p)
    assert not v.on
    p.close()


def test_vocal_page_and_mode_in_the_web_app():
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert '{ id: "vocal", nome: "Vocal", telas: ["vocal"] }' in js
    assert 'trackPanel(sec, "vocal", "do vocal")' in js and 'tc("trilha_mute"' in js


def test_profile_without_vocal_stays_without_vocal(dirs, win):
    """QA rodada 8: a migração 1.2 -> Vocal roda uma vez só (arquivo sem versão). Depois, um perfil (ou o acesso
    aberto) com todas as telas menos a Vocal continua assim ao salvar e abrir de novo."""
    v12 = ["pads", "faders", "setlist", "timbre", "guitarra", "baixo"]
    cfg = wcfg.load()                                       # sem arquivo: padrão (versão atual)
    assert cfg["versao"] == wcfg.VERSION
    wcfg.set_user(cfg, "Líder", "1234", v12)
    cfg["aberto"] = list(v12)
    wcfg.save(cfg)
    for _ in range(2):                                      # abrir e salvar de novo não muda nada
        c = wcfg.load()
        assert c["aberto"] == v12 and c["usuarios"][0]["telas"] == v12
        assert wcfg.check(c, "Líder", "1234") == v12
        wcfg.save(c)
    # pela tela remota do PC (janela Webserver -> Remote.set_config): mesma coisa
    c = wcfg.load()
    c["ligado"] = False
    win.remote.set_config(c)
    assert wcfg.load()["aberto"] == v12
    # arquivo antigo (1.2, sem versão) migra uma vez e grava a versão
    _write_old_config({"ligado": False, "aberto": v12, "usuarios": [
        {"nome": "Líder", "sal": "00", "hash": "x", "telas": v12},
        {"nome": "Batera", "sal": "00", "hash": "x", "telas": ["pads", "faders"]}]})
    c = wcfg.load()
    assert "vocal" in c["aberto"] and "vocal" in c["usuarios"][0]["telas"]
    assert c["usuarios"][1]["telas"] == ["pads", "faders"]
    assert json.loads(wcfg.path().read_text(encoding="utf-8"))["versao"] == wcfg.VERSION
    # depois da migração, tirar a Vocal de novo fica valendo
    c["aberto"] = list(v12)
    c["usuarios"][0]["telas"] = list(v12)
    wcfg.save(c)
    c = wcfg.load()
    assert c["aberto"] == v12 and c["usuarios"][0]["telas"] == v12


def test_vocal_fader_needs_vocal_permission(win, app):
    """QA rodada 8: perfil com Faders e sem Vocal não vê nem mexe no fader Vocal (nem no mudo dele)."""
    from ampsim.web.server import command_allowed, visible_state
    assert not command_allowed({"c": "fader", "id": "vocal", "valor": 10}, ["faders"])
    assert not command_allowed({"c": "mute", "id": "vocal", "on": True}, ["faders"])
    assert command_allowed({"c": "fader", "id": "vocal", "valor": 10}, ["faders", "vocal"])
    assert not command_allowed({"c": "fader", "id": "vocal", "valor": 10}, ["vocal"])          # sem Faders
    assert command_allowed({"c": "fader", "id": "Master", "valor": 10}, ["faders"])
    assert command_allowed({"c": "mute", "id": "Volume camada 1", "on": True}, ["faders"])
    data = {"canais": [{"id": "Master"}, {"id": "vocal"}]}
    assert visible_state("faders", data, ["faders"])["canais"] == [{"id": "Master"}]
    assert visible_state("faders", data, ["faders", "vocal"]) == data
    v = win.engine.tracks["vocal"]
    vol = v.values["track"]["volume"]
    port = serve(win, aberto=["faders"])
    p = Page(port)
    p.until("auth")
    drain(app, p)
    ids = [c["id"] for c in p.state["faders"]["canais"]]
    assert "vocal" not in ids and "Master" in ids
    m0 = win.engine.master
    p.cmd("fader", id="vocal", valor=5)
    p.cmd("mute", id="vocal", on=True)
    p.cmd("fader", id="Master", valor=40)
    assert wait(app, lambda: win.engine.master != m0)              # o resto da tela Faders funciona
    drain(app, p)
    assert v.values["track"]["volume"] == vol and not v.values["track"]["mute"]
    p.close()
    win.remote.stop()
    port = serve(win, aberto=["faders", "vocal"])
    p = Page(port)
    p.until("auth")
    drain(app, p)
    assert "vocal" in [c["id"] for c in p.state["faders"]["canais"]]
    p.cmd("mute", id="vocal", on=True)
    assert wait(app, lambda: v.values["track"]["mute"])
    p.close()


def test_short_portrait_phone_keeps_drum_pads_above_tabs():
    """QA: 320x568 (iPhone SE 1ª geração): na tela Pads a 2ª fileira de bateria ficava embaixo da barra de abas.
    Há um bloco só para tela em pé bem baixa (até 600 px) que encurta a barra de abas e as fileiras; medido com
    emulação de aparelho: 7 telas x 320x568, 320x640, 360x740, 390x844, 412x915, 740x360, 844x390, 768x1024 e
    1366x768 sem rolagem nem corte."""
    with open(os.path.join(STATIC, "app.css"), encoding="utf-8") as f:
        css = f.read()
    m = re.search(r"@media \(orientation: portrait\) and \(max-height: 600px\) and \(max-width: 1239px\) \{(.*?)\n\}",
                  css, re.S)
    assert m, "bloco do celular em pé bem baixo"
    block = m.group(1)
    tabs = int(re.search(r"--tabs-h: (\d+)px", block).group(1))
    rows = int(re.search(r"\.drumrow \{ min-height: (\d+)px", block).group(1))
    key = int(re.search(r"\.key \{ min-height: (\d+)px", block).group(1))
    assert tabs <= 52 and rows <= 96 and key >= 34                # ainda dá para tocar com o dedo
    assert "body.notabs { --tabs-h: 0px; }" in block               # sessão de uma tela só: sem barra
