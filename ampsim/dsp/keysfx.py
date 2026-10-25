"""Efeitos das teclas (saída estéreo do FluidSynth): Drive -> Rotação (Leslie) -> Delay.

Rodam no callback de áudio, em Numba, sem alocação.
"""
import math

import numpy as np
from numba import njit

JIT = dict(cache=True, fastmath=True, nogil=False, error_model="numpy")   # ver kernels.JIT
TWO_PI = 2.0 * math.pi

# parâmetros (KP)
K_DRV_ON, K_DRV, K_ROT_ON, K_ROT_FAST, K_ROT_MIX, K_DL_ON, K_DL_TIME, K_DL_FB, K_DL_MIX, \
    K_DL_DAMP, K_DL_PING = range(11)
KP_SIZE = 16
# estado (KS)
S_HSPD, S_DSPD, S_HPH, S_DPH, S_XLP, S_RPOS, S_DPOS, S_DLPL, S_DLPR = range(9)
KS_SIZE = 16
ROT_BUF = 2048            # buffer do Doppler da corneta (potência de 2)
HORN_SLOW, HORN_FAST = 0.8, 6.8      # Hz
DRUM_SLOW, DRUM_FAST = 0.7, 5.9


@njit(**JIT)
def process_keys_fx(KB, n, KP, KS, DB, RB, fs):
    """KB: [n, 2] estéreo, processado no lugar."""
    inv = 1.0 / fs
    # ---------------------------------------------------------------- drive
    if KP[K_DRV_ON] > 0.5 and KP[K_DRV] > 0.0:
        g = 1.0 + KP[K_DRV] * 14.0
        comp = 1.0 / math.sqrt(g)
        for i in range(n):
            KB[i, 0] = math.tanh(KB[i, 0] * g) * comp
            KB[i, 1] = math.tanh(KB[i, 1] * g) * comp
    # ---------------------------------------------------------------- rotação (Leslie)
    if KP[K_ROT_ON] > 0.5:
        fast = KP[K_ROT_FAST] > 0.5
        h_tgt = HORN_FAST if fast else HORN_SLOW
        d_tgt = DRUM_FAST if fast else DRUM_SLOW
        h_acc = 1.0 - math.exp(-inv / 0.9)        # corneta acelera em ~1 s
        d_acc = 1.0 - math.exp(-inv / 3.0)        # tambor é mais pesado (~3 s)
        xc = 1.0 - math.exp(-TWO_PI * 800.0 * inv)
        mix = KP[K_ROT_MIX]
        hs = KS[S_HSPD]
        ds = KS[S_DSPD]
        hph = KS[S_HPH]
        dph = KS[S_DPH]
        xlp = KS[S_XLP]
        pos = int(KS[S_RPOS])
        mask = ROT_BUF - 1
        base = 0.0012 * fs
        depth = 0.00045 * fs
        for i in range(n):
            hs += (h_tgt - hs) * h_acc
            ds += (d_tgt - ds) * d_acc
            hph += hs * inv
            if hph >= 1.0:
                hph -= 1.0
            dph += ds * inv
            if dph >= 1.0:
                dph -= 1.0
            x = (KB[i, 0] + KB[i, 1]) * 0.5
            xlp += (x - xlp) * xc
            hi = x - xlp
            RB[pos] = hi
            sh = math.sin(TWO_PI * hph)
            ch = math.cos(TWO_PI * hph)
            # dois "microfones" em lados opostos: Doppler e volume em fases contrárias
            dl = base + depth * sh
            dr = base - depth * sh
            fl = pos - dl
            il = int(math.floor(fl))
            fr_ = fl - il
            hl = RB[il & mask] * (1.0 - fr_) + RB[(il + 1) & mask] * fr_
            fl = pos - dr
            il = int(math.floor(fl))
            fr_ = fl - il
            hr = RB[il & mask] * (1.0 - fr_) + RB[(il + 1) & mask] * fr_
            hl *= 0.7 + 0.3 * ch
            hr *= 0.7 - 0.3 * ch
            sd = math.sin(TWO_PI * dph)
            lo_l = xlp * (0.85 + 0.15 * sd)
            lo_r = xlp * (0.85 - 0.15 * sd)
            KB[i, 0] = KB[i, 0] * (1.0 - mix) + (hl + lo_l) * mix
            KB[i, 1] = KB[i, 1] * (1.0 - mix) + (hr + lo_r) * mix
            pos = (pos + 1) & mask
        KS[S_HSPD] = hs
        KS[S_DSPD] = ds
        KS[S_HPH] = hph
        KS[S_DPH] = dph
        KS[S_XLP] = xlp if abs(xlp) > 1e-15 else 0.0
        KS[S_RPOS] = pos
    else:
        # parado: o rotor mantém a velocidade lenta para religar sem "arrancada"
        KS[S_HSPD] = HORN_SLOW
        KS[S_DSPD] = DRUM_SLOW
    # ---------------------------------------------------------------- delay estéreo
    if KP[K_DL_ON] > 0.5 and KP[K_DL_MIX] > 0.0:
        size = DB.shape[1]
        mask = size - 1
        t = int(KP[K_DL_TIME])
        if t >= size:
            t = size - 1
        if t < 1:
            t = 1
        fb = KP[K_DL_FB]
        mixd = KP[K_DL_MIX]
        damp = KP[K_DL_DAMP]
        ping = KP[K_DL_PING] > 0.5
        pos = int(KS[S_DPOS])
        lpl = KS[S_DLPL]
        lpr = KS[S_DLPR]
        for i in range(n):
            rd = (pos - t) & mask
            rl = DB[0, rd]
            rr = DB[1, rd]
            lpl += (rl - lpl) * damp
            lpr += (rr - lpr) * damp
            l = KB[i, 0]
            r = KB[i, 1]
            if ping:
                DB[0, pos] = (l + r) * 0.5 + lpr * fb
                DB[1, pos] = lpl * fb
            else:
                DB[0, pos] = l + lpl * fb
                DB[1, pos] = r + lpr * fb
            KB[i, 0] = l + rl * mixd
            KB[i, 1] = r + rr * mixd
            pos = (pos + 1) & mask
        KS[S_DPOS] = pos
        KS[S_DLPL] = lpl if abs(lpl) > 1e-15 else 0.0
        KS[S_DLPR] = lpr if abs(lpr) > 1e-15 else 0.0


@njit(**JIT)
def add_stereo(mix, KB, n):
    peak = 0.0
    for i in range(n):
        l = KB[i, 0]
        r = KB[i, 1]
        if not (abs(l) < 1e6 and abs(r) < 1e6):
            l = 0.0
            r = 0.0
        mix[i, 0] += l
        mix[i, 1] += r
        a = max(abs(l), abs(r))
        if a > peak:
            peak = a
    return peak


class KeysFX:
    def __init__(self, fs, max_block):
        self.fs = float(fs)
        self.KP = np.zeros(KP_SIZE)
        self.KS = np.zeros(KS_SIZE)
        size = 1 << int(math.ceil(math.log2(2.1 * fs)))
        self.DB = np.zeros((2, size))
        self.RB = np.zeros(ROT_BUF)
        self.KB = np.zeros((max_block, 2))
        self.KS[S_HSPD] = HORN_SLOW
        self.KS[S_DSPD] = DRUM_SLOW

    def configure(self, fx, bpm):
        """fx: dicionário de níveis (0-100) e chaves liga/desliga vindos de Instruments."""
        KP, fs = self.KP, self.fs
        KP[K_DRV_ON] = 1.0 if fx["drive_on"] else 0.0
        KP[K_DRV] = fx["drive"] / 100.0
        KP[K_ROT_ON] = 1.0 if fx["rot_on"] else 0.0
        KP[K_ROT_FAST] = 1.0 if fx["rot_fast"] else 0.0
        KP[K_ROT_MIX] = fx["rot_mix"] / 100.0
        KP[K_DL_ON] = 1.0 if fx["delay_on"] else 0.0
        div = fx.get("delay_div", 0)
        if div:                                 # sincronizado ao BPM
            beats = {1: 1.0, 2: 0.5, 3: 0.75, 4: 0.25, 5: 1.0 / 3.0}[div]
            ms = 60000.0 / max(bpm, 30) * beats
        else:
            ms = fx["delay_ms"]
        KP[K_DL_TIME] = ms / 1000.0 * fs
        KP[K_DL_FB] = fx["delay_fb"] / 100.0 * 0.9
        KP[K_DL_MIX] = fx["delay_mix"] / 100.0
        KP[K_DL_DAMP] = 1.0 - math.exp(-2.0 * math.pi * 4500.0 / fs)
        KP[K_DL_PING] = 1.0 if fx.get("delay_ping", True) else 0.0

    def process(self, n):
        process_keys_fx(self.KB, n, self.KP, self.KS, self.DB, self.RB, self.fs)


def warmup(fs=48000.0):
    k = KeysFX(fs, 64)
    k.configure(dict(drive_on=True, drive=40, rot_on=True, rot_fast=True, rot_mix=100, delay_on=True,
                     delay_ms=300, delay_fb=40, delay_mix=30), 100)
    k.KB[:, :] = 0.1
    k.process(64)
    add_stereo(np.zeros((64, 2)), k.KB, 64)
