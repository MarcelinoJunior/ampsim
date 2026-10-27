"""Gravações nos pads: gravar um som (o que sai do AmpSim ou uma entrada da placa) e tocar de volta.

Recorder e Sampler trabalham dentro do callback de áudio: nada de alocar memória lá (o buffer da
gravação é criado no start, na thread da interface). O banco de gravações (arquivos WAV em
%APPDATA%\\AmpSim\\gravacoes) é lido e escrito só pela interface.
"""
import re
from collections import deque

import numpy as np

REC_PREFIX = "Gravação: "        # nome do som de pad que toca uma gravação ("Gravação: Grito")
MAX_SECONDS = 60
MAX_VOICES = 12
SILENCE = 10 ** (-48 / 20)       # abaixo disso é silêncio (corta no começo e no fim da gravação)


class Recorder:
    """Grava blocos estéreo. source: "out" (o que sai do AmpSim) ou o índice de uma entrada."""

    def __init__(self):
        self.buf = None
        self.pos = 0
        self.source = "out"
        self.active = False
        self.fs = 48000

    def start(self, fs, source="out"):
        self.fs = int(fs)
        self.buf = np.zeros((int(fs * MAX_SECONDS), 2), np.float32)
        self.pos = 0
        self.source = source
        self.active = True

    @property
    def seconds(self):
        return self.pos / self.fs if self.fs else 0.0

    @property
    def full(self):
        return self.buf is not None and self.pos >= len(self.buf)

    def feed(self, block):
        """block: (frames, 1 ou 2). Chamado pelo callback de áudio."""
        if not self.active or self.buf is None:
            return
        n = min(len(block), len(self.buf) - self.pos)
        if n <= 0:
            self.active = False                     # chegou no limite: para sozinho
            return
        dst = self.buf[self.pos:self.pos + n]
        if block.shape[1] >= 2:
            dst[:] = block[:n, :2]
        else:
            dst[:, 0] = block[:n, 0]
            dst[:, 1] = block[:n, 0]
        self.pos += n

    def stop(self):
        """Para e devolve o que foi gravado (cópia), já sem o silêncio do começo e do fim."""
        self.active = False
        data = self.buf[:self.pos].copy() if self.buf is not None else np.zeros((0, 2), np.float32)
        self.buf = None
        return trim(data, self.fs)


def trim(data, fs):
    """Tira o silêncio do começo (o pad toca na hora) e do fim; fade curto nas pontas (sem estalo)."""
    if len(data) == 0:
        return data
    loud = np.flatnonzero(np.abs(data).max(axis=1) > SILENCE)
    if len(loud) == 0:
        return data[:0]
    pre = int(0.003 * fs)
    a = max(0, loud[0] - pre)
    b = min(len(data), loud[-1] + int(0.05 * fs))
    out = data[a:b].copy()
    f = min(int(0.003 * fs), len(out) // 2)
    if f > 1:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)[:, None]
        out[:f] *= ramp
        out[-f:] *= ramp[::-1]
    return out


class Sampler:
    """Toca as gravações dos pads. samples: nome -> array (n, 2) na taxa do motor."""

    def __init__(self):
        self.fs = 48000
        self.raw = {}            # nome -> (array, taxa do arquivo)
        self.samples = {}        # nome -> array na taxa do motor (trocado inteiro, nunca editado)
        self.events = deque()    # (nome, velocidade, loop) vindos da interface ou do MIDI
        self.voices = []         # [array, posição, ganho, nome, loop]

    # ------------------------------------------------------------------ interface
    def set_fs(self, fs):
        self.fs = int(fs)
        self.samples = {name: _resample(a, sr, self.fs) for name, (a, sr) in self.raw.items()}

    def put(self, name, data, fs):
        self.raw[name] = (data, int(fs))
        samples = dict(self.samples)
        samples[name] = _resample(data, fs, self.fs)
        self.samples = samples

    def remove(self, name):
        self.raw.pop(name, None)
        samples = dict(self.samples)
        samples.pop(name, None)
        self.samples = samples

    def trigger(self, name, vel=110):
        self.events.append((name, vel, False))

    def loop(self, name, vel=110):
        """Toca `name` em loop até o STOP (stop_all). Se ele já está tocando (o 1º toque do duplo
        toque), essa mesma voz passa a repetir: nada recomeça nem dobra."""
        self.events.append((name, vel, True))

    @property
    def looping(self):
        """Nome da gravação que está em loop ("" se nenhuma). Lido pela interface."""
        for v in list(self.voices):
            if v[4]:
                return v[3]
        return ""

    # ------------------------------------------------------------------ tempo real
    def render(self, mix, frames, gain):
        q = self.events
        while q:
            item = q.popleft()
            if item is None:                         # STOP pedido pela interface
                self.voices = []
                continue
            name, vel, loop = item
            a = self.samples.get(name)
            if a is None or not len(a):
                continue
            if loop:
                # a voz mais nova desta gravação (o toque de agora há pouco) vira loop; um loop só por vez
                cur = None
                for v in self.voices:
                    v[4] = False
                    if v[0] is a:
                        cur = v
                if cur is not None:
                    cur[4] = True
                    continue
            if len(self.voices) >= MAX_VOICES:
                self.voices.pop(0)
            self.voices.append([a, 0, (vel / 127.0) ** 1.5, name, loop])
        if not self.voices:
            return
        keep = []
        for v in self.voices:
            a, pos, g = v[0], v[1], v[2]
            k = 0
            while k < frames:
                n = min(frames - k, len(a) - pos)
                if n > 0:
                    mix[k:k + n] += a[pos:pos + n] * (g * gain)
                    pos += n
                    k += n
                if pos >= len(a):
                    if not v[4]:
                        break
                    pos = 0                          # loop: volta ao começo sem buraco no bloco
            v[1] = pos
            if v[4] or pos < len(a):
                keep.append(v)
        self.voices = keep

    def stop_all(self):
        # a lista vazia vale já para a tela; o evento garante que o callback (que pode estar no meio
        # de um bloco com a lista antiga) também pare, inclusive um loop
        self.events.append(None)
        self.voices = []


def _resample(a, sr, fs):
    if sr == fs or len(a) == 0:
        return a.astype(np.float32, copy=False)
    from math import gcd

    from scipy.signal import resample_poly
    g = gcd(int(sr), int(fs))
    return resample_poly(a, fs // g, sr // g, axis=0).astype(np.float32)


# ---------------------------------------------------------------------- banco (pasta de WAVs)
def rec_dir():
    from .. import storage
    return storage.APP_DIR / "gravacoes"


def list_recordings():
    d = rec_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.wav"))


def clean_name(name):
    name = re.sub(r'[\\/:*?"<>|]+', " ", name).strip().strip(".")
    return name[:40]


def new_name():
    have = set(list_recordings())
    i = 1
    while f"Gravação {i:02d}" in have:
        i += 1
    return f"Gravação {i:02d}"


def save_recording(data, fs, name=None):
    """Salva (WAV float 32) e devolve o nome usado."""
    from scipy.io import wavfile
    d = rec_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = clean_name(name or "") or new_name()
    wavfile.write(str(d / f"{name}.wav"), int(fs), np.asarray(data, np.float32))
    return name


def load_recording(name):
    """(array (n, 2) float32, taxa) ou None se o arquivo sumiu/não abre."""
    from scipy.io import wavfile
    try:
        sr, a = wavfile.read(str(rec_dir() / f"{name}.wav"))
    except (OSError, ValueError):
        return None
    if a.dtype.kind == "i":
        a = a.astype(np.float32) / float(np.iinfo(a.dtype).max)
    a = np.asarray(a, np.float32)
    if a.ndim == 1:
        a = np.stack([a, a], axis=1)
    return a[:, :2].copy(), int(sr)


def rename_recording(old, new):
    new = clean_name(new)
    if not new or new == old or new in list_recordings():
        return None
    d = rec_dir()
    (d / f"{old}.wav").rename(d / f"{new}.wav")
    return new


def delete_recording(name):
    p = rec_dir() / f"{name}.wav"
    if p.exists():
        p.unlink()
