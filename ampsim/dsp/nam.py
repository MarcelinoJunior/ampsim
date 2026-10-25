"""Inferência nativa de capturas Neural Amp Modeler (.nam, arquitetura WaveNet).

Reproduz o WaveNet do NeuralAmpModelerCore (MIT, Steven Atkinson): cada "layer array" faz
um rechannel 1x1, uma pilha de camadas com convolução causal dilatada + mixin do sinal de
entrada + tanh + 1x1 residual, acumulando as ativações num "head" que é reprojetado no fim.
A ordem dos pesos no arquivo é a mesma do código C++ (Conv1D: saída, entrada, kernel).

O processamento é feito por bloco, com os buffers em layout [tempo, canal] para que os
produtos internos fiquem contíguos e o Numba os vetorize (SIMD).
"""
import json
import os

import numpy as np
from numba import njit

JIT = dict(cache=True, fastmath=True, nogil=True, error_model="numpy")
NAM_SAMPLE_RATE = 48000
BUF_EXTRA = 8192               # amostras escritas antes de "rebobinar" o histórico
TARGET_RMS_DB = -18.0          # normalização de volume entre capturas


class NamError(ValueError):
    pass


@njit(**JIT)
def fast_tanh(x):
    # mesma aproximação racional do NeuralAmpModelerCore (erro máx. ~9e-4)
    ax = abs(x)
    x2 = x * x
    return (x * (np.float32(2.45550750702956) + np.float32(2.45550750702956) * ax
                 + (np.float32(0.893229853513558) + np.float32(0.821226666969744) * ax) * x2)
            / (np.float32(2.44506634652299)
               + (np.float32(2.44506634652299) + x2) * abs(x + np.float32(0.814642734961073) * x * ax)))


@njit(**JIT)
def _layer_array(inp, cond, n, X, p, rW, Wcat, convB, mixW, oW, oB, dil, head_acc, out_res, Sf, Zf, Af):
    """Layout canal-major: X [L, C, BUF], inp [In, n], head_acc/out_res [C, n].

    A convolução dilatada vira uma multiplicação de matrizes (im2col): as K janelas do
    histórico são copiadas para S [K*C, n] e Z = Wcat @ S sai numa chamada sgemm (BLAS).
    """
    L = Wcat.shape[0]
    C = Wcat.shape[1]
    KC = Wcat.shape[2]
    K = KC // C
    In = rW.shape[1]
    X0 = X[0]
    for c in range(C):
        for t in range(n):
            acc = np.float32(0.0)
            for j in range(In):
                acc += rW[c, j] * inp[j, t]
            X0[c, p + t] = acc
    S = Sf[:KC * n].reshape(KC, n)
    Z = Zf[:C * n].reshape(C, n)
    A = Af[:C * n].reshape(C, n)
    for l in range(L):
        d = dil[l]
        Xl = X[l]
        for k in range(K):
            base = p - d * (K - 1 - k)
            for ci in range(C):
                srow = S[k * C + ci]
                xs = Xl[ci]
                for t in range(n):
                    srow[t] = xs[base + t]
        np.dot(Wcat[l], S, Z)
        for c in range(C):
            b = convB[l, c]
            m = mixW[l, c]
            zr = Z[c]
            hr = head_acc[c]
            for t in range(n):
                v = fast_tanh(zr[t] + b + m * cond[t])
                zr[t] = v
                hr[t] += v
        np.dot(oW[l], Z, A)
        for c in range(C):
            xin = Xl[c]
            ar = A[c]
            b = oB[l, c]
            if l + 1 < L:
                dst = X[l + 1, c]
                for t in range(n):
                    dst[p + t] = xin[p + t] + ar[t] + b
            else:
                dst = out_res[c]
                for t in range(n):
                    dst[t] = xin[p + t] + ar[t] + b


@njit(**JIT)
def _head(head_acc, n, hW, hB, out):
    H = hW.shape[0]
    C = hW.shape[1]
    for h in range(H):
        o = out[h]
        for t in range(n):
            o[t] = hB[h]
        for c in range(C):
            w = hW[h, c]
            hr = head_acc[c]
            for t in range(n):
                o[t] += w * hr[t]


class _Array:
    def __init__(self, cfg, take):
        if cfg.get("gated") or cfg.get("activation", "Tanh") != "Tanh" or cfg.get("condition_size", 1) != 1:
            raise NamError("Variante de WaveNet não suportada (gated/ativação/condição)")
        In, C, H, K = cfg["input_size"], cfg["channels"], cfg["head_size"], cfg["kernel_size"]
        dil = cfg["dilations"]
        L = len(dil)
        self.rW = take(C * In).reshape(C, In)
        self.Wcat = np.empty((L, C, K * C), np.float32)      # [camada, saída, k*C + entrada]
        self.convB = np.empty((L, C), np.float32)
        self.mixW = np.empty((L, C), np.float32)
        self.oW = np.empty((L, C, C), np.float32)
        self.oB = np.empty((L, C), np.float32)
        for l in range(L):
            self.Wcat[l] = take(C * C * K).reshape(C, C, K).transpose(0, 2, 1).reshape(C, K * C)
            self.convB[l] = take(C)
            self.mixW[l] = take(C)
            self.oW[l] = take(C * C).reshape(C, C)
            self.oB[l] = take(C)
        self.hW = take(H * C).reshape(H, C)
        self.hB = take(H) if cfg.get("head_bias") else np.zeros(H, np.float32)
        self.dil = np.asarray(dil, np.int64)
        self.C, self.H, self.L = C, H, L
        self.hist = int(max(dil) * (K - 1))


class NamModel:
    """Uma instância por trilha (guarda o histórico da rede)."""

    def __init__(self, path, max_block=4096):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("architecture") != "WaveNet":
            raise NamError(f"Arquitetura {d.get('architecture')!r} não suportada (só WaveNet)")
        cfg = d["config"]
        if cfg.get("head") is not None:
            raise NamError("WaveNet com 'head' extra não suportado")
        w = np.asarray(d["weights"], np.float32)
        pos = [0]

        def take(k):
            a = w[pos[0]:pos[0] + k]
            if len(a) != k:
                raise NamError("Arquivo .nam com pesos faltando")
            pos[0] += k
            return a.copy()

        self.arrays = [_Array(la, take) for la in cfg["layers"]]
        self.head_scale = float(take(1)[0])
        if pos[0] != len(w):
            raise NamError(f"Sobraram {len(w) - pos[0]} pesos: formato inesperado")
        for a, b in zip(self.arrays, self.arrays[1:]):
            if a.H != b.C:
                raise NamError("Dimensões incompatíveis entre layer arrays")

        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.sample_rate = d.get("sample_rate") or NAM_SAMPLE_RATE
        self.max_block = max_block
        self.hist = max(a.hist for a in self.arrays)
        self.buf_len = self.hist + BUF_EXTRA
        self.X = [np.zeros((a.L, a.C, self.buf_len), np.float32) for a in self.arrays]
        self.p = self.hist
        self.cond = np.zeros(max_block, np.float32)
        self.inp0 = self.cond.reshape(1, max_block)
        self.res = [np.zeros((a.C, max_block), np.float32) for a in self.arrays]
        self.head_acc = [np.zeros((a.C, max_block), np.float32) for a in self.arrays]
        self.head_out = [np.zeros((a.H, max_block), np.float32) for a in self.arrays]
        cmax = max(a.C for a in self.arrays)
        kmax = max(a.Wcat.shape[2] for a in self.arrays)
        self.Sf = np.zeros(kmax * max_block, np.float32)
        self.Zf = np.zeros(cmax * max_block, np.float32)
        self.Af = np.zeros(cmax * max_block, np.float32)
        self.norm = 1.0
        self._prewarm()
        self._calibrate()

    def reset(self):
        for X in self.X:
            X[:] = 0
        self.p = self.hist
        self._prewarm()

    def _prewarm(self):
        """Roda silêncio pela rede para assentar o DC (como o plugin faz ao carregar)."""
        zeros = np.zeros(1024)
        for _ in range(self.hist // 1024 + 2):
            self.process(zeros, 1024)

    def _calibrate(self):
        """Mede o volume de saída com um sinal tipo guitarra e normaliza para -18 dBFS RMS."""
        fs = float(self.sample_rate)
        t = np.arange(int(fs * 0.5)) / fs
        x = sum(np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate((110.0, 220.0, 330.0, 440.0)))
        x = x / np.abs(x).max() * 10 ** (-12 / 20)
        y = np.empty_like(x)
        for i in range(0, len(x) - 512 + 1, 512):
            blk = x[i:i + 512].copy()
            self.process(blk, 512)
            y[i:i + 512] = blk
        rms = np.sqrt(np.mean(y[len(y) // 2:] ** 2))
        self.norm = 10 ** (TARGET_RMS_DB / 20) / rms if rms > 1e-6 else 1.0
        self.reset()

    def process(self, x, n):
        """Processa x[:n] (float64) no lugar. Chamado na thread de áudio."""
        if self.p + n > self.buf_len:
            h = self.hist
            for X in self.X:
                X[:, :, :h] = X[:, :, self.p - h:self.p]
            self.p = h
        cond = self.cond
        cond[:n] = x[:n]
        inp = self.inp0
        for i, a in enumerate(self.arrays):
            acc = self.head_acc[i]
            if i == 0:
                acc[:, :n] = 0
            else:
                acc[:, :n] = self.head_out[i - 1][:, :n]
            _layer_array(inp, cond, n, self.X[i], self.p, a.rW, a.Wcat, a.convB, a.mixW, a.oW,
                         a.oB, a.dil, acc, self.res[i], self.Sf, self.Zf, self.Af)
            _head(acc, n, a.hW, a.hB, self.head_out[i])
            inp = self.res[i]
        x[:n] = self.head_out[-1][0, :n] * (self.head_scale * self.norm)
        self.p += n


def capture_dirs():
    from ..storage import APP_DIR

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [os.path.join(root, "third_party", "nam_models"), str(APP_DIR / "nam")]


def list_captures():
    """{nome exibido: caminho} de todas as capturas disponíveis."""
    found = {}
    for d in capture_dirs():
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".nam"):
                    found.setdefault(os.path.splitext(f)[0], os.path.join(d, f))
    return found
