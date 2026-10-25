"""Sons "worship": bateria sintetizada (bumbos sub, caixa grave, palmas largas, toms
cinematográficos) e o reverb Shimmer (reverb com oitava acima realimentada).

Tudo roda no callback de áudio, em Numba, sem alocação.
"""
import math

import numpy as np
from numba import njit

from .layout import RV_AP_TUNING, RV_COMB_TUNING, RV_STEREO_SPREAD

JIT = dict(cache=True, fastmath=True, nogil=True, error_model="numpy")
TWO_PI = 2.0 * math.pi

# ------------------------------------------------------------------ bateria sintetizada
# parâmetros por tipo de som (colunas abaixo)
P_F0, P_F1, P_FDEC, P_ADEC, P_TONE, P_NOISE, P_NDEC, P_NLP, P_NHP, P_CLICK, P_BURSTS, P_BODY, \
    P_LEVEL, P_VERB = range(14)
NPARAM = 14

# nome: (freq inicial, freq final, queda do pitch s, queda do tom s, nível tom, nível ruído,
#        queda do ruído s, passa-baixa ruído Hz, passa-alta ruído Hz, click, rajadas (palmas),
#        2º tom (corpo da caixa) Hz, nível, envio de reverb)
DRUM_TYPES = {
    "Bumbo Sub Worship":       (130, 42, 0.045, 0.95, 1.0, 0.05, 0.02, 3000, 40, 0.35, 0, 0, 0.315, 0.10),
    "Bumbo Boom Cinemático":   (95, 31, 0.09, 2.2, 1.0, 0.25, 0.25, 600, 30, 0.2, 0, 0, 0.325, 0.25),
    "Bumbo Punch (pop)":       (165, 55, 0.03, 0.38, 1.0, 0.12, 0.015, 6000, 60, 0.6, 0, 0, 0.27, 0.08),
    "Bumbo 808 Longo":         (110, 48, 0.06, 1.6, 1.0, 0.0, 0.01, 2000, 40, 0.25, 0, 0, 0.337, 0.05),
    "Caixa Grave Worship":     (190, 150, 0.04, 0.32, 0.55, 0.85, 0.42, 5500, 900, 0.4, 0, 225, 0.162, 0.45),
    "Caixa Ampla (rimshot)":   (230, 180, 0.03, 0.2, 0.45, 0.9, 0.3, 8000, 1500, 0.6, 0, 330, 0.162, 0.4),
    "Palmas Largas":           (0, 0, 0.01, 0.01, 0.0, 1.0, 0.55, 3200, 900, 0.0, 3, 0, 0.217, 0.5),
    "Palmas + Caixa Worship":  (185, 150, 0.04, 0.3, 0.45, 1.0, 0.5, 4200, 800, 0.3, 3, 230, 0.167, 0.5),
    "Tom Cinemático":          (125, 78, 0.12, 1.3, 1.0, 0.18, 0.12, 1500, 60, 0.25, 0, 0, 0.33, 0.35),
    "Tom Grave Cinemático":    (82, 46, 0.18, 2.0, 1.0, 0.22, 0.2, 900, 40, 0.2, 0, 0, 0.334, 0.35),
    "Chimbal Fechado (synth)": (0, 0, 0.01, 0.01, 0.0, 1.0, 0.045, 14000, 7000, 0.0, 0, 0, 0.199, 0.1),
    "Chimbal Aberto (synth)":  (0, 0, 0.01, 0.01, 0.0, 1.0, 0.42, 14000, 6500, 0.0, 0, 0, 0.176, 0.15),
    "Shaker Suave":            (0, 0, 0.01, 0.01, 0.0, 1.0, 0.11, 9000, 4500, 0.0, 0, 0, 0.184, 0.15),
    "Impacto (Boom + Prato)":  (70, 30, 0.12, 2.6, 1.0, 0.6, 2.2, 9000, 2500, 0.3, 0, 0, 0.224, 0.45),
}
DRUM_TYPE_NAMES = list(DRUM_TYPES)

MAX_DRUM_VOICES = 24
DV_ACTIVE, DV_TYPE, DV_T, DV_VEL, DV_PH, DV_PH2, DV_LP, DV_HP, DV_HPX = range(9)
DV_SIZE = 9


@njit(**JIT)
def render_drums(mix, verb_send, n, ev, nev, DV, DT, fs, gain):
    """Dispara eventos (tipo, velocidade) e soma as vozes em mix (estéreo) e no envio de reverb."""
    for e in range(nev):
        v = -1
        oldest = -1.0
        for k in range(DV.shape[0]):
            if DV[k, DV_ACTIVE] < 0.5:
                v = k
                break
            if DV[k, DV_T] > oldest:
                oldest = DV[k, DV_T]
                v = k
        DV[v, DV_ACTIVE] = 1.0
        DV[v, DV_TYPE] = ev[e, 0]
        DV[v, DV_T] = 0.0
        DV[v, DV_VEL] = ev[e, 1] / 127.0
        DV[v, DV_PH] = 0.0
        DV[v, DV_PH2] = 0.0
        DV[v, DV_LP] = 0.0
        DV[v, DV_HP] = 0.0
        DV[v, DV_HPX] = 0.0
    inv = 1.0 / fs
    for v in range(DV.shape[0]):
        if DV[v, DV_ACTIVE] < 0.5:
            continue
        p = DT[int(DV[v, DV_TYPE])]
        f0, f1, fdec, adec = p[P_F0], p[P_F1], p[P_FDEC], p[P_ADEC]
        tone_l, noise_l, ndec = p[P_TONE], p[P_NOISE], p[P_NDEC]
        lpc = 1.0 - math.exp(-TWO_PI * p[P_NLP] * inv)
        hpc = 1.0 - math.exp(-TWO_PI * p[P_NHP] * inv)
        click, bursts, body = p[P_CLICK], p[P_BURSTS], p[P_BODY]
        amp = p[P_LEVEL] * DV[v, DV_VEL] * gain
        send = p[P_VERB]
        t = DV[v, DV_T]
        ph = DV[v, DV_PH]
        ph2 = DV[v, DV_PH2]
        lp = DV[v, DV_LP]
        hp = DV[v, DV_HP]
        end = 6.0 * max(adec, ndec) + 0.05
        for i in range(n):
            tt = t * inv
            s = 0.0
            if tone_l > 0.0:
                f = f1 + (f0 - f1) * math.exp(-tt / fdec)
                ph += f * inv
                if ph >= 1.0:
                    ph -= 1.0
                s += tone_l * math.sin(TWO_PI * ph) * math.exp(-tt / adec)
                if body > 0.0:
                    ph2 += body * inv
                    if ph2 >= 1.0:
                        ph2 -= 1.0
                    s += 0.5 * tone_l * math.sin(TWO_PI * ph2) * math.exp(-tt / (adec * 0.6))
            if noise_l > 0.0 or click > 0.0:
                w = np.random.random() * 2.0 - 1.0
                lp += (w - lp) * lpc                  # passa-baixa
                hp += (lp - hp) * hpc                 # passa-alta = lp - (lp suavizado)
                nz = lp - hp
                if bursts > 0.0:                      # palmas: rajadas rápidas + cauda
                    env = 0.0
                    for b in range(int(bursts)):
                        tb = tt - b * 0.011
                        if tb >= 0.0:
                            env += math.exp(-tb / 0.007)
                    env += 0.6 * math.exp(-tt / ndec) * (1.0 if tt > 0.03 else tt / 0.03)
                else:
                    env = math.exp(-tt / ndec)
                s += noise_l * nz * env * 1.6
                if click > 0.0 and tt < 0.004:
                    s += click * w * (1.0 - tt / 0.004)
            out = s * amp
            mix[i, 0] += out
            mix[i, 1] += out
            verb_send[i] += out * send
            t += 1.0
            if tt > end:
                DV[v, DV_ACTIVE] = 0.0
                break
        DV[v, DV_T] = t
        DV[v, DV_PH] = ph
        DV[v, DV_PH2] = ph2
        DV[v, DV_LP] = lp
        DV[v, DV_HP] = hp


class DrumSynth:
    def __init__(self, fs):
        self.fs = float(fs)
        self.DV = np.zeros((MAX_DRUM_VOICES, DV_SIZE))
        self.DT = np.array([DRUM_TYPES[k] for k in DRUM_TYPE_NAMES], dtype=np.float64)
        self.ev = np.zeros((64, 2), dtype=np.int64)


# ------------------------------------------------------------------ reverb Shimmer
PS_BUF = 8192          # buffer do pitch shifter (potência de 2)
PS_WIN = 3072          # janela (~64 ms a 48 kHz)


@njit(**JIT)
def fx_shimmer(x, n, mix, B, OFF, LEN, POS, FS_, PS, ST, room, damp, wet, fb):
    """Reverb estéreo (Freeverb) com pitch shift de +1 oitava realimentado (fb = 0: só reverb).

    x: envio mono; o resultado molhado é somado em mix.
    ST: [posição do shift, fase, saída do shift, passa-baixa da realimentação, passa-alta].

    Estabilidade: as janelas do pitch shifter somam 1 (sen² + cos²), a realimentação passa por
    passa-alta/passa-baixa e por um limitador suave, e o ganho do laço fica abaixo de 1. Se
    mesmo assim algo sair do normal (NaN/inf ou nível absurdo), o efeito zera e se recupera.
    """
    pos = int(ST[0])
    phase = ST[1]
    shift_out = ST[2]
    fb_lp = ST[3]
    fb_hp = ST[4]
    mask = PS_BUF - 1
    lp_c = 0.35                    # ~4 kHz a 48 kHz: tira o "brilho" acumulado no laço
    hp_c = 0.004                   # ~30 Hz: tira DC/grave acumulado
    for i in range(n):
        f = shift_out * fb * 0.5
        fb_lp += (f - fb_lp) * lp_c
        fb_hp += (fb_lp - fb_hp) * hp_c
        back = math.tanh((fb_lp - fb_hp) * 2.0) * 0.5
        inp = (x[i] + back) * 0.015
        outs_l = 0.0
        outs_r = 0.0
        for side in range(2):
            acc = 0.0
            for c in range(8):
                u = side * 8 + c
                pp = OFF[u] + POS[u]
                o = B[pp]
                fs_ = o * (1.0 - damp) + FS_[u] * damp
                if -1e-15 < fs_ < 1e-15:
                    fs_ = 0.0
                FS_[u] = fs_
                B[pp] = inp + fs_ * room
                POS[u] += 1
                if POS[u] >= LEN[u]:
                    POS[u] = 0
                acc += o
            for a in range(4):
                u = 16 + side * 4 + a
                pp = OFF[u] + POS[u]
                bo = B[pp]
                o = -acc + bo
                B[pp] = acc + bo * 0.5
                POS[u] += 1
                if POS[u] >= LEN[u]:
                    POS[u] = 0
                acc = o
            if side == 0:
                outs_l = acc
            else:
                outs_r = acc
        if not (abs(outs_l) < 20.0 and abs(outs_r) < 20.0):     # NaN, inf ou disparo
            B[:] = 0.0
            FS_[:] = 0.0
            PS[:] = 0.0
            shift_out = 0.0
            fb_lp = 0.0
            fb_hp = 0.0
            continue
        mix[i, 0] += outs_l * wet
        mix[i, 1] += outs_r * wet
        # pitch shifter (+12): duas cabeças de leitura, atraso caindo 1 amostra/amostra,
        # janelas sen²/cos² (somam 1: sem ganho extra no laço)
        PS[pos] = (outs_l + outs_r) * 0.5
        d1 = PS_WIN * (1.0 - phase)
        p2 = phase + 0.5
        if p2 >= 1.0:
            p2 -= 1.0
        d2 = PS_WIN * (1.0 - p2)
        w1 = math.sin(math.pi * phase)
        w1 *= w1
        shift_out = PS[(pos - int(d1)) & mask] * w1 + PS[(pos - int(d2)) & mask] * (1.0 - w1)
        phase += 1.0 / PS_WIN
        if phase >= 1.0:
            phase -= 1.0
        pos = (pos + 1) & mask
    ST[0] = pos
    ST[1] = phase
    ST[2] = shift_out if abs(shift_out) > 1e-15 else 0.0
    ST[3] = fb_lp if abs(fb_lp) > 1e-15 else 0.0
    ST[4] = fb_hp if abs(fb_hp) > 1e-15 else 0.0


class ShimmerDSP:
    """Estado de um reverb Shimmer (ou reverb comum, com fb = 0)."""

    def __init__(self, fs, room=0.93, damp=0.25):
        scale = fs / 44100.0
        lens = []
        for side in range(2):
            lens += [max(1, int((t * 1.25 + RV_STEREO_SPREAD * side) * scale)) for t in RV_COMB_TUNING]
        for side in range(2):
            lens += [max(1, int((t + RV_STEREO_SPREAD * side) * scale)) for t in RV_AP_TUNING]
        self.LEN = np.array(lens, dtype=np.int64)
        self.OFF = np.concatenate(([0], np.cumsum(self.LEN)[:-1])).astype(np.int64)
        self.B = np.zeros(int(self.LEN.sum()))
        self.POS = np.zeros(len(lens), dtype=np.int64)
        self.FS = np.zeros(16)
        self.PS = np.zeros(PS_BUF)
        self.ST = np.zeros(6)
        self.room = room
        self.damp = damp

    def process(self, x, n, mix, wet, fb):
        fx_shimmer(x, n, mix, self.B, self.OFF, self.LEN, self.POS, self.FS, self.PS, self.ST,
                   self.room, self.damp, wet, fb)


def warmup(fs=48000.0):
    d = DrumSynth(fs)
    mix = np.zeros((64, 2))
    send = np.zeros(64)
    d.ev[0] = (0, 100)
    d.ev[1] = (6, 100)
    render_drums(mix, send, 64, d.ev, 2, d.DV, d.DT, fs, 1.0)
    ShimmerDSP(fs).process(send, 64, mix, 0.5, 0.5)
