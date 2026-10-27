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
        end = time.monotonic() + timeout
        while True:
            m = self.recv(max(0.05, end - time.monotonic()))
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
    wcfg.set_user(cfg, "Baterista", "1234", ["pads", "tempo", "xyz"])
    assert cfg["usuarios"][0]["telas"] == ["pads", "tempo"]
    assert "1234" not in json.dumps(cfg)
    assert wcfg.check(cfg, "baterista", "1234") == ["pads", "tempo"]
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


def test_page_only_sends_known_commands():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    used = set(re.findall(r'cmd\("(\w+)"', js))
    assert used and used <= set(COMMAND_PANEL), used - set(COMMAND_PANEL)
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
    port = serve(win, aberto=["pads", "tempo"])
    p = Page(port)
    m = p.until("auth")
    assert m["ok"] and m["telas"] == ["pads", "tempo"] and not m["login"]
    p.until("estado")
    assert set(p.state) == {"pads", "tempo"}
    assert len(p.state["pads"]["tons"]) == 12 and len(p.state["pads"]["bateria"]) == 8
    # sem permissão: o fader não muda
    before = win.engine.tracks["guitar"].values["track"]["volume"]
    p.cmd("fader", id="guitar", valor=0)
    drain(app, p)
    assert win.engine.tracks["guitar"].values["track"]["volume"] == before
    p.close()


def test_login_token_and_wrong_password(win, app):
    cfg = wcfg.default()
    wcfg.set_user(cfg, "mesa", "segredo", ["faders", "emergencia"])
    port = serve(win, login=True, usuarios=cfg["usuarios"])
    p = Page(port)
    assert p.recv()["t"] == "precisa_login"
    p.cmd("mute_geral", on=True)                         # antes de entrar: ignorado
    p.send(t="login", nome="mesa", senha="errada")
    m = p.until("auth")
    assert not m["ok"] and "errad" in m["erro"]
    assert not win.engine.muted
    p.send(t="login", nome="Mesa", senha="segredo")
    m = p.until("auth")
    assert m["ok"] and m["telas"] == ["faders", "emergencia"] and m["token"]
    p.until("estado")
    assert set(p.state) == {"faders", "emergencia"}
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
    new["usuarios"][0]["telas"] = ["tempo"]
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
    p.cmd("fader", id="guitar", valor=50)
    slider = [s for s in win.dock.strips if s[0] == ("track", "guitar")][0][1]
    assert wait(app, lambda: slider.value() == 50)
    drain(app, p)
    ch = {c["id"]: c for c in p.state["faders"]["canais"]}
    assert ch["guitar"]["valor"] == 50
    mutable = next(c["id"] for c in p.state["faders"]["canais"] if c["pode_mutar"])
    p.cmd("mute", id=mutable, on=True)
    assert wait(app, lambda: mutable in inst.mutes)
    drain(app, p)
    assert {c["id"]: c for c in p.state["faders"]["canais"]}[mutable]["mudo"]
    p.cmd("mute", id=mutable, on=False)
    assert wait(app, lambda: mutable not in inst.mutes)
    p.cmd("fader", id="nao-existe", valor=10)

    # tempo
    p.cmd("bpm", valor=97)
    assert wait(app, lambda: round(inst.bpm) == 97)
    p.cmd("click", on=True)
    assert wait(app, lambda: win.engine.metronome.on)
    p.cmd("click", on=False)
    assert wait(app, lambda: not win.engine.metronome.on)
    p.cmd("tap")
    drain(app, p, 0.1)
    time.sleep(0.4)
    p.cmd("tap")
    assert wait(app, lambda: 100 <= inst.bpm <= 140)

    # emergência
    p.cmd("mute_geral", on=True)
    assert wait(app, lambda: win.engine.muted and win.mute_banner.isVisibleTo(win))
    p.cmd("mute_geral", on=False)
    assert wait(app, lambda: not win.engine.muted)
    p.cmd("panico")
    drain(app, p)

    # preset do Pad/Piano muda sem trocar a aba do PC
    win.tabs.setCurrentIndex(0)
    before = win.pad_view.title.text()
    p.cmd("preset_passo", d=1)
    assert wait(app, lambda: win.pad_view.title.text() != before)
    assert win.tabs.currentIndex() == 0
    drain(app, p)
    assert p.state["timbre"]["preset"] == win.pad_view.title.text()

    # comando estranho não derruba nada
    p.send(t="cmd", c="bpm", valor="abc")
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
        p.recv(0.3)
    win.inst.set_bpm(133)
    win.remote.push()
    m = p.until("estado")
    assert set(m["telas"]) == {"tempo"}
    p.close()


def test_two_devices_at_once(win, app):
    port = serve(win)
    a, b = Page(port), Page(port)
    a.until("auth")
    b.until("auth")
    assert wait(app, lambda: len(win.remote.server.connected()) == 2)
    drain(app, b)
    a.cmd("bpm", valor=88)
    assert wait(app, lambda: round(win.inst.bpm) == 88)
    drain(app, b)
    assert round(b.state["tempo"]["bpm"]) == 88
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
    d.save_user("baterista", "1234", ["pads", "tempo"])
    assert d.users.count() == 1 and "Pads" in d.users.item(0).text()
    assert wcfg.check(wcfg.load(), "baterista", "1234") == ["pads", "tempo"]
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
