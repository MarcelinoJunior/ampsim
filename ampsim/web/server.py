"""Servidor da tela remota: página web + WebSocket na mesma porta, numa thread própria (asyncio).

Protocolo (JSON pelo WebSocket em /ws):
  aparelho -> {"t": "login", "nome", "senha"} | {"t": "token", "token"} | {"t": "cmd", "c": ..., ...}
              | {"t": "ping", "id"}
  servidor -> {"t": "precisa_login"} | {"t": "auth", "ok", "nome", "telas", "token", "erro"}
              | {"t": "estado", "telas": {tela: dados}} (só as telas liberadas e só o que mudou;
                "tela.parte" é um pedaço da tela que muda pouco, ex. "pads.sons" com o catálogo)
              | {"t": "pong", "id"} | {"t": "aviso", "texto"} (só para o aparelho que pediu)
              | {"t": "vu", "m", "c"} (~15x/s, só com a tela Faders: nível da saída e redução do compressor, 0..1)

Comandos chegam em on_command(cmd, telas) na thread do servidor; quem usa decide o que roda direto
(ex.: tocar um pad) e o que vai para a thread da interface.
"""
import asyncio
import json
import os
import secrets
import socket
import threading
import time

from . import config as wcfg

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FILES = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8"),
         "/icone.svg": ("icone.svg", "image/svg+xml")}
TOKEN_TTL = 12 * 3600
# trilha do AmpSim -> tela da página que controla ela
TRACK_PANEL = {"guitar": "guitarra", "bass": "baixo", "vocal": "vocal"}
# comando -> tela que precisa estar liberada (um dict: depende da "trilha" do comando)
COMMAND_PANEL = {
    "pad": "pads", "pad_cont": "pads", "pad_parar": "pads", "pad_timbre": "pads", "pad_som": "pads",
    "rec": "pads", "rec_parar": "pads", "rec_ouvir": "pads", "pad_volume": "pads", "pad_mute": "pads",
    "fader": "faders", "mute": "faders",
    "musica": "setlist", "musica_passo": "setlist", "setlist": "setlist",
    "preset_passo": "timbre", "timbre_camada": "timbre", "timbre_salvar": "timbre",
    "timbre_l2": "timbre", "timbre_remover": "timbre",
    "trilha_preset_passo": TRACK_PANEL, "trilha_preset": TRACK_PANEL, "trilha_volume": TRACK_PANEL,
    "trilha_on": TRACK_PANEL, "trilha_mute": TRACK_PANEL, "efeito_on": TRACK_PANEL, "efeito_param": TRACK_PANEL, "trilha_salvar": TRACK_PANEL,
}


# fader da tela Faders que é de uma trilha com tela própria: só quem vê essa tela também vê e mexe nele
FADER_PANEL = {"vocal": "vocal"}


def command_panel(msg):
    """Tela que o comando precisa (None = comando desconhecido ou trilha inválida)."""
    c = msg.get("c")
    p = COMMAND_PANEL.get(c) if isinstance(c, str) else None
    if isinstance(p, dict):
        t = msg.get("trilha")
        return p.get(t) if isinstance(t, str) else None
    return p


def command_allowed(msg, telas):
    """O aparelho com estas telas pode mandar este comando? (fader/mudo da Vocal pedem Faders E Vocal)"""
    tela = command_panel(msg)
    if tela is None or tela not in telas:
        return False
    if msg.get("c") in ("fader", "mute"):
        extra = FADER_PANEL.get(msg.get("id")) if isinstance(msg.get("id"), str) else None
        if extra is not None and extra not in telas:
            return False
    return True


def visible_state(tela, data, telas):
    """O que o aparelho vê de uma tela: na Faders, sem os faders de trilhas que ele não pode ver."""
    if tela == "faders" and isinstance(data, dict) and isinstance(data.get("canais"), list):
        hide = {fid for fid, p in FADER_PANEL.items() if p not in telas}
        if hide:
            data = dict(data, canais=[x for x in data["canais"] if x.get("id") not in hide])
    return data


def local_ips():
    """IPs desta máquina na rede local (o primeiro é o da rota padrão)."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))           # não manda nada: só escolhe a placa de rede da rota
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")] or ["127.0.0.1"]


class Client:
    def __init__(self, ws, addr):
        self.ws = ws
        self.addr = addr
        self.nome = ""
        self.telas = None              # None = ainda não entrou
        self.sent = {}                 # tela -> JSON já enviado
        self.since = time.time()


class WebServer:
    def __init__(self, on_command, get_state):
        self.on_command = on_command   # (cmd: dict, telas: list) na thread do servidor
        self.get_state = get_state     # () -> {tela: dados}, chamado na thread da interface
        self.cfg = wcfg.default()
        self.loop = None
        self.thread = None
        self.server = None
        self.port = None
        self.host = None
        self.error = ""
        self.clients = set()
        self.tokens = {}               # token -> (nome, telas, validade)
        self._state = {}

    # ------------------------------------------------------------------ ligar / desligar
    @property
    def running(self):
        return self.server is not None

    def start(self, cfg, host="0.0.0.0", port=None):
        """Liga na porta da configuração (ou `port`). -> True; em erro, False e self.error."""
        self.stop()
        self.cfg = cfg
        self.host = host
        want = cfg["porta"] if port is None else port
        ready = threading.Event()
        self.error = ""

        def run():
            loop = asyncio.new_event_loop()
            self.loop = loop
            asyncio.set_event_loop(loop)
            try:
                self.server = loop.run_until_complete(self._serve(host, want))
                self.port = self.server.sockets[0].getsockname()[1]
            except OSError as exc:
                self.error = (f"A porta {want} já está em uso (outro programa?). Escolha outra porta."
                              if getattr(exc, "winerror", None) == 10048 or exc.errno in (98, 10048)
                              else f"Não foi possível abrir o servidor: {exc}")
                self.server = None
            except ImportError:
                self.error = "Falta a biblioteca websockets: rode o instalar.bat de novo para atualizar."
                self.server = None
            ready.set()
            if self.server is not None:
                loop.run_forever()
            loop.close()

        self.thread = threading.Thread(target=run, name="ampsim-web", daemon=True)
        self.thread.start()
        ready.wait(10)
        return self.server is not None

    def stop(self):
        loop, server = self.loop, self.server
        if loop is None:
            return
        self.server = None

        async def shutdown():
            if server is not None:
                server.close()
                for c in list(self.clients):
                    try:
                        await c.ws.close()
                    except Exception:  # noqa: BLE001 - conexão já caiu
                        pass
                await server.wait_closed()
            loop.stop()
        try:
            asyncio.run_coroutine_threadsafe(shutdown(), loop)
        except RuntimeError:
            pass
        if self.thread is not None:
            self.thread.join(5)
        self.loop = None
        self.thread = None
        self.clients = set()
        self.tokens = {}

    def update_config(self, cfg):
        """Mudou usuários/telas: quem já está conectado precisa entrar de novo."""
        self.cfg = cfg
        self.tokens = {}
        if self.loop is not None:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._kick_all()))

    async def _kick_all(self):
        for c in list(self.clients):
            c.telas = None
            c.sent = {}
            await self._hello(c)

    def urls(self):
        if not self.running:
            return []
        return [f"http://{ip}:{self.port}" for ip in local_ips()]

    def connected(self):
        return [(c.nome or "(entrando)", c.addr) for c in list(self.clients)]

    # ------------------------------------------------------------------ estado (thread da interface)
    def publish(self, state):
        """Manda o estado novo (só o que mudou para cada aparelho). Chamado pela interface."""
        if self.loop is None or not self.clients:
            self._state = state
            return
        self._state = state
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._push_all()))

    def publish_vu(self, msg):
        """Medidores (Master e Compressor) para quem vê a tela Faders: mensagem curta, fora do estado."""
        if self.loop is None or not self.clients:
            return
        text = json.dumps(msg, separators=(",", ":"))
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._send_vu(text)))

    async def _send_vu(self, text):
        for c in list(self.clients):
            if c.telas is not None and "faders" in c.telas:
                try:
                    await c.ws.send(text)
                except Exception:  # noqa: BLE001 - aparelho saiu no meio
                    self.clients.discard(c)

    async def _push_all(self):
        for c in list(self.clients):
            await self._push(c)

    async def _push(self, c, full=False):
        if c.telas is None:
            return
        out = {}
        for tela, data in list(self._state.items()):
            if tela.split(".", 1)[0] not in c.telas:
                continue
            data = visible_state(tela, data, c.telas)
            text = json.dumps(data, sort_keys=True, ensure_ascii=False)
            if full or c.sent.get(tela) != text:
                c.sent[tela] = text
                out[tela] = data
        if out:
            await self._send(c, {"t": "estado", "telas": out})

    # ------------------------------------------------------------------ conexões
    async def _serve(self, host, port):
        from websockets.asyncio.server import serve
        return await serve(self._handler, host, port, process_request=self._http,
                           ping_interval=20, ping_timeout=20, max_size=64 * 1024)

    def _http(self, connection, request):
        """Página e arquivos estáticos; só /ws vira WebSocket."""
        from websockets.datastructures import Headers
        from websockets.http11 import Response
        path = request.path.split("?", 1)[0]
        if path == "/ws":
            # só a própria página do AmpSim conecta (um site qualquer aberto no celular não)
            origin = request.headers.get("Origin")
            if origin and origin.split("://", 1)[-1] != request.headers.get("Host", ""):
                return Response(403, "Forbidden", Headers([("Content-Type", "text/plain")]), b"origem recusada")
            return None
        item = FILES.get(path)
        if item is None:
            return Response(404, "Not Found", Headers([("Content-Type", "text/plain")]), b"nada aqui")
        with open(os.path.join(STATIC, item[0]), "rb") as f:
            body = f.read()
        headers = Headers([("Content-Type", item[1]), ("Cache-Control", "no-cache"),
                           ("Content-Length", str(len(body)))])
        return Response(200, "OK", headers, body)

    def tell(self, c, text):
        """Aviso curto só para o aparelho `c` (ex.: "o áudio está desligado")."""
        if self.loop is not None and c in self.clients:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._send(c, {"t": "aviso", "texto": text})))

    async def _send(self, c, msg):
        try:
            await c.ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:  # noqa: BLE001 - aparelho saiu no meio
            self.clients.discard(c)

    async def _hello(self, c):
        if self.cfg["login"]:
            await self._send(c, {"t": "precisa_login"})
        else:
            await self._enter(c, "", self.cfg["aberto"])

    async def _enter(self, c, nome, telas, token=None):
        c.nome = nome or "visitante"
        c.telas = list(telas)
        c.sent = {}
        if token is None and self.cfg["login"]:
            token = secrets.token_hex(16)
            self.tokens[token] = (nome, list(telas), time.time() + TOKEN_TTL)
        await self._send(c, {"t": "auth", "ok": True, "nome": c.nome, "telas": c.telas, "token": token,
                             "login": self.cfg["login"]})
        await self._push(c, full=True)

    async def _handler(self, ws):
        addr = ws.remote_address[0] if ws.remote_address else "?"
        c = Client(ws, addr)
        self.clients.add(c)
        try:
            await self._hello(c)
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                t = msg.get("t")
                if t == "ping":
                    await self._send(c, {"t": "pong", "id": msg.get("id")})
                elif t == "login":
                    telas = wcfg.check(self.cfg, str(msg.get("nome", "")), str(msg.get("senha", "")))
                    if telas is None:
                        await asyncio.sleep(0.5)         # devagar com quem erra a senha
                        await self._send(c, {"t": "auth", "ok": False, "erro": "Usuário ou senha errados"})
                    else:
                        await self._enter(c, str(msg.get("nome", "")).strip(), telas)
                elif t == "token":
                    tok = self.tokens.get(str(msg.get("token", "")))
                    if tok and tok[2] > time.time():
                        await self._enter(c, tok[0], tok[1], token=msg.get("token"))
                    else:
                        await self._send(c, {"t": "auth", "ok": False, "erro": ""})
                elif t == "cmd" and c.telas is not None:
                    if command_allowed(msg, c.telas):
                        msg["_c"] = c                    # quem pediu (para avisos)
                        try:
                            self.on_command(msg, c.telas)
                        except Exception:  # noqa: BLE001 - comando estranho não derruba o servidor
                            pass
        except Exception:  # noqa: BLE001 - conexão caiu
            pass
        finally:
            self.clients.discard(c)
