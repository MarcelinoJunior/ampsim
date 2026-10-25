"""Arquivos para compartilhar: cenas e presets (.ampsim) e o "código de texto" para colar em
WhatsApp, Instagram, grupos etc.

Formato (JSON, UTF-8):
    {"formato": "ampsim", "versao": 1, "tipo": "cena" | "preset",
     "trilha": "guitar" | "bass" | "pads" | "teclas",     (só em preset)
     "nome": "...", "autor": "...", "criado": "2026-10-25", "dados": {...}}

Tudo que vem de fora passa por `sanitize_*`: só chaves conhecidas, só números onde se espera
número, e nada de caminhos de arquivo de outro computador (plugin VST3, IR). Capturas NAM vão
só pelo nome e são procuradas nas pastas locais.
"""
import base64
import datetime
import json
import os
import zlib

from .dsp.padeq import DEFAULT_PAD_EQ, clean_pad_eq
from .dsp.synth import default_synth_values
from .dsp.track import default_values

FORMAT, VERSION = "ampsim", 1
TEXT_PREFIX = "AMPSIM1:"
EXTENSION = ".ampsim"
TRACK_KINDS = ("guitar", "bass", "pads")
KIND_TITLES = {"guitar": "Guitarra", "bass": "Baixo", "pads": "Pad/Piano (amp e efeitos)",
               "teclas": "Pad/Piano (timbres do teclado)"}
MAX_TEXT = 200_000                    # um preset tem poucos kB; recusa textos absurdos


class ShareError(ValueError):
    pass


# ------------------------------------------------------------------ documento
def make_doc(tipo, dados, nome="", autor="", trilha=None):
    doc = {"formato": FORMAT, "versao": VERSION, "tipo": tipo, "nome": nome, "autor": autor,
           "criado": datetime.date.today().isoformat(), "dados": dados}
    if trilha:
        doc["trilha"] = trilha
    return doc


def check_doc(doc):
    if not isinstance(doc, dict) or doc.get("formato") != FORMAT:
        raise ShareError("Não é um arquivo do AmpSim.")
    if not isinstance(doc.get("versao"), int) or doc["versao"] > VERSION:
        raise ShareError("Arquivo de uma versão mais nova do AmpSim. Atualize o programa.")
    if doc.get("tipo") not in ("cena", "preset") or not isinstance(doc.get("dados"), dict):
        raise ShareError("Arquivo incompleto ou corrompido.")
    if doc["tipo"] == "preset" and doc.get("trilha") not in TRACK_KINDS + ("teclas",):
        raise ShareError("Preset de tipo desconhecido.")
    for k in ("nome", "autor"):
        if not isinstance(doc.get(k, ""), str):
            doc[k] = ""
        doc[k] = doc.get(k, "")[:80]
    return doc


def save_file(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


def load_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(MAX_TEXT + 1)
    except OSError as exc:
        raise ShareError(f"Não foi possível abrir: {exc}") from exc
    if len(text) > MAX_TEXT:
        raise ShareError("Arquivo grande demais para um preset do AmpSim.")
    try:
        return check_doc(json.loads(text))
    except ValueError as exc:
        if isinstance(exc, ShareError):
            raise
        raise ShareError("O arquivo não é um JSON válido do AmpSim.") from exc


def to_text(doc):
    """Código compacto em uma linha (cabe em mensagem de WhatsApp/legenda)."""
    raw = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return TEXT_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii")


def from_text(text):
    text = "".join((text or "").split())          # mensagens quebram linhas e põem espaços
    i = text.find(TEXT_PREFIX)
    if i < 0:
        raise ShareError("Cole o código inteiro, começando por AMPSIM1:")
    code = text[i + len(TEXT_PREFIX):]
    if len(code) > MAX_TEXT:
        raise ShareError("Código grande demais.")
    try:
        raw = zlib.decompressobj().decompress(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)),
                                              MAX_TEXT * 4)
        return check_doc(json.loads(raw.decode("utf-8")))
    except ShareError:
        raise
    except (ValueError, zlib.error, UnicodeDecodeError) as exc:
        raise ShareError("Código incompleto ou corrompido (copie de novo, sem cortar o final).") from exc


# ------------------------------------------------------------------ limpeza do que vem de fora
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e7


def _same_kind(default, v):
    if isinstance(default, bool):
        return isinstance(v, bool)
    if isinstance(default, (int, float)):
        return _num(v)
    if isinstance(default, str):
        return isinstance(v, str) and len(v) <= 200
    return False


def sanitize_track(state):
    """Valores de trilha (amp + pedais). Remove caminhos de outro computador."""
    vals = default_values()
    out = {}
    src = state.get("values", {}) if isinstance(state, dict) else {}
    if not isinstance(src, dict):
        src = {}
    for eff, params in src.items():
        if eff not in vals or not isinstance(params, dict):
            continue
        clean = {}
        for k, v in params.items():
            if k in vals[eff] and _same_kind(vals[eff][k], v):
                clean[k] = v
        out[eff] = clean
    vst = out.get("vst", {})
    if not _local_plugin(vst.get("path", "")):      # plugin de outro PC: cada um escolhe o seu
        vst.pop("path", None)
        vst.pop("state", None)
    if "nam" in out and "file" in out["nam"]:
        out["nam"]["file"] = out["nam"]["file"].replace("/", "").replace("\\", "")[:120]
    ir = state.get("ir_path") if isinstance(state, dict) else None
    ir = ir if isinstance(ir, str) and ir.lower().endswith(".wav") and os.path.isfile(ir) else None
    return {"values": out, "ir_path": ir}


def _local_plugin(path):
    """Só aceita plugin que já está instalado nas pastas padrão de VST3 deste computador."""
    if not path or not os.path.exists(path):
        return False
    roots = [os.path.join(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files"), "VST3"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Common", "VST3")]
    real = os.path.normcase(os.path.realpath(path))
    return any(real.startswith(os.path.normcase(os.path.realpath(r)) + os.sep) for r in roots if r)


def sanitize_synth(values):
    base = default_synth_values()
    if not isinstance(values, dict):
        return {}
    return {k: v for k, v in values.items() if k in base and _same_kind(base[k], v)}


SOUND_STATE_KEYS = ("keys", "ready", "pad_preset", "pad_sounds", "pad_keys", "cont_sound",
                    "levels", "fx", "pad_eq", "bpm")


def sound_state(inst_state):
    """Parte do estado das teclas que é "som" (sem mapeamento de controlador nem aparelho)."""
    return {k: inst_state[k] for k in SOUND_STATE_KEYS if k in inst_state}


def sanitize_instruments(st, current):
    """Estado das teclas/pads vindo de fora, conferido contra o estado atual (`current`)."""
    if not isinstance(st, dict):
        return {}
    out = {}
    for k in ("ready", "pad_preset", "cont_sound"):
        if isinstance(st.get(k), str) and len(st[k]) <= 120:
            out[k] = st[k]
    for k in ("keys", "levels", "fx"):
        src, ref = st.get(k), current.get(k, {})
        if isinstance(src, dict):
            out[k] = {kk: v for kk, v in src.items() if kk in ref and _same_kind(ref[kk], v)}
    if "levels" in out:
        out["levels"] = {k: max(0, min(127, v)) for k, v in out["levels"].items()}
    for k in ("pad_sounds", "pad_keys"):
        src = st.get(k)
        if isinstance(src, list) and len(src) == len(current.get(k, [])) and all(
                isinstance(x, str) and len(x) <= 120 for x in src):
            out[k] = list(src)
    if isinstance(st.get("pad_eq"), dict):
        out["pad_eq"] = dict(DEFAULT_PAD_EQ, **clean_pad_eq(st["pad_eq"]))
    if _num(st.get("bpm")):
        out["bpm"] = int(max(30, min(300, st["bpm"])))
    return out


def sanitize_scene(d, inst_current):
    out = {"tracks": {}}
    tracks = d.get("tracks", {})
    if isinstance(tracks, dict):
        for name in TRACK_KINDS:
            if isinstance(tracks.get(name), dict):
                out["tracks"][name] = sanitize_track(tracks[name])
    out["synth"] = sanitize_synth(d.get("synth"))
    out["instruments"] = sanitize_instruments(d.get("instruments"), inst_current)
    if _num(d.get("master_db")):
        out["master_db"] = float(max(-40.0, min(6.0, d["master_db"])))
    return out
