"""Arquivos para compartilhar: cenas e presets (.ampsim) e o "código de texto" para colar em
WhatsApp, Instagram, grupos etc.

Formato (JSON, UTF-8):
    {"formato": "ampsim", "versao": 1, "tipo": "cena" | "preset",
     "trilha": "guitar" | "bass" | "pads" | "vocal" | "teclas",     (só em preset)
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

from .audio.vst import clean_chain, clean_plugin, is_local, portable_ref, resolve_ref, valid_state
from .dsp.padeq import DEFAULT_PAD_EQ, clean_pad_eq
from .dsp.synth import default_synth_values
from .dsp.track import default_values
from .dsp.vocal import clean_values as clean_vocal_values

FORMAT, VERSION = "ampsim", 1
TEXT_PREFIX = "AMPSIM1:"
EXTENSION = ".ampsim"
TRACK_KINDS = ("guitar", "bass", "pads", "vocal")
KIND_TITLES = {"guitar": "Guitarra", "bass": "Baixo", "pads": "Pad/Piano (amp e efeitos)",
               "vocal": "Vocal (microfone)", "teclas": "Pad/Piano (timbres do teclado)"}
MAX_TEXT = 200_000                    # um preset tem poucos kB; recusa textos absurdos
PLUGIN_STATE_MAX = 150_000            # estado de plugin (base64) num arquivo compartilhado


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
    vst = out.setdefault("vst", {})
    raw = src.get("vst", {}) if isinstance(src.get("vst"), dict) else {}
    if isinstance(raw.get("path"), str) and len(raw["path"]) <= 1024:
        vst["path"] = raw["path"]                    # "vst3:…" ou caminho completo (pode passar de 200 letras)
    if not _local_plugin(vst.get("path", "")):      # plugin de outro PC: cada um escolhe o seu
        vst.pop("path", None)
        vst.pop("state", None)
    else:                                            # plugin deste PC: o estado (base64) costuma ter > 200 letras
        vst["path"] = _portable(vst["path"])
        st = raw.get("state", "")
        if valid_state(st, PLUGIN_STATE_MAX):
            vst["state"] = st
    if "nam" in out and "file" in out["nam"]:
        out["nam"]["file"] = out["nam"]["file"].replace("/", "").replace("\\", "")[:120]
    ir = state.get("ir_path") if isinstance(state, dict) else None
    ir = ir if isinstance(ir, str) and ir.lower().endswith(".wav") and os.path.isfile(ir) else None
    return {"values": out, "ir_path": ir, "fx_chain": sanitize_chain(state.get("fx_chain") if isinstance(state, dict)
                                                                      else None)}


def sanitize_vocal(state):
    """Trilha Vocal vinda de fora (preset, cena): faixas e tipos conferidos (dsp/vocal.clean_values), só
    plugins deste PC. Liga/desliga e mudo da trilha não vêm de fora: abrir um arquivo nunca liga o
    microfone de ninguém (quem aplica mantém os atuais)."""
    src = state.get("values", {}) if isinstance(state, dict) else {}
    vals = clean_vocal_values(src)
    for k in ("on", "mute"):
        vals["track"].pop(k, None)
    return {"values": vals, "fx_chain": sanitize_chain(state.get("fx_chain") if isinstance(state, dict)
                                                         else None)}


def sanitize_kind(kind, state):
    """sanitize_track ou sanitize_vocal, conforme a trilha."""
    return sanitize_vocal(state) if kind == "vocal" else sanitize_track(state)


def _local_plugin(path):
    """Só aceita plugin que já está instalado neste computador: nas pastas padrão de VST3 (do sistema
    ou do usuário) ou um que a pessoa já escolheu aqui em "Procurar arquivo…" (audio/vst.is_local)."""
    return is_local(path)


def _portable(path):
    """Plugin das pastas padrão vai como "vst3:Nome.vst3" (abre no PC de quem tiver o mesmo plugin)."""
    return portable_ref(resolve_ref(path))


def sanitize_plugin(d):
    """Um plugin vindo de fora: plugin de outro PC (fora das pastas padrão) não vem (slot vazio)."""
    out = clean_plugin(d, PLUGIN_STATE_MAX)
    if not _local_plugin(out["path"]):
        out.update(path="", state="", on=False)
    else:
        out["path"] = _portable(out["path"])
    return out


def sanitize_chain(v):
    """Cadeia FX vinda de fora (lista de plugins ou o formato antigo de 1): só os plugins deste PC."""
    return [d for d in (sanitize_plugin(x) for x in clean_chain(v, PLUGIN_STATE_MAX)) if d["path"]]


def sanitize_synth(values):
    base = default_synth_values()
    if not isinstance(values, dict):
        return {}
    return {k: v for k, v in values.items() if k in base and _same_kind(base[k], v)}


SOUND_STATE_KEYS = ("keys", "ready", "pad_preset", "pad_sounds", "pad_keys", "cont_sound",
                    "levels", "fx", "layer_fx", "extra_layers", "pad_eq", "bpm", "layer_chains")
# a FX do Master (como o Compressor) é da saída: fica só na sessão (Instruments.get_state)
# níveis da saída (como o master): ficam na sessão, mas presets, cenas e músicas não levam nem mudam
OUTPUT_LEVELS = ("comp",)


def sound_state(inst_state):
    """Parte do estado das teclas que é "som" (sem mapeamento de controlador nem aparelho)."""
    out = {k: inst_state[k] for k in SOUND_STATE_KEYS if k in inst_state}
    if isinstance(out.get("levels"), dict):
        out["levels"] = {k: v for k, v in out["levels"].items() if k not in OUTPUT_LEVELS}
    return out


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
        out["levels"] = {k: max(0, min(127, v)) for k, v in out["levels"].items() if k not in OUTPUT_LEVELS}
    for k in ("pad_sounds", "pad_keys"):
        src = st.get(k)
        if isinstance(src, list) and len(src) == len(current.get(k, [])) and all(
                isinstance(x, str) and len(x) <= 120 for x in src):
            out[k] = list(src)
    if isinstance(st.get("pad_eq"), dict):
        out["pad_eq"] = dict(DEFAULT_PAD_EQ, **clean_pad_eq(st["pad_eq"]))
    from .instruments import MAX_LAYERS, clean_fx, clean_layer

    if isinstance(st.get("layer_fx"), list):
        out["layer_fx"] = [clean_fx(d) if isinstance(d, dict) else {} for d in st["layer_fx"][:MAX_LAYERS]]
    if isinstance(st.get("extra_layers"), list):
        out["extra_layers"] = [x for x in (clean_layer(d) for d in st["extra_layers"][:MAX_LAYERS - 2]) if x]
    elif "keys" in out:
        out["extra_layers"] = []        # timbre sem camadas extras: tira as que estavam
    src = st.get("layer_chains")
    if not isinstance(src, list):
        src = st.get("layer_plugins")    # formato de 1 plugin por camada
    if isinstance(src, list):
        src = src[:MAX_LAYERS]
        out["layer_chains"] = [sanitize_chain(src[k] if k < len(src) else []) for k in range(MAX_LAYERS)]
    elif "keys" in out:
        out["layer_chains"] = []        # timbre salvo antes dos plugins: camadas sem plugin
    if _num(st.get("bpm")):
        out["bpm"] = int(max(30, min(300, st["bpm"])))
    return out


def sanitize_scene(d, inst_current):
    out = {"tracks": {}}
    tracks = d.get("tracks", {})
    if isinstance(tracks, dict):
        for name in TRACK_KINDS:
            if isinstance(tracks.get(name), dict):
                out["tracks"][name] = sanitize_kind(name, tracks[name])
    out["synth"] = sanitize_synth(d.get("synth"))
    out["instruments"] = sanitize_instruments(d.get("instruments"), inst_current)
    if _num(d.get("master_db")):
        out["master_db"] = float(max(-40.0, min(6.0, d["master_db"])))
    return out
