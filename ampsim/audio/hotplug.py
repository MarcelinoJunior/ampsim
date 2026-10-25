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
