"""Timbres de SoundFont (.sf2) via FluidSynth (LGPL-2.1), carregado por ctypes.

O FluidSynth é usado só como "motor de vozes": nada de driver de áudio próprio. O AmpSim
chama fluid_synth_process() dentro do callback de áudio, então não há latência extra.

8 saídas estéreo (audio-groups = 8, grupo = canal % 8), cada uma com reverb e chorus próprios.
Com 16 grupos o FluidSynth gastava o dobro de CPU (16 reverbs/chorus por bloco) e o som picotava
em placas USB de teclado. O destino de cada grupo (camada 1-4 das teclas, pad contínuo, bateria)
fica em instruments.channel_routes(); kernels.mix_soundfont soma cada um no lugar certo.
"""
import ctypes as C
import glob
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SF2_DEFAULT = os.path.join(ROOT, "third_party", "soundfonts", "GeneralUser-GS.sf2")
DRUM_CHANNEL = 9
N_GROUPS = 8              # canal -> grupo = canal % 8: cada camada das teclas tem os próprios efeitos
N_OUT = 2 * N_GROUPS      # grupos estéreo
N_FX_GROUPS = N_GROUPS    # unidades de reverb/chorus (tem de ser igual: menos derruba o FluidSynth)
N_FX = 4 * N_FX_GROUPS    # unidades x (reverb, chorus) x estéreo


def _find_dll():
    for d in glob.glob(os.path.join(ROOT, "third_party", "fluidsynth", "*", "bin")):
        dll = os.path.join(d, "libfluidsynth-3.dll")
        if os.path.exists(dll):
            return d, dll
    return None, None


def available():
    return _find_dll()[1] is not None and os.path.exists(SF2_DEFAULT)


class SoundFontEngine:
    def __init__(self, fs, max_block, sf2_path=SF2_DEFAULT):
        bindir, dll = _find_dll()
        if dll is None:
            raise RuntimeError("FluidSynth não encontrado (rode tools/baixar_extras.py)")
        if not os.path.exists(sf2_path):
            raise RuntimeError("SoundFont não encontrado (rode tools/baixar_extras.py)")
        self._dll_dir = os.add_dll_directory(bindir)
        lib = C.CDLL(dll)
        self._bind(lib)
        self.lib = lib
        # o render roda no callback de áudio: PyDLL não solta o GIL durante a chamada (ver
        # kernels.JIT); noteon/cc vêm da UI e do MIDI e continuam pelo CDLL
        proc = C.PyDLL(dll).fluid_synth_process
        proc.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.c_int, C.c_void_p]
        proc.restype = C.c_int
        self._process = proc
        self.settings = lib.new_fluid_settings()
        for key, val in (("synth.sample-rate", float(fs)), ("synth.gain", 0.55)):
            lib.fluid_settings_setnum(self.settings, key.encode(), val)
        for key, val in (("synth.audio-channels", N_GROUPS), ("synth.audio-groups", N_GROUPS),
                         ("synth.effects-groups", N_FX_GROUPS), ("synth.polyphony", 256),
                         ("synth.cpu-cores", 1), ("synth.reverb.active", 1),
                         ("synth.chorus.active", 1)):
            lib.fluid_settings_setint(self.settings, key.encode(), val)
        self.synth = lib.new_fluid_synth(self.settings)
        if not self.synth:
            raise RuntimeError("Falha ao criar o sintetizador FluidSynth")
        self.sfont_id = lib.fluid_synth_sfload(self.synth, os.path.abspath(sf2_path).encode(), 1)
        if self.sfont_id < 0:
            raise RuntimeError(f"Falha ao carregar o SoundFont {sf2_path}")
        self.fs = float(fs)
        # buffers planares persistentes (o FluidSynth só soma neles)
        self.buf = np.zeros((N_OUT + N_FX, max_block), np.float32)
        self._out_ptrs = (C.POINTER(C.c_float) * N_OUT)(
            *[self.buf[i].ctypes.data_as(C.POINTER(C.c_float)) for i in range(N_OUT)])
        self._fx_ptrs = (C.POINTER(C.c_float) * N_FX)(
            *[self.buf[N_OUT + i].ctypes.data_as(C.POINTER(C.c_float)) for i in range(N_FX)])
        self._out_arg = C.cast(self._out_ptrs, C.c_void_p)
        self._fx_arg = C.cast(self._fx_ptrs, C.c_void_p)
        self.presets = self._list_presets()
        self.fonts = {}                  # pacote extra -> (id no FluidSynth, (banco, programa) do 1º preset)

    @staticmethod
    def _bind(lib):
        P, I, D, F = C.c_void_p, C.c_int, C.c_double, C.c_float
        sig = {
            "new_fluid_settings": ([], P),
            "new_fluid_synth": ([P], P),
            "delete_fluid_synth": ([P], None),
            "delete_fluid_settings": ([P], None),
            "fluid_settings_setnum": ([P, C.c_char_p, D], I),
            "fluid_settings_setint": ([P, C.c_char_p, I], I),
            "fluid_synth_sfload": ([P, C.c_char_p, I], I),
            "fluid_synth_get_sfont_by_id": ([P, I], P),
            "fluid_sfont_iteration_start": ([P], None),
            "fluid_sfont_iteration_next": ([P], P),
            "fluid_preset_get_name": ([P], C.c_char_p),
            "fluid_preset_get_banknum": ([P], I),
            "fluid_preset_get_num": ([P], I),
            "fluid_synth_program_select": ([P, I, I, I, I], I),
            "fluid_synth_noteon": ([P, I, I, I], I),
            "fluid_synth_noteoff": ([P, I, I], I),
            "fluid_synth_cc": ([P, I, I, I], I),
            "fluid_synth_pitch_bend": ([P, I, I], I),
            "fluid_synth_all_notes_off": ([P, I], I),
            "fluid_synth_all_sounds_off": ([P, I], I),
            "fluid_synth_set_gain": ([P, F], None),
            "fluid_synth_process": ([P, I, I, P, I, P], I),
        }
        for name, (args, res) in sig.items():
            fn = getattr(lib, name)
            fn.argtypes = args
            fn.restype = res

    def _list_presets(self, sfont_id=None):
        lib = self.lib
        sf = lib.fluid_synth_get_sfont_by_id(self.synth, self.sfont_id if sfont_id is None else sfont_id)
        lib.fluid_sfont_iteration_start(sf)
        out = {}
        while True:
            p = lib.fluid_sfont_iteration_next(sf)
            if not p:
                break
            out[(lib.fluid_preset_get_banknum(p), lib.fluid_preset_get_num(p))] = \
                lib.fluid_preset_get_name(p).decode("latin-1")
        return out

    # ------------------------------------------------------------------ controle (qualquer thread)
    def load_font(self, key, path):
        """Carrega um SoundFont extra (pacote de "Timbres adicionais"). -> True se carregou."""
        if key in self.fonts:
            return True
        i = self.lib.fluid_synth_sfload(self.synth, os.path.abspath(str(path)).encode(), 0)
        if i < 0:
            return False
        presets = self._list_presets(i)
        self.fonts[key] = (i, min(presets) if presets else (0, 0))
        return True

    def program(self, chan, bank, prog, font=""):
        """font = pacote extra: usa o 1º preset dele; pacote não instalado: o piano de cauda padrão."""
        if font:
            f = self.fonts.get(font)
            if f is None:
                return self.lib.fluid_synth_program_select(self.synth, chan, self.sfont_id, 0, 0) == 0
            i, (bank, prog) = f
            return self.lib.fluid_synth_program_select(self.synth, chan, i, bank, prog) == 0
        return self.lib.fluid_synth_program_select(self.synth, chan, self.sfont_id, bank, prog) == 0

    def noteon(self, chan, key, vel):
        if 0 <= key <= 127:
            self.lib.fluid_synth_noteon(self.synth, chan, key, max(1, min(127, vel)))

    def noteoff(self, chan, key):
        if 0 <= key <= 127:
            self.lib.fluid_synth_noteoff(self.synth, chan, key)

    def cc(self, chan, ctrl, val):
        self.lib.fluid_synth_cc(self.synth, chan, ctrl, max(0, min(127, int(val))))

    def pitch_bend(self, chan, val):
        self.lib.fluid_synth_pitch_bend(self.synth, chan, val)

    def all_off(self, chan=-1):
        chans = range(16) if chan < 0 else (chan,)
        for c in chans:
            self.lib.fluid_synth_all_notes_off(self.synth, c)

    def silence(self):
        for c in range(16):
            self.lib.fluid_synth_all_sounds_off(self.synth, c)

    # ------------------------------------------------------------------ áudio (thread de áudio)
    def render(self, n):
        """Gera n amostras em self.buf: linhas 2g, 2g+1 = grupo (canal) g seco (L, R);
        N_OUT + 4g .. N_OUT + 4g + 3 = reverb L, R e chorus L, R do grupo g."""
        self.buf[:, :n] = 0.0
        self._process(self.synth, n, N_FX, self._fx_arg, N_OUT, self._out_arg)

    def close(self):
        if self.synth:
            self.lib.delete_fluid_synth(self.synth)
            self.lib.delete_fluid_settings(self.settings)
            self.synth = None
