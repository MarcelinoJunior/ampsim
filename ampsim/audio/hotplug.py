"""Aparelhos conectados com o app aberto (ex.: o teclado M-VAVE com interface de áudio própria).

A lista vem do winmm (saídas de áudio e entradas MIDI do Windows): é uma consulta leve, que não
mexe no PortAudio nem no stream que está tocando. O nome do winmm é cortado em 31 letras, por
isso `match_output` compara por pedaço do nome com os dispositivos do PortAudio.
"""
import ctypes
import sys

from ..midi import winmm


class _WAVEOUTCAPSW(ctypes.Structure):
    _fields_ = [("wMid", ctypes.c_ushort), ("wPid", ctypes.c_ushort), ("vDriverVersion", ctypes.c_uint),
                ("szPname", ctypes.c_wchar * 32), ("dwFormats", ctypes.c_uint), ("wChannels", ctypes.c_ushort),
                ("wReserved1", ctypes.c_ushort), ("dwSupport", ctypes.c_uint)]


def audio_outputs():
    """Nomes das saídas de áudio que o Windows enxerga agora."""
    if sys.platform != "win32":
        return []
    try:
        lib = ctypes.windll.winmm
        names = []
        for i in range(lib.waveOutGetNumDevs()):
            caps = _WAVEOUTCAPSW()
            if lib.waveOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                names.append(caps.szPname)
        return names
    except OSError:
        return []


def midi_inputs():
    return winmm.list_inputs()


# palavras que aparecem no nome do aparelho no Windows (o nome exato depende do driver/firmware;
# a pergunta de "aparelho conectado" vale para qualquer placa, mesmo sem estar nesta lista)
INSTRUMENTS = {
    "M-VAVE SMK-25": ("m-vave", "mvave", "smk-25", "smk25"),
    "Yamaha PSR-E473": ("psr-e473", "psr e473", "psr-e", "yamaha", "digital keyboard"),
    "Roland VR-730": ("vr-730", "vr730", "v-combo", "roland"),
}


def instrument_of(name):
    """Modelo conhecido pelo nome do aparelho de áudio, ou None."""
    low = name.lower()
    for model, words in INSTRUMENTS.items():
        if any(w in low for w in words):
            return model
    return None


# a entrada USB destes aparelhos é o som do próprio teclado; com "Audio Loop Back" (o PSR vem com
# ele ligado) volta também o que o PC manda. Como guitarra/baixo isso vira microfonia.
KEYBOARD_AUDIO = ("psr-e", "digital keyboard", "m-vave", "smk-25", "smk25", "vr-730", "vr730", "v-combo")


def is_keyboard_audio(name, wdm_names=None):
    """A entrada `name` é o áudio de um teclado (e não de uma guitarra/microfone)?"""
    low = name.lower()
    if any(w in low for w in KEYBOARD_AUDIO):
        return True
    if "yamaha steinberg usb" in low:
        # o mesmo driver serve o PSR e as interfaces Steinberg UR: decide por quem está conectado
        names = [n.lower() for n in (audio_outputs() if wdm_names is None else wdm_names)]
        return (any(w in n for n in names for w in KEYBOARD_AUDIO)
                and not any("steinberg" in n for n in names))
    return False


def find_instrument_output(names, prefer=None):
    """(modelo, nome) da saída de um instrumento conhecido; dá preferência ao modelo `prefer`."""
    found = [(instrument_of(n), n) for n in names]
    found = [(m, n) for m, n in found if m]
    for m, n in found:
        if m == prefer:
            return m, n
    return found[0] if found else (None, None)


def match_output(short_name, candidates):
    """Nome (cortado) do winmm -> nome completo do PortAudio, ou None."""
    s = short_name.strip().lower()
    if not s:
        return None
    for c in candidates:
        if c.lower() == s:
            return c
    for c in candidates:
        if s in c.lower() or c.lower().startswith(s):
            return c
    return None


class DeviceWatcher:
    """Compara a lista atual com a anterior. A primeira leitura só guarda (não avisa nada)."""

    def __init__(self, outputs=audio_outputs, midis=midi_inputs):
        self._outputs_fn = outputs
        self._midis_fn = midis
        self._outs = None
        self._midis = None

    def poll(self):
        """-> (saídas novas, entradas MIDI novas)"""
        outs, midis = list(self._outputs_fn()), list(self._midis_fn())
        if self._outs is None:
            self._outs, self._midis = outs, midis
            return [], []
        new_outs = [o for o in outs if o not in self._outs]
        new_midis = [m for m in midis if m not in self._midis]
        self._outs, self._midis = outs, midis
        return new_outs, new_midis
