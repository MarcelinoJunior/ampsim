"""Configuração da tela remota: liga/desliga, porta, login e o que cada perfil vê.

Arquivo %APPDATA%\\AmpSim\\webserver.json. As senhas ficam só como hash PBKDF2 (com sal).
"""
import hashlib
import hmac
import json
import os

from .. import storage

# telas da página remota (a ordem é a da página)
PANELS = (
    ("pads", "Pads (contínuo e bateria)"),
    ("faders", "Faders e mute"),
    ("setlist", "Setlist"),
    ("timbre", "Timbre atual e presets"),
    ("guitarra", "Guitarra (presets, pedais e volume)"),
    ("baixo", "Baixo (presets, pedais e volume)"),
)
PANEL_IDS = tuple(p for p, _ in PANELS)
DEFAULT_PORT = 8080
ITER = 120_000


def path():
    return storage.APP_DIR / "webserver.json"


def default():
    return {"ligado": False, "porta": DEFAULT_PORT, "login": False,
            "aberto": list(PANEL_IDS),            # o que vê quem entra sem login (login desligado)
            "usuarios": []}                        # [{"nome", "sal", "hash", "telas": [...]}]


# todas as telas da 1.1 (antes de Guitarra/Baixo; Tempo e Mute saíram): quem via tudo continua vendo tudo
OLD_ALL = {"pads", "faders", "setlist", "tempo", "emergencia", "timbre"}


def clean_panels(v):
    """Telas válidas, na ordem da página. Quem via todas as telas antigas continua vendo tudo; um perfil
    restrito continua restrito (só Tempo/Mute, que saíram, vira nenhuma tela: o PC mostra "nenhuma tela")."""
    if not isinstance(v, list):
        return []
    old = set(x for x in v if isinstance(x, str))
    if OLD_ALL <= old:
        return list(PANEL_IDS)
    return [p for p in PANEL_IDS if p in old]


def load():
    try:
        d = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default()
    out = default()
    if not isinstance(d, dict):
        return out
    out["ligado"] = bool(d.get("ligado", False))
    port = d.get("porta")
    out["porta"] = port if isinstance(port, int) and 1024 <= port <= 65535 else DEFAULT_PORT
    out["login"] = bool(d.get("login", False))
    if isinstance(d.get("aberto"), list):
        out["aberto"] = clean_panels(d["aberto"])
    users = []
    for u in d.get("usuarios", []) if isinstance(d.get("usuarios"), list) else []:
        if isinstance(u, dict) and isinstance(u.get("nome"), str) and isinstance(u.get("hash"), str) \
                and isinstance(u.get("sal"), str) and u["nome"].strip():
            users.append({"nome": u["nome"].strip()[:40], "sal": u["sal"], "hash": u["hash"],
                          "telas": clean_panels(u.get("telas", []))})
    out["usuarios"] = users
    return out


def save(cfg):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), ITER).hex()


def set_user(cfg, name, password, panels):
    """Cria ou altera um usuário (senha vazia ao alterar = mantém a atual)."""
    name = name.strip()[:40]
    if not name:
        raise ValueError("Nome vazio")
    user = next((u for u in cfg["usuarios"] if u["nome"].lower() == name.lower()), None)
    if user is None:
        if not password:
            raise ValueError("Usuário novo precisa de senha")
        user = {"nome": name}
        cfg["usuarios"].append(user)
    if password:
        salt = os.urandom(16).hex()
        user["sal"], user["hash"] = salt, _hash(password, salt)
    user["telas"] = clean_panels(panels)
    return user


def remove_user(cfg, name):
    cfg["usuarios"] = [u for u in cfg["usuarios"] if u["nome"].lower() != name.lower()]


def check(cfg, name, password):
    """-> telas liberadas para o usuário, ou None se nome/senha não conferem."""
    for u in cfg["usuarios"]:
        if u["nome"].lower() == (name or "").strip().lower():
            if hmac.compare_digest(u["hash"], _hash(password or "", u["sal"])):
                return list(u["telas"])
            return None
    _hash(password or "", "00" * 16)              # mesmo tempo com nome inexistente
    return None
