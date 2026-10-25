"""Cálculo de coeficientes (roda na thread de UI, não em tempo real)."""
import math

import numpy as np

from .layout import OS_TAPS, OVERSAMPLE

IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0)


def _norm(b0, b1, b2, a0, a1, a2):
    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def biquad(kind, fs, f, gain_db=0.0, q=0.707):
    """Coeficientes RBJ (Audio EQ Cookbook) normalizados: (b0, b1, b2, a1, a2)."""
    f = min(max(f, 5.0), fs * 0.49)
    w = 2.0 * math.pi * f / fs
    cw, sw = math.cos(w), math.sin(w)
    alpha = sw / (2.0 * q)
    A = 10.0 ** (gain_db / 40.0)
    if kind == "lp":
        return _norm((1 - cw) / 2, 1 - cw, (1 - cw) / 2, 1 + alpha, -2 * cw, 1 - alpha)
    if kind == "hp":
        return _norm((1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + alpha, -2 * cw, 1 - alpha)
    if kind == "notch":
        return _norm(1, -2 * cw, 1, 1 + alpha, -2 * cw, 1 - alpha)
    if kind == "peak":
        return _norm(1 + alpha * A, -2 * cw, 1 - alpha * A, 1 + alpha / A, -2 * cw, 1 - alpha / A)
    if kind in ("ls", "hs"):
        sq = 2.0 * math.sqrt(A) * alpha
        if kind == "ls":
            return _norm(A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw),
                         A * ((A + 1) - (A - 1) * cw - sq), (A + 1) + (A - 1) * cw + sq,
                         -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq)
        return _norm(A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw),
                     A * ((A + 1) + (A - 1) * cw - sq), (A + 1) - (A - 1) * cw + sq,
                     2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq)
    raise ValueError(kind)


def onepole_coef(fs, time_s):
    """Coeficiente de suavização: chega a ~99% do alvo em `time_s`."""
    return 1.0 - math.exp(-4.6 / max(time_s * fs, 1.0))


def oversampling_kernel():
    """Passa-baixa FIR (sinc com janela de Kaiser) para o oversampling 4x."""
    n = np.arange(OS_TAPS) - (OS_TAPS - 1) / 2.0
    cutoff = 0.45 / OVERSAMPLE              # ciclos/amostra na taxa sobreamostrada
    h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.kaiser(OS_TAPS, 8.0)
    return (h / h.sum()).astype(np.float64)


def db(x):
    return 10.0 ** (x / 20.0)
