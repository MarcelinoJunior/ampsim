"""Kernels de DSP em tempo real, compilados para código nativo com Numba.

Tudo aqui roda dentro do callback de áudio: sem alocação, sem objetos Python.
A cadeia de cada trilha é:

    Gate -> Compressor -> Overdrive(4x) -> Amp(4x) -> Gabinete -> EQ
         -> [mono->estéreo] -> Chorus -> Delay -> Reverb -> Volume/Pan
"""
import math

import numpy as np
from numba import njit

from .layout import (
    A_BIAS, A_BLEND, A_G1, A_G2, A_G3, A_HEAD, A_ON, A_OUT, A_PDRIVE, A_SAG, A_SAGCOEF, A_STAGES,
    BQ_A_BASS, BQ_A_DEPTH, BQ_A_DI, BQ_A_HPF, BQ_A_INTER1, BQ_A_INTER2, BQ_A_MID, BQ_A_PRES,
    BQ_A_TREB, BQ_CAB, BQ_EQ, BQ_NR_HPF, BQ_NR_HUM, BQ_NR_LPF, BQ_OD_HPF, BQ_OD_TONE,
    C_ATT, C_MAKEUP, C_ON, C_REL, C_SLOPE, C_THR_DB,
    CAB_GAIN, CAB_IRLEN, CAB_MODE, CAB_NBQ, CAB_ON,
    CH_BASE, CH_DEPTH, CH_MIX, CH_ON, CH_RATE, CHORUS_BUF,
    DL_DAMP, DL_FB, DL_MIX, DL_ON, DL_PING, DL_TIME,
    EQ_BANDS, EQ_LEVEL, EQ_ON,
    EV_ALL_OFF, EV_BEND, EV_MOD, EV_NOTE_OFF, EV_NOTE_ON, EV_SUSTAIN,
    G_ATT, G_DET, G_ON, G_REL, G_THR,
    IR_BUF, MAX_VOICES,
    NR_ATT, NR_DYN, NR_FMAX, NR_FMIN, NR_HPF, NR_HUM, NR_LPF, NR_ON, NR_REL, NR_THR,
    O_DRIVE, O_LEVEL, O_ON, OS_PHASE, OS_TAPS, OVERSAMPLE,
    RV_APS, RV_COMBS, RV_DAMP, RV_DRY, RV_FB, RV_ON, RV_WET, RV_WIDTH,
    S_CH_PHASE, S_CH_POS, S_COMP_ENV, S_DL_LEN, S_DL_LP_L, S_DL_LP_R, S_DL_POS,
    S_GATE_ENV, S_GATE_GAIN, S_GATE_OPEN, S_IR_POS, S_OSD0, S_OSD1, S_OSU0, S_OSU1,
    S_NR_ENV, S_NR_IC1, S_NR_IC2, S_PEAK_IN, S_PEAK_OUT, S_SAG,
    SS_AGE, SS_BEND, SS_LFO, SS_MOD, SS_PRESTART, SS_PULSE, SS_SUSTAIN, SS_XF, SS_XFMUL, SS_XFOCT,
    SY_AATT, SY_ADEC, SY_AREL, SY_ASUS, SY_BEND_RANGE, SY_CUTOFF, SY_DETUNE, SY_FATT,
    SY_FDEC, SY_FENV, SY_FREL, SY_FSUS, SY_KEYTRK, SY_LFODEPTH, SY_LFORATE, SY_MIX2,
    SY_PULSE_DEPTH, SY_PULSE_FILT, SY_PULSE_RATE, SY_PULSE_RETRIG, SY_PULSE_SHAPE,
    SY_RESO, SY_SEMI2, SY_SUB, SY_VELSENS, SY_VOL, SY_WAVE1, SY_WAVE2,
    T_AMP, T_INGAIN, T_PANL, T_PANR, T_VOL,
    V_ACTIVE, V_AGE, V_ELEVEL, V_ESTAGE, V_FLEVEL, V_FREQ, V_FSTAGE, V_GATE, V_HELD,
    V_IC1, V_IC2, V_NOTE, V_PH1, V_PH2, V_PHS, V_VEL,
)

JIT = dict(cache=True, fastmath=True, nogil=True, error_model="numpy")
TWO_PI = 2.0 * math.pi


# ======================================================================= utilitários
@njit(**JIT)
def bq(x, BQ, Z, i):
    """Biquad Transposed Direct Form II."""
    y = BQ[i, 0] * x + Z[i, 0]
    Z[i, 0] = BQ[i, 1] * x - BQ[i, 3] * y + Z[i, 1]
    Z[i, 1] = BQ[i, 2] * x - BQ[i, 4] * y
    return y


@njit(**JIT)
def flush_denormals(Z):
    for i in range(Z.shape[0]):
        for j in range(Z.shape[1]):
            if -1e-15 < Z[i, j] < 1e-15:
                Z[i, j] = 0.0


@njit(**JIT)
def clip_asym(x, bias, tbias):
    # tanh com polarização: gera harmônicos pares como um estágio valvulado
    return math.tanh(x + bias) - tbias


@njit(**JIT)
def upsample_block(x, n, h, buf, ST, si, u):
    pos = int(ST[si])
    for i in range(n):
        pos -= 1
        if pos < 0:
            pos = OS_PHASE - 1
        buf[pos] = x[i]
        buf[pos + OS_PHASE] = x[i]
        for k in range(OVERSAMPLE):
            acc = 0.0
            for j in range(OS_PHASE):
                acc += h[j * OVERSAMPLE + k] * buf[pos + j]
            u[i * OVERSAMPLE + k] = acc * OVERSAMPLE
    ST[si] = pos


@njit(**JIT)
def downsample_block(u, n, h, buf, ST, si, y):
    pos = int(ST[si])
    for i in range(n):
        for k in range(OVERSAMPLE):
            pos -= 1
            if pos < 0:
                pos = OS_TAPS - 1
            v = u[i * OVERSAMPLE + k]
            buf[pos] = v
            buf[pos + OS_TAPS] = v
        acc = 0.0
        for j in range(OS_TAPS):
            acc += h[j] * buf[pos + j]
        y[i] = acc
    ST[si] = pos


# ======================================================================= efeitos (mono)
@njit(**JIT)
def fx_denoise(x, n, D, BQ, Z, ST):
    """Corte grave, notches da rede elétrica (hum) e corte agudo fixos, mais um passa-baixa
    dinâmico (anti-chiado) que fecha os agudos quando o sinal cai abaixo do limiar."""
    hum = int(D[NR_HUM])
    hpf = D[NR_HPF] > 0.5
    lpf = D[NR_LPF] > 0.5
    amt = D[NR_DYN]
    thr = D[NR_THR]
    att = D[NR_ATT]
    rel = D[NR_REL]
    fmin = D[NR_FMIN]
    fmax = D[NR_FMAX]
    ratio = fmin / fmax
    k = 1.4142135623730951          # Q = 0.707
    env = ST[S_NR_ENV]
    ic1 = ST[S_NR_IC1]
    ic2 = ST[S_NR_IC2]
    for i in range(n):
        v = x[i]
        if hpf:
            v = bq(v, BQ, Z, BQ_NR_HPF)
        for h in range(hum):
            v = bq(v, BQ, Z, BQ_NR_HUM + h)
        if lpf:
            v = bq(v, BQ, Z, BQ_NR_LPF)
        if amt > 0.0:
            a = abs(v)
            env += (a - env) * (att if a > env else rel)
            o = (20.0 * math.log10(env + 1e-9) - thr) / 20.0 + 1.0    # 0 = 20 dB abaixo do limiar
            if o > 1.0:
                o = 1.0
            elif o < 0.0:
                o = 0.0
            g = math.tan(math.pi * fmax * math.pow(ratio, (1.0 - o) * amt))
            a1 = 1.0 / (1.0 + g * (g + k))
            a2 = g * a1
            v3 = v - ic2
            v1 = a1 * ic1 + a2 * v3
            v2 = ic2 + a2 * ic1 + g * a2 * v3
            ic1 = 2.0 * v1 - ic1
            ic2 = 2.0 * v2 - ic2
            v = v2
        x[i] = v
    ST[S_NR_ENV] = env
    ST[S_NR_IC1] = ic1 if abs(ic1) > 1e-15 else 0.0
    ST[S_NR_IC2] = ic2 if abs(ic2) > 1e-15 else 0.0


@njit(**JIT)
def fx_gate(x, n, D, ST):
    thr = D[G_THR]
    det = D[G_DET]
    att = D[G_ATT]
    rel = D[G_REL]
    env = ST[S_GATE_ENV]
    g = ST[S_GATE_GAIN]
    is_open = ST[S_GATE_OPEN]
    for i in range(n):
        a = abs(x[i])
        env = a if a > env else env * det
        if is_open > 0.5:
            if env < thr * 0.5:
                is_open = 0.0
        elif env > thr:
            is_open = 1.0
        if is_open > 0.5:
            g += (1.0 - g) * att
        else:
            g += (0.0 - g) * rel
        x[i] *= g
    ST[S_GATE_ENV] = env
    ST[S_GATE_GAIN] = g
    ST[S_GATE_OPEN] = is_open


@njit(**JIT)
def fx_comp(x, n, D, ST):
    thr = D[C_THR_DB]
    slope = D[C_SLOPE]
    att = D[C_ATT]
    rel = D[C_REL]
    makeup = D[C_MAKEUP]
    knee = 6.0
    env = ST[S_COMP_ENV]
    for i in range(n):
        a = abs(x[i])
        env += (a - env) * (att if a > env else rel)
        over = 20.0 * math.log10(env + 1e-9) - thr
        if over <= -knee * 0.5:
            gr = 0.0
        elif over < knee * 0.5:
            t = over + knee * 0.5
            gr = -slope * t * t / (2.0 * knee)
        else:
            gr = -slope * over
        x[i] *= math.pow(10.0, gr * 0.05) * makeup
    ST[S_COMP_ENV] = env


@njit(**JIT)
def fx_overdrive(x, n, D, BQ, Z, ST, h, OSU, OSD, t1, u):
    drive = D[O_DRIVE]
    level = D[O_LEVEL]
    for i in range(n):
        t1[i] = bq(x[i], BQ, Z, BQ_OD_HPF) * drive
    upsample_block(t1, n, h, OSU[0], ST, S_OSU0, u)
    tb = math.tanh(0.15)
    for m in range(n * OVERSAMPLE):
        u[m] = clip_asym(u[m], 0.15, tb)
    downsample_block(u, n, h, OSD[0], ST, S_OSD0, t1)
    for i in range(n):
        x[i] = bq(x[i] * 0.5 + t1[i], BQ, Z, BQ_OD_TONE) * level


@njit(**JIT)
def fx_amp(x, n, D, BQ, Z, ST, h, OSU, OSD, t1, u, di):
    stages = int(D[A_STAGES])
    g1 = D[A_G1]
    g2 = D[A_G2]
    g3 = D[A_G3]
    bias = D[A_BIAS]
    tb1 = math.tanh(bias)
    tb2 = math.tanh(bias * 0.7)
    tb3 = math.tanh(bias * 0.5)
    pd = D[A_PDRIVE]
    sag_amt = D[A_SAG]
    sag_c = D[A_SAGCOEF]
    head = D[A_HEAD]
    inv_head = 1.0 / head
    out = D[A_OUT]
    blend = D[A_BLEND]
    sag = ST[S_SAG]

    if blend > 0.0:
        for i in range(n):
            di[i] = bq(x[i], BQ, Z, BQ_A_DI)

    upsample_block(x, n, h, OSU[1], ST, S_OSU1, u)
    for m in range(n * OVERSAMPLE):
        v = bq(u[m], BQ, Z, BQ_A_HPF)
        v = clip_asym(v * g1, bias, tb1)
        v = bq(v, BQ, Z, BQ_A_INTER1)
        if stages >= 2:
            v = clip_asym(v * g2, bias * 0.7, tb2)
            v = bq(v, BQ, Z, BQ_A_INTER2)
        if stages >= 3:
            v = clip_asym(v * g3, bias * 0.5, tb3)
        v = bq(v, BQ, Z, BQ_A_BASS)
        v = bq(v, BQ, Z, BQ_A_MID)
        v = bq(v, BQ, Z, BQ_A_TREB)
        # estágio de potência com "sag" (a fonte cede quando o sinal é alto)
        p = v * pd
        sag += (abs(p) - sag) * sag_c
        # head < 1: mesma amplitude em sinal baixo, mas satura bem mais tarde (amp limpo)
        u[m] = math.tanh(p * head / (1.0 + sag_amt * sag * head)) * inv_head
    downsample_block(u, n, h, OSD[1], ST, S_OSD1, t1)
    for i in range(n):
        y = bq(t1[i], BQ, Z, BQ_A_PRES)
        y = bq(y, BQ, Z, BQ_A_DEPTH) * out
        if blend > 0.0:
            y = y * (1.0 - blend) + di[i] * blend
        x[i] = y
    ST[S_SAG] = sag


@njit(**JIT)
def fx_cab(x, n, D, BQ, Z, ST, IR, IRH):
    gain = D[CAB_GAIN]
    if int(D[CAB_MODE]) == 0:
        nbq = int(D[CAB_NBQ])
        for i in range(n):
            y = x[i]
            for b in range(nbq):
                y = bq(y, BQ, Z, BQ_CAB + b)
            x[i] = y * gain
    else:
        # convolução direta (latência zero); histórico gravado em dobro para leitura contígua
        L = int(D[CAB_IRLEN])
        pos = int(ST[S_IR_POS])
        for i in range(n):
            pos -= 1
            if pos < 0:
                pos = IR_BUF - 1
            IRH[pos] = x[i]
            IRH[pos + IR_BUF] = x[i]
            acc = 0.0
            for k in range(L):
                acc += IR[k] * IRH[pos + k]
            x[i] = acc * gain
        ST[S_IR_POS] = pos


@njit(**JIT)
def fx_eq(x, n, D, BQ, Z):
    level = D[EQ_LEVEL]
    for i in range(n):
        y = x[i]
        for b in range(EQ_BANDS):
            y = bq(y, BQ, Z, BQ_EQ + b)
        x[i] = y * level


# ======================================================================= efeitos (estéreo)
@njit(**JIT)
def fx_chorus(L, R, n, D, ST, CHB):
    rate = D[CH_RATE]
    depth = D[CH_DEPTH]
    base = D[CH_BASE]
    mix = D[CH_MIX]
    ph = ST[S_CH_PHASE]
    pos = int(ST[S_CH_POS])
    mask = CHORUS_BUF - 1
    for i in range(n):
        x = (L[i] + R[i]) * 0.5
        CHB[pos] = x
        dl = base + depth * (0.5 + 0.5 * math.sin(TWO_PI * ph))
        dr = base + depth * (0.5 + 0.5 * math.sin(TWO_PI * (ph + 0.25)))
        # leitura fracionária (interpolação linear)
        fl = pos - dl
        il = int(math.floor(fl))
        fr = fl - il
        wl = CHB[il & mask] * (1.0 - fr) + CHB[(il + 1) & mask] * fr
        fl = pos - dr
        il = int(math.floor(fl))
        fr = fl - il
        wr = CHB[il & mask] * (1.0 - fr) + CHB[(il + 1) & mask] * fr
        L[i] = L[i] * (1.0 - 0.5 * mix) + wl * mix
        R[i] = R[i] * (1.0 - 0.5 * mix) + wr * mix
        pos = (pos + 1) & mask
        ph += rate
        if ph >= 1.0:
            ph -= 1.0
    ST[S_CH_PHASE] = ph
    ST[S_CH_POS] = pos


@njit(**JIT)
def fx_delay(L, R, n, D, ST, DLB):
    size = int(ST[S_DL_LEN])
    mask = size - 1
    t = int(D[DL_TIME])
    if t >= size:
        t = size - 1
    fb = D[DL_FB]
    mix = D[DL_MIX]
    damp = D[DL_DAMP]
    ping = D[DL_PING] > 0.5
    pos = int(ST[S_DL_POS])
    lpl = ST[S_DL_LP_L]
    lpr = ST[S_DL_LP_R]
    for i in range(n):
        rd = (pos - t) & mask
        rl = DLB[0, rd]
        rr = DLB[1, rd]
        lpl += (rl - lpl) * damp
        lpr += (rr - lpr) * damp
        if ping:
            DLB[0, pos] = (L[i] + R[i]) * 0.5 + lpr * fb
            DLB[1, pos] = lpl * fb
        else:
            DLB[0, pos] = L[i] + lpl * fb
            DLB[1, pos] = R[i] + lpr * fb
        L[i] += rl * mix
        R[i] += rr * mix
        pos = (pos + 1) & mask
    if -1e-15 < lpl < 1e-15:
        lpl = 0.0
    if -1e-15 < lpr < 1e-15:
        lpr = 0.0
    ST[S_DL_POS] = pos
    ST[S_DL_LP_L] = lpl
    ST[S_DL_LP_R] = lpr


@njit(**JIT)
def fx_reverb(L, R, n, D, RVB, RVOFF, RVLEN, RVPOS, RVFS):
    room = D[RV_FB]
    damp = D[RV_DAMP]
    wet = D[RV_WET]
    dry = D[RV_DRY]
    width = D[RV_WIDTH]
    wet1 = wet * (width * 0.5 + 0.5)
    wet2 = wet * ((1.0 - width) * 0.5)
    for i in range(n):
        inp = (L[i] + R[i]) * 0.015
        outs_l = 0.0
        outs_r = 0.0
        for side in range(2):
            acc = 0.0
            for c in range(RV_COMBS):
                ui = side * RV_COMBS + c
                p = RVOFF[ui] + RVPOS[ui]
                o = RVB[p]
                f = o * (1.0 - damp) + RVFS[ui] * damp
                if -1e-15 < f < 1e-15:
                    f = 0.0
                RVFS[ui] = f
                RVB[p] = inp + f * room
                RVPOS[ui] += 1
                if RVPOS[ui] >= RVLEN[ui]:
                    RVPOS[ui] = 0
                acc += o
            for a in range(RV_APS):
                ui = 2 * RV_COMBS + side * RV_APS + a
                p = RVOFF[ui] + RVPOS[ui]
                bo = RVB[p]
                o = -acc + bo
                RVB[p] = acc + bo * 0.5
                RVPOS[ui] += 1
                if RVPOS[ui] >= RVLEN[ui]:
                    RVPOS[ui] = 0
                acc = o
            if side == 0:
                outs_l = acc
            else:
                outs_r = acc
        L[i] = outs_l * wet1 + outs_r * wet2 + L[i] * dry
        R[i] = outs_r * wet1 + outs_l * wet2 + R[i] * dry


# ======================================================================= trilha completa
# A cadeia é dividida em duas metades para que a captura NAM e o plugin VST3 (que rodam
# fora deste kernel) entrem entre o amplificador e o gabinete. O sinal mono fica em W[0].
@njit(**JIT)
def process_pre(src, ch, n, D, BQ, Z, ST, H, OSU, OSD, W):
    """Entrada -> redutor de ruído -> gate -> compressor -> overdrive -> amp."""
    x = W[0]
    t1 = W[1]
    u = W[2]
    di = W[5]
    ingain = D[T_INGAIN]
    peak = ST[S_PEAK_IN]
    for i in range(n):
        v = src[i, ch] * ingain
        x[i] = v
        if abs(v) > peak:
            peak = abs(v)
    ST[S_PEAK_IN] = peak
    if D[T_AMP] < 0.5:
        return

    if D[NR_ON] > 0.5:
        fx_denoise(x, n, D, BQ, Z, ST)
    if D[G_ON] > 0.5:
        fx_gate(x, n, D, ST)
    if D[C_ON] > 0.5:
        fx_comp(x, n, D, ST)
    if D[O_ON] > 0.5:
        fx_overdrive(x, n, D, BQ, Z, ST, H, OSU, OSD, t1, u)
    if D[A_ON] > 0.5:
        fx_amp(x, n, D, BQ, Z, ST, H, OSU, OSD, t1, u, di)


@njit(**JIT)
def process_post(n, mix, D, BQ, Z, ST, IR, IRH, CHB, DLB, RVB, RVOFF, RVLEN, RVPOS, RVFS, W):
    """Gabinete -> EQ -> chorus -> delay -> reverb -> volume/pan, somando em `mix`."""
    x = W[0]
    L = W[3]
    R = W[4]
    if D[CAB_ON] > 0.5 and D[T_AMP] > 0.5:
        fx_cab(x, n, D, BQ, Z, ST, IR, IRH)
    if D[EQ_ON] > 0.5:
        fx_eq(x, n, D, BQ, Z)

    for i in range(n):
        L[i] = x[i]
        R[i] = x[i]
    if D[CH_ON] > 0.5:
        fx_chorus(L, R, n, D, ST, CHB)
    if D[DL_ON] > 0.5:
        fx_delay(L, R, n, D, ST, DLB)
    if D[RV_ON] > 0.5:
        fx_reverb(L, R, n, D, RVB, RVOFF, RVLEN, RVPOS, RVFS)

    vl = D[T_VOL] * D[T_PANL]
    vr = D[T_VOL] * D[T_PANR]
    peak = ST[S_PEAK_OUT]
    for i in range(n):
        l = L[i] * vl
        r = R[i] * vr
        mix[i, 0] += l
        mix[i, 1] += r
        a = max(abs(l), abs(r))
        if a > peak:
            peak = a
    ST[S_PEAK_OUT] = peak
    flush_denormals(Z)


@njit(**JIT)
def process_track(src, ch, n, mix, D, BQ, Z, ST, H, OSU, OSD, IR, IRH, CHB, DLB,
                  RVB, RVOFF, RVLEN, RVPOS, RVFS, W):
    """Cadeia inteira numa chamada (quando não há NAM/VST na trilha)."""
    process_pre(src, ch, n, D, BQ, Z, ST, H, OSU, OSD, W)
    process_post(n, mix, D, BQ, Z, ST, IR, IRH, CHB, DLB, RVB, RVOFF, RVLEN, RVPOS, RVFS, W)


@njit(**JIT)
def mix_soundfont(B, n, mix, synth_out, shim, kb, to_chain, keys_gain, drums_gain, pad_gain,
                  keys_shim, pad_shim):
    """Soma a saída do FluidSynth (4 grupos; ver audio/soundfont.py) e monta o envio do Shimmer.

    Teclas: para a trilha (to_chain, mono) ou direto em estéreo. Pads e pad contínuo: sempre
    direto. Retorna o pico do que foi direto para a saída.
    """
    peak = 0.0
    for i in range(n):
        kl = (B[0, i] + B[8, i] + B[10, i]) * keys_gain
        kr = (B[1, i] + B[9, i] + B[11, i]) * keys_gain
        dl = (B[2, i] + B[12, i] + B[14, i] + B[6, i] + B[20, i] + B[22, i]) * drums_gain
        dr = (B[3, i] + B[13, i] + B[15, i] + B[7, i] + B[21, i] + B[23, i]) * drums_gain
        pl = (B[4, i] + B[16, i] + B[18, i]) * pad_gain
        pr = (B[5, i] + B[17, i] + B[19, i]) * pad_gain
        send = (pl + pr) * 0.5 * pad_shim
        l = dl + pl
        r = dr + pr
        if to_chain:
            synth_out[i, 0] += (kl + kr) * 0.5
            kb[i, 0] = 0.0
            kb[i, 1] = 0.0
        else:                                   # teclas vão para os efeitos das teclas (kb)
            kb[i, 0] = kl
            kb[i, 1] = kr
            send += (kl + kr) * 0.5 * keys_shim
        shim[i] = send
        mix[i, 0] += l
        mix[i, 1] += r
        a = max(abs(l), abs(r))
        if a > peak:
            peak = a
    return peak


@njit(**JIT)
def write_output(mix, n, out, off, master):
    """Copia a mixagem para o buffer do driver, com limitador suave de segurança."""
    nout = out.shape[1]
    for i in range(n):
        for c in range(nout):
            out[i, c] = 0.0
        for k in range(2):
            v = mix[i, k] * master
            if not (abs(v) < 1e6):         # NaN/inf de algum efeito: silencia esta amostra
                v = 0.0
            a = abs(v)
            if a > 0.9:
                v = math.copysign(0.9 + 0.1 * math.tanh((a - 0.9) * 10.0), v)
            if off + k < nout:
                out[i, off + k] = v
            mix[i, k] = 0.0


# ======================================================================= synth de pads
@njit(**JIT)
def polyblep(t, dt):
    if t < dt:
        t /= dt
        return t + t - t * t - 1.0
    if t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


@njit(**JIT)
def osc(ph, dt, wave):
    if wave == 0:
        return math.sin(TWO_PI * ph)
    if wave == 1:
        return 2.0 * abs(2.0 * ph - 1.0) - 1.0
    if wave == 2:
        return 2.0 * ph - 1.0 - polyblep(ph, dt)
    v = 1.0 if ph < 0.5 else -1.0
    t2 = ph + 0.5
    if t2 >= 1.0:
        t2 -= 1.0
    return v + polyblep(ph, dt) - polyblep(t2, dt)


@njit(**JIT)
def _release(VS, v):
    VS[v, V_ESTAGE] = 4.0
    VS[v, V_FSTAGE] = 4.0
    VS[v, V_HELD] = 0.0


@njit(**JIT)
def synth_events(ev, nev, VS, SST, retrig):
    for e in range(nev):
        kind = ev[e, 0]
        a = ev[e, 1]
        b = ev[e, 2]
        if kind == EV_NOTE_ON and b == 0:
            kind = EV_NOTE_OFF
        if kind == EV_NOTE_ON:
            if retrig:                            # 1ª nota depois de soltar tudo: pulso começa no tempo
                held = False
                for k in range(MAX_VOICES):
                    if VS[k, V_ACTIVE] > 0.5 and (VS[k, V_GATE] > 0.5 or VS[k, V_HELD] > 0.5):
                        held = True
                        break
                if not held:
                    SST[SS_PULSE] = 0.0
            v = -1
            for k in range(MAX_VOICES):          # mesma nota já soando: reaproveita
                if VS[k, V_ACTIVE] > 0.5 and int(VS[k, V_NOTE]) == a:
                    v = k
                    break
            if v < 0:
                for k in range(MAX_VOICES):      # voz livre
                    if VS[k, V_ACTIVE] < 0.5:
                        v = k
                        break
            if v < 0:                            # rouba: a mais silenciosa em release, senão a mais antiga
                best = 1e9
                for k in range(MAX_VOICES):
                    if VS[k, V_ESTAGE] == 4.0 and VS[k, V_ELEVEL] < best:
                        best = VS[k, V_ELEVEL]
                        v = k
                if v < 0:
                    best = 1e18
                    for k in range(MAX_VOICES):
                        if VS[k, V_AGE] < best:
                            best = VS[k, V_AGE]
                            v = k
            if VS[v, V_ACTIVE] < 0.5:
                VS[v, V_PH1] = 0.0
                VS[v, V_PH2] = 0.37
                VS[v, V_PHS] = 0.0
                VS[v, V_ELEVEL] = 0.0
                VS[v, V_FLEVEL] = 0.0
                VS[v, V_IC1] = 0.0
                VS[v, V_IC2] = 0.0
            VS[v, V_ACTIVE] = 1.0
            VS[v, V_NOTE] = a
            VS[v, V_VEL] = b / 127.0
            VS[v, V_FREQ] = 440.0 * math.pow(2.0, (a - 69) / 12.0)
            VS[v, V_ESTAGE] = 1.0
            VS[v, V_FSTAGE] = 1.0
            VS[v, V_GATE] = 1.0
            VS[v, V_HELD] = 0.0
            SST[SS_AGE] += 1.0
            VS[v, V_AGE] = SST[SS_AGE]
        elif kind == EV_NOTE_OFF:
            for k in range(MAX_VOICES):
                if VS[k, V_ACTIVE] > 0.5 and VS[k, V_GATE] > 0.5 and int(VS[k, V_NOTE]) == a:
                    VS[k, V_GATE] = 0.0
                    if SST[SS_SUSTAIN] > 0.5:
                        VS[k, V_HELD] = 1.0
                    else:
                        _release(VS, k)
        elif kind == EV_SUSTAIN:
            SST[SS_SUSTAIN] = 1.0 if a >= 64 else 0.0
            if a < 64:
                for k in range(MAX_VOICES):
                    if VS[k, V_HELD] > 0.5:
                        _release(VS, k)
        elif kind == EV_BEND:
            SST[SS_BEND] = (a - 8192) / 8192.0
        elif kind == EV_MOD:
            SST[SS_MOD] = a / 127.0
        elif kind == EV_ALL_OFF:
            for k in range(MAX_VOICES):
                if VS[k, V_ACTIVE] > 0.5:
                    VS[k, V_GATE] = 0.0
                    _release(VS, k)
            SST[SS_SUSTAIN] = 0.0


@njit(**JIT)
def _env_step(stage, level, att, dec, sus, rel):
    if stage == 1.0:
        level += att
        if level >= 1.0:
            level = 1.0
            stage = 2.0
    elif stage == 2.0:
        level += (sus - level) * dec
        if abs(level - sus) < 1e-4:
            stage = 3.0
    elif stage == 3.0:
        level = sus
    elif stage == 4.0:
        level -= level * rel
        if level < 1e-4:
            level = 0.0
            stage = 0.0
    return stage, level


@njit(**JIT)
def pulse_shape(ph, shape):
    """Envelope rítmico 0..1 dentro de um ciclo do pulso (ph = 0 no tempo)."""
    if shape == 0:      # "Pulso": cai no tempo e volta subindo (efeito sidechain)
        # a queda é uma curva suave (6% do ciclo); um degrau de 1 para 0 faria um clique
        duck = 0.06
        if ph < duck:
            return 0.5 + 0.5 * math.cos(math.pi * ph / duck)
        t = (ph - duck) / (1.0 - duck)
        return (1.0 - math.exp(-5.0 * t)) / (1.0 - math.exp(-5.0))
    if shape == 1:      # "Ondas": vai e volta suave
        return 0.5 - 0.5 * math.cos(TWO_PI * ph)
    # "Gate": nota picada (metade do tempo)
    return (1.0 - math.exp(-ph * 120.0)) / (1.0 + math.exp((ph - 0.5) * 60.0))


@njit(**JIT)
def render_synth(out, n, ev, nev, SD, VS, SST, fs):
    synth_events(ev, nev, VS, SST, SD[SY_PULSE_RETRIG] > 0.5)
    for i in range(n):
        out[i, 0] = 0.0

    wave1 = int(SD[SY_WAVE1])
    wave2 = int(SD[SY_WAVE2])
    mix2 = SD[SY_MIX2]
    sub = SD[SY_SUB]
    ratio2 = math.pow(2.0, SD[SY_SEMI2] / 12.0 + SD[SY_DETUNE] / 1200.0)
    cutoff = SD[SY_CUTOFF]
    k = 2.0 - 2.0 * SD[SY_RESO]
    fenv = SD[SY_FENV]
    keytrk = SD[SY_KEYTRK]
    lfo_depth = SD[SY_LFODEPTH] + SST[SS_MOD] * 1.5
    lfo_inc = SD[SY_LFORATE] / fs
    velsens = SD[SY_VELSENS]
    bend = math.pow(2.0, SST[SS_BEND] * SD[SY_BEND_RANGE] / 12.0)
    vol = SD[SY_VOL] * 0.18
    nyq = 0.45 * fs
    inv_fs = 1.0 / fs
    p_depth = SD[SY_PULSE_DEPTH]
    p_inc = SD[SY_PULSE_RATE] * inv_fs
    p_shape = int(SD[SY_PULSE_SHAPE])
    p_filt = SD[SY_PULSE_FILT]
    pph0 = SST[SS_PULSE]
    if SST[SS_PRESTART] > 0.5:           # Tap: recomeça o ciclo com 12 ms de transição
        pv = pulse_shape(pph0, p_shape)
        SST[SS_XFMUL] = 1.0 - p_depth * (1.0 - pv)
        SST[SS_XFOCT] = p_filt * (pv - 1.0)
        SST[SS_XF] = 0.012 * fs
        SST[SS_PRESTART] = 0.0
        pph0 = 0.0
    xf_len = 0.012 * fs
    xf_left = SST[SS_XF]
    xf_mul = SST[SS_XFMUL]
    xf_oct = SST[SS_XFOCT]

    lfo_ph0 = SST[SS_LFO]
    for v in range(MAX_VOICES):
        if VS[v, V_ACTIVE] < 0.5:
            continue
        f1 = VS[v, V_FREQ] * bend
        dt1 = f1 * inv_fs
        dt2 = dt1 * ratio2
        dts = dt1 * 0.5
        ph1 = VS[v, V_PH1]
        ph2 = VS[v, V_PH2]
        phs = VS[v, V_PHS]
        es = VS[v, V_ESTAGE]
        el = VS[v, V_ELEVEL]
        fsg = VS[v, V_FSTAGE]
        fl = VS[v, V_FLEVEL]
        ic1 = VS[v, V_IC1]
        ic2 = VS[v, V_IC2]
        vel = 1.0 - velsens + velsens * VS[v, V_VEL]
        key_oct = keytrk * (VS[v, V_NOTE] - 60.0) / 12.0
        lph = lfo_ph0
        pph = pph0
        for i in range(n):
            s = osc(ph1, dt1, wave1) * (1.0 - mix2) + osc(ph2, dt2, wave2) * mix2
            if sub > 0.0:
                s += sub * math.sin(TWO_PI * phs)
            ph1 += dt1
            if ph1 >= 1.0:
                ph1 -= 1.0
            ph2 += dt2
            if ph2 >= 1.0:
                ph2 -= 1.0
            phs += dts
            if phs >= 1.0:
                phs -= 1.0

            es, el = _env_step(es, el, SD[SY_AATT], SD[SY_ADEC], SD[SY_ASUS], SD[SY_AREL])
            fsg, fl = _env_step(fsg, fl, SD[SY_FATT], SD[SY_FDEC], SD[SY_FSUS], SD[SY_FREL])

            lfo = math.sin(TWO_PI * lph)
            lph += lfo_inc
            if lph >= 1.0:
                lph -= 1.0
            pmul = 1.0
            poct = 0.0
            if p_depth > 0.0:
                pv = pulse_shape(pph, p_shape)
                pmul = 1.0 - p_depth * (1.0 - pv)
                poct = p_filt * (pv - 1.0)
                pph += p_inc
                if pph >= 1.0:
                    pph -= 1.0
                if xf_left > i:
                    w = (xf_left - i) / xf_len
                    pmul = pmul * (1.0 - w) + xf_mul * w
                    poct = poct * (1.0 - w) + xf_oct * w
            fc = cutoff * math.pow(2.0, fenv * fl + lfo * lfo_depth + key_oct + poct)
            if fc > nyq:
                fc = nyq
            elif fc < 20.0:
                fc = 20.0
            # filtro de variáveis de estado TPT (Zavalishin), passa-baixa ressonante
            g = math.tan(math.pi * fc * inv_fs)
            a1 = 1.0 / (1.0 + g * (g + k))
            a2 = g * a1
            a3 = g * a2
            v3 = s - ic2
            v1 = a1 * ic1 + a2 * v3
            v2 = ic2 + a2 * ic1 + a3 * v3
            ic1 = 2.0 * v1 - ic1
            ic2 = 2.0 * v2 - ic2
            out[i, 0] += v2 * el * vel * vol * pmul
            if es == 0.0:
                break
        if es == 0.0:
            VS[v, V_ACTIVE] = 0.0
            VS[v, V_GATE] = 0.0
            VS[v, V_HELD] = 0.0
        VS[v, V_PH1] = ph1
        VS[v, V_PH2] = ph2
        VS[v, V_PHS] = phs
        VS[v, V_ESTAGE] = es
        VS[v, V_ELEVEL] = el
        VS[v, V_FSTAGE] = fsg
        VS[v, V_FLEVEL] = fl
        VS[v, V_IC1] = ic1 if abs(ic1) > 1e-15 else 0.0
        VS[v, V_IC2] = ic2 if abs(ic2) > 1e-15 else 0.0
    ph = lfo_ph0 + lfo_inc * n
    SST[SS_LFO] = ph - math.floor(ph)
    ph = pph0 + p_inc * n
    SST[SS_PULSE] = ph - math.floor(ph)
    SST[SS_XF] = max(0.0, xf_left - n)


def warmup(fs=48000.0):
    """Força a compilação (ou carga do cache) de todos os kernels antes de abrir o stream."""
    from .track import TrackDSP
    from .synth import SynthDSP

    from .params import EFFECTS

    t = TrackDSP(fs)
    for e in EFFECTS:
        t.set_on(e.key, True)
    n = 64
    src = np.zeros((n, 2), dtype=np.float32)
    src[:, 0] = 0.1
    mix = np.zeros((n, 2), dtype=np.float64)
    process_track(src, 0, n, mix, *t.arrays)
    process_pre(src, 0, n, *t.pre_arrays)
    process_post(n, mix, *t.post_arrays)
    t.set_cab_ir(np.array([1.0, 0.5, 0.25]))
    process_track(src, 0, n, mix, *t.arrays)
    out = np.zeros((n, 2), dtype=np.float32)
    write_output(mix, n, out, 0, 1.0)
    so = np.zeros((n, 1), dtype=np.float32)
    sh = np.zeros(n)
    kb = np.zeros((n, 2))
    for chain in (True, False):
        mix_soundfont(np.zeros((24, n), dtype=np.float32), n, mix, so, sh, kb, chain, 1.0, 1.0, 1.0,
                      0.5, 0.5)
    from .keysfx import warmup as warmup_keysfx
    from .worship import warmup as warmup_worship

    warmup_worship(fs)
    warmup_keysfx(fs)
    s = SynthDSP(fs)
    ev = np.zeros((4, 3), dtype=np.int32)
    ev[0] = (EV_NOTE_ON, 60, 100)
    render_synth(so, n, ev, 1, s.SD, s.VS, s.SST, fs)
