"""Entrada MIDI nativa do Windows (winmm) via ctypes — sem dependências extras.

O callback do winmm roda numa thread do sistema; repassamos as mensagens já
decodificadas para `on_message(status, data1, data2)`.
"""
import ctypes
import sys
from ctypes import wintypes

MIM_DATA = 0x3C3
CALLBACK_FUNCTION = 0x00030000
MAXPNAMELEN = 32


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("dwSupport", wintypes.DWORD),
    ]


MidiInProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t,
                                ctypes.c_size_t, ctypes.c_size_t)

available = sys.platform == "win32"
if available:
    _winmm = ctypes.WinDLL("winmm")
    _winmm.midiInGetNumDevs.restype = wintypes.UINT
    _winmm.midiInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIINCAPSW), wintypes.UINT]
    _winmm.midiInOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.UINT, MidiInProc,
                                  ctypes.c_size_t, wintypes.DWORD]
    _winmm.midiInStart.argtypes = [wintypes.HANDLE]
    _winmm.midiInStop.argtypes = [wintypes.HANDLE]
    _winmm.midiInReset.argtypes = [wintypes.HANDLE]
    _winmm.midiInClose.argtypes = [wintypes.HANDLE]


def list_inputs():
    if not available:
        return []
    names = []
    for i in range(_winmm.midiInGetNumDevs()):
        caps = MIDIINCAPSW()
        if _winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


class MidiInput:
    def __init__(self, on_message):
        self.on_message = on_message
        self.handle = None
        self.name = None
        self._proc = MidiInProc(self._callback)    # manter referência viva!

    def open(self, name):
        self.close()
        names = list_inputs()
        if name not in names:
            raise RuntimeError(f"Dispositivo MIDI não encontrado: {name}")
        h = wintypes.HANDLE()
        err = _winmm.midiInOpen(ctypes.byref(h), names.index(name), self._proc, 0, CALLBACK_FUNCTION)
        if err != 0:
            raise RuntimeError(f"midiInOpen falhou (erro {err}) — o dispositivo pode estar em uso")
        _winmm.midiInStart(h)
        self.handle = h
        self.name = name

    def close(self):
        if self.handle is not None:
            _winmm.midiInStop(self.handle)
            _winmm.midiInReset(self.handle)
            _winmm.midiInClose(self.handle)
            self.handle = None
            self.name = None

    def _callback(self, handle, msg, instance, param1, param2):
        if msg != MIM_DATA:
            return
        status = param1 & 0xFF
        if status >= 0xF0:            # clock/active sensing/sysex: ignora
            return
        self.on_message(status, (param1 >> 8) & 0x7F, (param1 >> 16) & 0x7F)
