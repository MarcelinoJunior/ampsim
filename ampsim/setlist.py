"""Setlists: músicas do culto em ordem, cada uma com uma cópia completa do som do Pad/Piano.

Arquivo: %APPDATA%\\AmpSim\\setlists.json
    {"atual": "Culto de domingo", "recolhido": false,
     "listas": {"Culto de domingo": [{"nome": "Música 1", "som": {...}}, ...]}}

"som" = parte "som" do estado das teclas (sharing.sound_state), o tom do pad contínuo, o amp e
efeitos das teclas (trilha "pads") e o preset do usuário que estava aberto.
"""
import copy
import json

from . import storage

DEFAULT_LIST = "Meu setlist"
MAX_SONGS = 200


def path():
    return storage.APP_DIR / "setlists.json"


def empty():
    return {"atual": DEFAULT_LIST, "recolhido": False, "listas": {DEFAULT_LIST: []}}


def load():
    """Lê o arquivo; se faltar ou estiver estragado, começa com um setlist vazio."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict) or not isinstance(data.get("listas"), dict):
        return empty()
    out = empty()
    out["listas"] = {}
    for name, songs in data["listas"].items():
        if isinstance(name, str) and isinstance(songs, list):
            out["listas"][name[:60]] = [s for s in songs[:MAX_SONGS]
                                        if isinstance(s, dict) and isinstance(s.get("nome"), str)
                                        and isinstance(s.get("som"), dict)]
    if not out["listas"]:
        out["listas"] = {DEFAULT_LIST: []}
    atual = data.get("atual")
    out["atual"] = atual if atual in out["listas"] else next(iter(out["listas"]))
    out["recolhido"] = bool(data.get("recolhido", False))
    return out


def save(data):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def capture(win):
    """O som de agora, para guardar numa música."""
    from .sharing import sound_state
    inst = win.engine.instruments
    return {"instruments": copy.deepcopy(sound_state(inst.get_state())),
            "pad_tom": inst.cont_key,
            "pads_track": copy.deepcopy(win.track_pages["pads"].preset_data()),
            "user_preset": getattr(win.pad_view, "user_preset", "")}


def apply(win, som):
    """Carrega o som de uma música. O pad contínuo que estiver tocando passa para o tom da música."""
    from .sharing import sanitize_instruments
    inst = win.engine.instruments
    st = som.get("instruments")
    if isinstance(st, dict):
        inst.load_state(sanitize_instruments(st, inst.get_state()))
    pads = som.get("pads_track")
    if isinstance(pads, dict) and isinstance(pads.get("values"), dict):
        win.track_pages["pads"].apply_preset_data(pads)
    tom = som.get("pad_tom")
    if inst.cont_key is not None and isinstance(tom, str) and tom in _keys():
        inst.start_cont_pad(tom)
    win.pad_view.user_preset = som.get("user_preset", "") if isinstance(som.get("user_preset"), str) else ""


def _keys():
    from .instruments import KEY_NAMES
    return KEY_NAMES
