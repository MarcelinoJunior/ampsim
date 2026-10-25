"""Persistência: estado da sessão e presets do usuário em %APPDATA%\\AmpSim."""
import json
import os
import re
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "AmpSim"
STATE_FILE = APP_DIR / "state.json"
PRESET_DIR = APP_DIR / "presets"
# cenas e presets para compartilhar: numa pasta fácil de achar (Documentos\AmpSim)
SHARE_DIR = Path.home() / "Documents" / "AmpSim"


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_state():
    return _read(STATE_FILE) or {}


def save_state(data):
    _write(STATE_FILE, data)


def _safe(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "preset"


def list_user_presets(kind):
    d = PRESET_DIR / kind
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_user_preset(kind, name):
    return _read(PRESET_DIR / kind / f"{_safe(name)}.json")


def save_user_preset(kind, name, data):
    _write(PRESET_DIR / kind / f"{_safe(name)}.json", data)


def delete_user_preset(kind, name):
    p = PRESET_DIR / kind / f"{_safe(name)}.json"
    if p.exists():
        p.unlink()
