"""Hospedagem de plugins VST3 (via pedalboard, da Spotify) na cadeia de uma trilha."""
import base64
import os

import numpy as np

try:
    import pedalboard
except ImportError:          # dependência opcional
    pedalboard = None

SYSTEM_VST3_DIR = r"C:\Program Files\Common Files\VST3"


def available():
    return pedalboard is not None


def find_plugins():
    """Plugins .vst3 instalados na pasta padrão do Windows."""
    if not os.path.isdir(SYSTEM_VST3_DIR):
        return []
    return sorted(os.path.join(SYSTEM_VST3_DIR, f) for f in os.listdir(SYSTEM_VST3_DIR)
                  if f.lower().endswith(".vst3"))


def resolve_binary(path):
    """Um .vst3 no Windows costuma ser uma pasta (pacote); o pedalboard às vezes só consegue
    ler o binário de dentro dela (Contents/x86_64-win/*.vst3)."""
    if os.path.isdir(path):
        inner = os.path.join(path, "Contents", "x86_64-win")
        if os.path.isdir(inner):
            for f in sorted(os.listdir(inner)):
                if f.lower().endswith(".vst3"):
                    return os.path.join(inner, f)
    return path


class VstSlot:
    def __init__(self, path, fs, max_block):
        if pedalboard is None:
            raise RuntimeError("Pacote 'pedalboard' não instalado (pip install pedalboard)")
        try:
            plugin = pedalboard.load_plugin(path)
        except ImportError:
            binary = resolve_binary(path)
            if binary == path:
                raise
            plugin = pedalboard.load_plugin(binary)
        if not getattr(plugin, "is_effect", True):
            raise RuntimeError("Esse plugin é um instrumento, não um efeito de áudio")
        self.plugin = plugin
        self.path = path
        self.name = getattr(plugin, "name", "") or os.path.splitext(os.path.basename(path))[0]
        self.fs = float(fs)
        self.error = None
        # descobre se o plugin aceita mono; senão manda o sinal duplicado em estéreo
        self.channels = 1
        for ch in (1, 2):
            try:
                plugin.process(np.zeros((ch, 64), np.float32), self.fs, buffer_size=64, reset=True)
                self.channels = ch
                break
            except Exception:  # noqa: BLE001 - erros vêm do plugin
                continue
        self.buf = np.zeros((self.channels, max_block), np.float32)

    def process(self, x, n, mix):
        """Thread de áudio. Em caso de erro, desativa o slot em vez de derrubar o stream."""
        if self.error:
            return
        b = self.buf[:, :n]
        b[:] = x[:n]
        try:
            out = self.plugin.process(b, self.fs, buffer_size=n, reset=False)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return
        y = out[0] if out.shape[0] == 1 else out.mean(axis=0)
        m = min(len(y), n)
        if mix >= 1.0:
            x[:m] = y[:m]
        else:
            x[:m] = x[:m] * (1.0 - mix) + y[:m] * mix

    def get_state(self):
        try:
            return base64.b64encode(self.plugin.raw_state).decode("ascii")
        except Exception:  # noqa: BLE001
            return ""

    def set_state(self, b64):
        if b64:
            self.plugin.raw_state = base64.b64decode(b64)

    def show_editor(self):
        """Bloqueia a janela principal até o editor do plugin ser fechado (o áudio continua)."""
        self.plugin.show_editor()
