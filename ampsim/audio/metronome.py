"""Metrônomo (click) no BPM do AmpSim: primeiro tempo do compasso mais agudo (acento).

Roda dentro do callback de áudio sem alocar memória: as batidas de cada bloco são calculadas e a
forma de onda curta do click é somada no buffer (o pedaço que passa do bloco continua no próximo).
"""
import numpy as np

CLICK_MS = 28.0
FREQ_ACCENT, FREQ_BEAT = 1760.0, 1100.0


def _wave(fs, freq, gain):
    n = int(fs * CLICK_MS / 1000.0)
    t = np.arange(n) / fs
    env = np.exp(-t / 0.006) * np.minimum(1.0, t / 0.0005)     # ataque de 0,5 ms (sem estalo) e queda curta
    return (gain * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class Metronome:
    def __init__(self, fs, max_block):
        self.set_fs(fs, max_block)
        self.on = False
        self.volume = 0.6          # 0-1
        self.beats = 4             # tempos por compasso (1 = sem acento)
        self.beat = 0              # tempo atual do compasso (0 = acento), para a tela piscar
        self.count = 0             # batidas tocadas desde que ligou

    def set_fs(self, fs, max_block):
        self.fs = float(fs)
        self.waves = (_wave(fs, FREQ_ACCENT, 0.9), _wave(fs, FREQ_BEAT, 0.6))
        self.buf = np.zeros(max_block, np.float32)
        self.restart()

    def restart(self):
        """Próxima batida agora (tap tempo, ligar o click)."""
        self._until = 0.0          # amostras até a próxima batida
        self._tail = None          # (onda, posição) do click que passou do bloco anterior
        self._next_beat = 0

    def render(self, frames, bpm):
        """Preenche self.buf[:frames] com o click (mono) e devolve True se tocou algo."""
        buf = self.buf
        buf[:frames] = 0.0
        if not self.on:
            self._tail = None
            return False
        played = False
        if self._tail is not None:
            w, pos = self._tail
            n = min(frames, len(w) - pos)
            buf[:n] += w[pos:pos + n]
            self._tail = (w, pos + n) if pos + n < len(w) else None
            played = True
        spb = 60.0 / max(bpm, 20.0) * self.fs
        t = self._until
        while t < frames:
            i = int(t)
            accent = self.beats > 1 and self._next_beat == 0
            w = self.waves[0 if accent else 1]
            n = min(frames - i, len(w))
            buf[i:i + n] += w[:n]
            self._tail = (w, n) if n < len(w) else None
            self.beat = self._next_beat
            self._next_beat = (self._next_beat + 1) % max(self.beats, 1)
            self.count += 1
            played = True
            t += spb
        self._until = t - frames
        if played:
            buf[:frames] *= self.volume
        return played
