"""Trilha Vocal (microfone): cadeia de efeitos de voz, sem amplificador nem gabinete.

    Entrada (ganho, inverter fase, medidor e clip) -> Filtro de graves -> Noise gate -> Compressor
    -> EQ de voz -> De-esser -> [mono -> estéreo] -> (plugins, se "antes") -> Dobra -> Delay -> Reverb
    -> (plugins, se "no fim") -> Volume/Pan/Mute -> soma na mixagem

Tudo roda no callback de áudio em Numba, sem alocação e sem lookahead (latência de algoritmo zero:
cada amostra sai no mesmo bloco em que entrou). Como em dsp/track.py, a thread de interface calcula os
valores derivados (ganhos lineares, coeficientes, tempos em amostras) e grava em VP; os kernels só leem
VP/BQ e mexem no estado (VS, Z e buffers), tudo pré-alocado no VocalChain.

A cadeia de plugins VST3 é a mesma das outras partes do app (audio/vst.py, PluginChain, em
`VocalChain.fx_chain`, salva em get_state()["fx_chain"] como nas trilhas): ela processa o buffer estéreo
KB [n, 2] no ponto escolhido em values["track"]["plug_pos"]. O reverb é o mesmo Freeverb das trilhas (kernels.fx_reverb), alimentado
por um envio com pré-delay e filtros.

Proteção: a saída da trilha continua passando pelo compressor/limitador do Master (write_output_lim).
Um "anti-microfonia" automático (detectar e cortar a frequência que apita) ficou de fora de propósito:
os métodos simples confundem nota cantada sustentada com microfonia e cortam a voz no meio do culto.
"""
import copy
import math

import numpy as np
from numba import njit

from . import layout as Ly
from .filters import IDENTITY, biquad, db, onepole_coef
from .kernels import JIT, flush_denormals, fx_reverb
from .params import EffectDef, Param

TWO_PI = 2.0 * math.pi

# ======================================================================= parâmetros (o que a tela mostra)
HPF_SLOPES = ("Suave (12 dB/oitava)", "Forte (24 dB/oitava)")
COMP_SPEEDS = ("Ataque suave", "Ataque normal", "Ataque rápido")
COMP_TIMES = ((0.010, 0.250), (0.005, 0.140), (0.002, 0.070))      # (ataque, volta) em segundos
DELAY_SYNC = ("Tempo livre (ms)", "BPM: 1/4", "BPM: 1/8", "BPM: 1/8 pontuada", "BPM: 1/4 pontuada",
              "BPM: 1/2")
DELAY_MODES = ("Mono", "Ping-pong")
DELAY_BEATS = (0.0, 1.0, 0.5, 0.75, 1.5, 2.0)
REVERB_TYPES = ("Sala", "Hall", "Placa")
PLUG_POS = ("Antes da dobra/delay/reverb", "No fim da cadeia")
DELAY_MAX_MS = 2000.0
PREDELAY_MAX_MS = 120.0

VOCAL_EFFECTS = (
    EffectDef("hpf", "Filtro de graves", (
        Param("freq", "Corte", 60, 200, 100, "Hz", log=True),
        Param("slope", "Inclinação", 0, 1, 1, choices=HPF_SLOPES),
    )),
    EffectDef("gate", "Noise gate", (
        Param("threshold", "Limiar", -80, -20, -52, "dB"),
        Param("range", "Redução", 6, 80, 30, "dB"),
        Param("release", "Volta", 20, 1000, 180, "ms", log=True),
    )),
    EffectDef("comp", "Compressor vocal", (
        Param("amount", "Quantidade", 0, 100, 40, "%"),
        Param("gain", "Ganho extra", -6, 12, 0, "dB"),
        Param("speed", "Velocidade", 0, 2, 1, choices=COMP_SPEEDS),
    )),
    EffectDef("eq", "EQ de voz", (
        Param("low", "Graves", -12, 12, 0, "dB"),
        Param("body", "Corpo", -12, 12, 0, "dB"),
        Param("presence", "Presença", -12, 12, 0, "dB"),
        Param("air", "Brilho", -12, 12, 0, "dB"),
        Param("highcut", "Corte agudo", 3000, 20000, 20000, "Hz", log=True),
    )),
    EffectDef("deess", "De-esser (suaviza o “S”)", (
        Param("amount", "Quantidade", 0, 100, 50, "%"),
        Param("freq", "Frequência", 4000, 10000, 6500, "Hz", log=True),
    )),
    EffectDef("double", "Dobra (doubler)", (
        Param("mix", "Quantidade", 0, 100, 40, "%"),
        Param("width", "Largura", 0, 100, 80, "%"),
    )),
    EffectDef("delay", "Delay", (
        Param("time", "Tempo", 60, 1500, 320, "ms", log=True),
        Param("sync", "No BPM", 0, len(DELAY_SYNC) - 1, 0, choices=DELAY_SYNC),
        Param("feedback", "Repetições", 0, 85, 25, "%"),
        Param("mix", "Mix", 0, 100, 18, "%"),
        Param("ping", "Ping-pong", 0, 1, 0, choices=DELAY_MODES),
    )),
    EffectDef("reverb", "Reverb", (
        Param("type", "Tipo", 0, len(REVERB_TYPES) - 1, 1, choices=REVERB_TYPES),
        Param("size", "Tamanho", 0, 100, 55, "%"),
        Param("predelay", "Pré-delay", 0, PREDELAY_MAX_MS, 20, "ms"),
        Param("mix", "Mix", 0, 100, 20, "%"),
    )),
)
VOCAL_EFFECT_BY_KEY = {e.key: e for e in VOCAL_EFFECTS}

VOCAL_TRACK_PARAMS = (
    Param("input_gain", "Entrada", -24, 36, 0, "dB"),
    Param("volume", "Volume", -60, 12, 0, "dB"),
    Param("pan", "Pan", -100, 100, 0, ""),
)
PLUG_POS_PARAM = Param("plug_pos", "Plugins", 0, 1, 0, choices=PLUG_POS)
TRACK_SWITCHES = ("on", "mute", "phase")      # booleanos de values["track"]

# ======================================================================= layout dos arrays
# VP: valores derivados (escritos pela interface, lidos pelo áudio)
(P_INGAIN, P_GL, P_GR, P_SMOOTH,
 P_HPF_ON, P_HPF_N,
 P_G_ON, P_G_THR, P_G_CLOSE, P_G_FLOOR, P_G_ATT, P_G_REL, P_G_HOLD, P_G_DET,
 P_C_ON, P_C_THR, P_C_SLOPE, P_C_ATT, P_C_REL, P_C_MAKEUP,
 P_EQ_ON, P_EQ_LP,
 P_DS_ON, P_DS_THR, P_DS_MAX, P_DS_EATT, P_DS_EREL, P_DS_GATT, P_DS_GREL, P_DS_FLOOR,
 P_DB_ON, P_DB_MIX, P_DB_WIDTH, P_DB_BASE1, P_DB_BASE2, P_DB_DEPTH, P_DB_RATE1, P_DB_RATE2,
 P_DL_ON, P_DL_TIME, P_DL_FB, P_DL_MIX, P_DL_DAMP, P_DL_PING,
 P_RV_ON, P_RV_PRE, P_RV_DRY,
 P_PLUG_POS, _P_FREE, P_DS_CW, P_DS_AL, P_C_FAST) = range(52)
VP_SIZE = 64

# VS: estado escalar
(S_GIN, S_GL, S_GR, S_PEAK_IN, S_PEAK_OUT, S_CLIP,
 S_G_ENV, S_G_GAIN, S_G_OPEN, S_G_HOLD,
 S_C_GR, S_C_GRMAX,
 S_DS_EH, S_DS_EF, S_DS_G, S_DS_GMIN,
 S_DB_PH1, S_DB_PH2, S_DB_POS,
 S_DL_POS, S_DL_LPL, S_DL_LPR,
 S_PD_POS, S_BAD) = range(24)
VS_SIZE = 32

# biquads (BQ/Z)
BQ_HPF1, BQ_HPF2 = 0, 1
BQ_EQ_LOW, BQ_EQ_BODY, BQ_EQ_PRES, BQ_EQ_AIR, BQ_EQ_LP = 2, 3, 4, 5, 6
BQ_DS = 7
BQ_DL_HPL, BQ_DL_HPR = 8, 9
BQ_RV_HP, BQ_RV_LP = 10, 11
BQ_DS_SHELF = 12                # só o estado (Z): os coeficientes do shelf dinâmico são calculados no kernel
NBQ = 13

EQ_FREQS = dict(low=150.0, body=400.0, presence=3200.0, air=10000.0)

# reverb por tipo: (sala base, sala extra pelo Tamanho, abafar, largura, corte grave do envio, corte agudo)
REVERB_VOICING = (
    (0.70, 0.17, 0.45, 0.80, 220.0, 7000.0),     # Sala: curta e quente
    (0.80, 0.18, 0.30, 1.00, 180.0, 9000.0),     # Hall: longa e aberta
    (0.78, 0.19, 0.12, 1.00, 300.0, 12000.0),    # Placa: brilhante, sem graves embolando
)


def default_values():
    vals = {e.key: {p.key: p.default for p in e.params} for e in VOCAL_EFFECTS}
    for e in VOCAL_EFFECTS:
        vals[e.key]["on"] = False
    tr = {p.key: p.default for p in VOCAL_TRACK_PARAMS}
    # desligada por padrão: abrir o app (ou uma sessão antiga) não liga o microfone sem querer
    tr.update(on=False, mute=False, phase=False, plug_pos=PLUG_POS_PARAM.default)
    vals["track"] = tr
    return vals


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def clean_values(d):
    """Valores vindos de arquivo (sessão, preset, tela remota): só chaves conhecidas, com tipo e faixa
    válidos, sobre os padrões. Nunca lança exceção."""
    out = default_values()
    if not isinstance(d, dict):
        return out
    groups = [(e.key, e.params) for e in VOCAL_EFFECTS] + [("track", VOCAL_TRACK_PARAMS + (PLUG_POS_PARAM,))]
    for key, params in groups:
        src = d.get(key)
        if not isinstance(src, dict):
            continue
        for p in params:
            v = src.get(p.key)
            if _num(v):
                v = float(min(max(v, p.lo), p.hi))
                out[key][p.key] = float(round(v)) if p.is_choice or p.step else v
        bools = TRACK_SWITCHES if key == "track" else ("on",)
        for b in bools:
            if isinstance(src.get(b), bool):
                out[key][b] = src[b]
    return out


def latency_note(blocksize, fs):
    """Aviso para a aba Vocal quando o buffer da placa deixa a voz no retorno atrasada (ou "")."""
    ms = 1000.0 * blocksize / max(float(fs), 1.0)
    if ms <= 10.7:            # até 512 amostras a 48 kHz
        return ""
    return (f"Buffer da placa em {int(blocksize)} amostras (~{ms:.0f} ms por bloco): quem canta ouve a "
            "própria voz atrasada no retorno. Para o vocal, use 128 ou 256 no ⚙ Áudio.")


def _next_pow2(n):
    return 1 << max(0, int(math.ceil(math.log2(max(n, 1)))))


# ======================================================================= kernels (tempo real)
@njit(**JIT)
def _bq(x, BQ, Z, i):
    y = BQ[i, 0] * x + Z[i, 0]
    Z[i, 0] = BQ[i, 1] * x - BQ[i, 3] * y + Z[i, 1]
    Z[i, 1] = BQ[i, 2] * x - BQ[i, 4] * y
    return y


@njit(**JIT)
def v_input(src, ch, n, x, VP, VS):
    """Ganho de entrada (com rampa) e fase; medidor de pico e indicador de clip."""
    tgt = VP[P_INGAIN]
    c = VP[P_SMOOTH]
    g = VS[S_GIN]
    pk = VS[S_PEAK_IN]
    clip = VS[S_CLIP]
    for i in range(n):
        if g != tgt:
            g += (tgt - g) * c
            if abs(tgt - g) < 1e-7:
                g = tgt
        raw = src[i, ch]
        v = raw * g
        a = abs(v)
        if a > pk:
            pk = a
        if a >= 1.0 or abs(raw) >= 0.999:      # passou do máximo (no app) ou já chegou cortado da placa
            clip = 1.0
        x[i] = v
    VS[S_GIN] = g
    VS[S_PEAK_IN] = pk
    VS[S_CLIP] = clip


@njit(**JIT)
def v_hpf(x, n, VP, BQ, Z):
    two = VP[P_HPF_N] > 1.5
    for i in range(n):
        v = _bq(x[i], BQ, Z, BQ_HPF1)
        if two:
            v = _bq(v, BQ, Z, BQ_HPF2)
        x[i] = v


@njit(**JIT)
def v_gate(x, n, VP, VS):
    """Abre quando o nível RMS passa do limiar; fecha 3 dB abaixo dele depois de um tempo de espera (não
    corta o fim das palavras) e abaixa até a "Redução" (não muta: respiração e fim de frase continuam
    naturais). O detector é a média quadrática (RMS de ~8 ms, subida e descida iguais): o chiado de fundo
    fica no nível RMS dele, sem picos que segurem o gate aberto."""
    thr = VP[P_G_THR]
    close = VP[P_G_CLOSE]
    floor = VP[P_G_FLOOR]
    att = VP[P_G_ATT]
    rel = VP[P_G_REL]
    hold = VP[P_G_HOLD]
    det = VP[P_G_DET]
    env = VS[S_G_ENV]               # média quadrática (comparada com os limiares ao quadrado)
    g = VS[S_G_GAIN]
    is_open = VS[S_G_OPEN]
    hc = VS[S_G_HOLD]
    for i in range(n):
        v = x[i]
        env += (v * v - env) * det
        if env > thr:
            is_open = 1.0
            hc = hold
        elif is_open > 0.5:
            if env < close:
                hc -= 1.0
                if hc <= 0.0:
                    is_open = 0.0
            else:
                hc = hold
        if is_open > 0.5:
            g += (1.0 - g) * att
        else:
            g += (floor - g) * rel
        x[i] *= g
    VS[S_G_ENV] = env if env > 1e-20 else 0.0
    VS[S_G_GAIN] = g
    VS[S_G_OPEN] = is_open
    VS[S_G_HOLD] = hc


@njit(**JIT)
def v_comp(x, n, VP, VS):
    """Compressor de pico no domínio dB (joelho de 6 dB), ganho suavizado com ataque/volta; guarda a maior
    redução desde a última leitura para o medidor."""
    thr = VP[P_C_THR]
    slope = VP[P_C_SLOPE]
    att = VP[P_C_ATT]
    rel = VP[P_C_REL]
    mk = VP[P_C_MAKEUP]
    fast = VP[P_C_FAST]
    knee = 6.0
    half = 3.0
    gr = VS[S_C_GR]
    grmax = VS[S_C_GRMAX]
    for i in range(n):
        v = x[i]
        over = 20.0 * math.log10(abs(v) + 1e-9) - thr
        if over <= -half:
            t = 0.0
        elif over < half:
            k = over + half
            t = slope * k * k / (2.0 * knee)
        else:
            t = slope * over
        if t > gr:
            # pico muito acima (grito, batida no microfone): ataque rápido para não estourar com o ganho
            # de compensação; subidas normais usam o ataque da Velocidade
            gr += (t - gr) * (fast if t - gr > 6.0 else att)
        else:
            gr += (t - gr) * rel
        if gr < 1e-6:
            gr = 0.0
            x[i] = v * mk
        else:
            if gr > grmax:
                grmax = gr
            x[i] = v * math.pow(10.0, -0.05 * gr) * mk
    VS[S_C_GR] = gr
    VS[S_C_GRMAX] = grmax


@njit(**JIT)
def v_eq(x, n, VP, BQ, Z):
    lp = VP[P_EQ_LP] > 0.5
    for i in range(n):
        v = _bq(x[i], BQ, Z, BQ_EQ_LOW)
        v = _bq(v, BQ, Z, BQ_EQ_BODY)
        v = _bq(v, BQ, Z, BQ_EQ_PRES)
        v = _bq(v, BQ, Z, BQ_EQ_AIR)
        if lp:
            v = _bq(v, BQ, Z, BQ_EQ_LP)
        x[i] = v


@njit(**JIT)
def v_deess(x, n, VP, VS, BQ, Z):
    """De-esser: um passa-altas na Frequência só para detectar o "S" (agudos dominando o sinal); quando
    detecta, um shelf de agudos (abaixo da Frequência) abaixa na hora e volta devagar. Vogais e consoantes
    graves passam intactas. Shelf em 0 dB é exatamente o sinal de entrada (b = a)."""
    thr = VP[P_DS_THR]
    mx = VP[P_DS_MAX]
    eatt = VP[P_DS_EATT]
    erel = VP[P_DS_EREL]
    gatt = VP[P_DS_GATT]
    grel = VP[P_DS_GREL]
    floor = VP[P_DS_FLOOR]
    cw = VP[P_DS_CW]
    al = VP[P_DS_AL]
    eh = VS[S_DS_EH]
    ef = VS[S_DS_EF]
    g = VS[S_DS_G]
    gmin = VS[S_DS_GMIN]
    z0 = Z[BQ_DS_SHELF, 0]
    z1 = Z[BQ_DS_SHELF, 1]
    for i in range(n):
        v = x[i]
        h = _bq(v, BQ, Z, BQ_DS)
        ah = abs(h)
        af = abs(v)
        eh += (ah - eh) * (eatt if ah > eh else erel)
        ef += (af - ef) * (eatt if af > ef else erel)
        tgt = 1.0
        if ef > floor:
            r = 20.0 * math.log10((eh + 1e-12) / (ef + 1e-12)) - thr
            if r > 0.0:
                red = r * 2.0
                if red > mx:
                    red = mx
                tgt = math.pow(10.0, -0.05 * red)
        g += (tgt - g) * (gatt if tgt < g else grel)
        if g > 1.0 - 1e-7:
            g = 1.0
            if z0 == 0.0 and z1 == 0.0:
                continue                       # x[i] fica igual (bit a bit)
        if g < gmin:
            gmin = g
        # shelf de agudos (RBJ) com ganho g: A = sqrt(g), sqrt(A) = g ** 0.25
        A = math.sqrt(g)
        sq = 2.0 * math.sqrt(A) * al
        ap = A + 1.0
        am = A - 1.0
        ia0 = 1.0 / (ap - am * cw + sq)
        b0 = A * (ap + am * cw + sq) * ia0
        b1 = -2.0 * A * (am + ap * cw) * ia0
        b2 = A * (ap + am * cw - sq) * ia0
        a1 = 2.0 * (am - ap * cw) * ia0
        a2 = (ap - am * cw - sq) * ia0
        y = b0 * v + z0
        z0 = b1 * v - a1 * y + z1
        z1 = b2 * v - a2 * y
        if g == 1.0 and abs(z0) < 1e-12 and abs(z1) < 1e-12:
            z0 = 0.0
            z1 = 0.0
        x[i] = y
    Z[BQ_DS_SHELF, 0] = z0
    Z[BQ_DS_SHELF, 1] = z1
    VS[S_DS_EH] = eh if eh > 1e-20 else 0.0
    VS[S_DS_EF] = ef if ef > 1e-20 else 0.0
    VS[S_DS_G] = g
    VS[S_DS_GMIN] = gmin


@njit(**JIT)
def v_pre(src, ch, n, VP, VS, BQ, Z, X, KB):
    """Parte mono: entrada -> filtro de graves -> gate -> compressor -> EQ -> de-esser -> KB (L = R)."""
    v_input(src, ch, n, X, VP, VS)
    if VP[P_HPF_ON] > 0.5:
        v_hpf(X, n, VP, BQ, Z)
    if VP[P_G_ON] > 0.5:
        v_gate(X, n, VP, VS)
    if VP[P_C_ON] > 0.5:
        v_comp(X, n, VP, VS)
    if VP[P_EQ_ON] > 0.5:
        v_eq(X, n, VP, BQ, Z)
    if VP[P_DS_ON] > 0.5:
        v_deess(X, n, VP, VS, BQ, Z)
    for i in range(n):
        KB[i, 0] = X[i]
        KB[i, 1] = X[i]


@njit(**JIT)
def _frac_read(buf, mask, pos_f):
    il = int(math.floor(pos_f))
    fr = pos_f - il
    return buf[il & mask] * (1.0 - fr) + buf[(il + 1) & mask] * fr


@njit(**JIT)
def v_double(KB, n, VP, VS, DBB):
    """Duas cópias da voz com atraso curto (12 e 19 ms) que oscila devagar (pequena variação de afinação
    e tempo, como uma segunda tomada), abertas para os lados conforme a Largura."""
    mix = VP[P_DB_MIX]
    width = VP[P_DB_WIDTH]
    b1 = VP[P_DB_BASE1]
    b2 = VP[P_DB_BASE2]
    dep = VP[P_DB_DEPTH]
    r1 = VP[P_DB_RATE1]
    r2 = VP[P_DB_RATE2]
    near = 0.5 * (1.0 + width) * mix
    far = 0.5 * (1.0 - width) * mix
    mask = DBB.shape[0] - 1
    ph1 = VS[S_DB_PH1]
    ph2 = VS[S_DB_PH2]
    pos = int(VS[S_DB_POS])
    for i in range(n):
        m = (KB[i, 0] + KB[i, 1]) * 0.5
        DBB[pos] = m
        d1 = b1 + dep * (0.5 + 0.5 * math.sin(TWO_PI * ph1))
        d2 = b2 + dep * (0.5 + 0.5 * math.sin(TWO_PI * ph2))
        a = _frac_read(DBB, mask, pos - d1)
        b = _frac_read(DBB, mask, pos - d2)
        KB[i, 0] += a * near + b * far
        KB[i, 1] += a * far + b * near
        pos = (pos + 1) & mask
        ph1 += r1
        if ph1 >= 1.0:
            ph1 -= 1.0
        ph2 += r2
        if ph2 >= 1.0:
            ph2 -= 1.0
    VS[S_DB_PH1] = ph1
    VS[S_DB_PH2] = ph2
    VS[S_DB_POS] = pos


@njit(**JIT)
def v_delay(KB, n, VP, VS, BQ, Z, DLB):
    """Delay com as repetições mais escuras e sem graves (ficam atrás da voz). Ping-pong opcional."""
    size = DLB.shape[1]
    mask = size - 1
    t = int(VP[P_DL_TIME])
    if t >= size:
        t = size - 1
    if t < 1:
        t = 1
    fb = VP[P_DL_FB]
    mix = VP[P_DL_MIX]
    damp = VP[P_DL_DAMP]
    ping = VP[P_DL_PING] > 0.5
    pos = int(VS[S_DL_POS])
    lpl = VS[S_DL_LPL]
    lpr = VS[S_DL_LPR]
    for i in range(n):
        rd = (pos - t) & mask
        lpl += (DLB[0, rd] - lpl) * damp
        lpr += (DLB[1, rd] - lpr) * damp
        el = _bq(lpl, BQ, Z, BQ_DL_HPL)
        er = _bq(lpr, BQ, Z, BQ_DL_HPR)
        m = (KB[i, 0] + KB[i, 1]) * 0.5
        if ping:
            DLB[0, pos] = m + er * fb
            DLB[1, pos] = el * fb
        else:
            DLB[0, pos] = m + el * fb
            DLB[1, pos] = m + er * fb
        KB[i, 0] += el * mix
        KB[i, 1] += er * mix
        pos = (pos + 1) & mask
    VS[S_DL_POS] = pos
    VS[S_DL_LPL] = lpl if abs(lpl) > 1e-15 else 0.0
    VS[S_DL_LPR] = lpr if abs(lpr) > 1e-15 else 0.0


@njit(**JIT)
def v_reverb(KB, n, VP, VS, BQ, Z, PDB, RW, RVD, RVB, RVOFF, RVLEN, RVPOS, RVFS):
    """Envio (pré-delay + corte de graves/agudos) -> Freeverb do app (só o molhado) -> soma na voz."""
    mask = PDB.shape[0] - 1
    pre = int(VP[P_RV_PRE])
    if pre > mask:
        pre = mask
    pos = int(VS[S_PD_POS])
    L = RW[0]
    R = RW[1]
    for i in range(n):
        PDB[pos] = (KB[i, 0] + KB[i, 1]) * 0.5
        s = PDB[(pos - pre) & mask]
        s = _bq(s, BQ, Z, BQ_RV_HP)
        s = _bq(s, BQ, Z, BQ_RV_LP)
        L[i] = s
        R[i] = s
        pos = (pos + 1) & mask
    VS[S_PD_POS] = pos
    fx_reverb(L, R, n, RVD, RVB, RVOFF, RVLEN, RVPOS, RVFS)
    dry = VP[P_RV_DRY]
    for i in range(n):
        KB[i, 0] = KB[i, 0] * dry + L[i]
        KB[i, 1] = KB[i, 1] * dry + R[i]


@njit(**JIT)
def v_ambient(n, VP, VS, BQ, Z, KB, DBB, DLB, PDB, RW, RVD, RVB, RVOFF, RVLEN, RVPOS, RVFS):
    """Parte estéreo: dobra -> delay -> reverb."""
    if VP[P_DB_ON] > 0.5:
        v_double(KB, n, VP, VS, DBB)
    if VP[P_DL_ON] > 0.5:
        v_delay(KB, n, VP, VS, BQ, Z, DLB)
    if VP[P_RV_ON] > 0.5:
        v_reverb(KB, n, VP, VS, BQ, Z, PDB, RW, RVD, RVB, RVOFF, RVLEN, RVPOS, RVFS)


@njit(**JIT)
def v_out(n, mix, VP, VS, Z, KB):
    """Volume/pan/mute (com rampa, sem estalo) e soma na mixagem. Amostra inválida (NaN/inf de um
    plugin, por exemplo) vira silêncio e marca S_BAD para o estado ser zerado no próximo bloco."""
    tl = VP[P_GL]
    tr = VP[P_GR]
    c = VP[P_SMOOTH]
    gl = VS[S_GL]
    gr = VS[S_GR]
    pk = VS[S_PEAK_OUT]
    bad = False
    for i in range(n):
        if gl != tl:
            gl += (tl - gl) * c
            if abs(tl - gl) < 1e-7:
                gl = tl
        if gr != tr:
            gr += (tr - gr) * c
            if abs(tr - gr) < 1e-7:
                gr = tr
        l = KB[i, 0] * gl
        r = KB[i, 1] * gr
        if not (abs(l) < 1e6 and abs(r) < 1e6):
            l = 0.0
            r = 0.0
            bad = True
        mix[i, 0] += l
        mix[i, 1] += r
        a = max(abs(l), abs(r))
        if a > pk:
            pk = a
    VS[S_GL] = gl
    VS[S_GR] = gr
    VS[S_PEAK_OUT] = pk
    if bad:
        VS[S_BAD] = 1.0
    flush_denormals(Z)


@njit(**JIT)
def process_vocal(src, ch, n, mix, VP, VS, BQ, Z, X, KB, DBB, DLB, PDB, RW, RVD, RVB, RVOFF, RVLEN, RVPOS,
                  RVFS):
    """Cadeia inteira numa chamada (sem plugins na trilha)."""
    v_pre(src, ch, n, VP, VS, BQ, Z, X, KB)
    v_ambient(n, VP, VS, BQ, Z, KB, DBB, DLB, PDB, RW, RVD, RVB, RVOFF, RVLEN, RVPOS, RVFS)
    v_out(n, mix, VP, VS, Z, KB)


# ======================================================================= estado da trilha
class VocalChain:
    """Trilha Vocal: valores dos controles (values), arrays de DSP e a ponte para a thread de áudio.

    Mesma interface pública do TrackDSP onde faz sentido (values["track"], set_param, set_on, get_state,
    load_state, meters, reset_dsp_state), para a mesa, a tela remota e a sessão tratarem as trilhas igual.
    """

    def __init__(self, fs=48000.0, max_block=Ly.MAX_BLOCK):
        self.fs = float(fs)
        self.max_block = int(max_block)
        self.values = default_values()
        self.bpm = 120.0
        from ..audio.vst import PluginChain
        self.fx_chain = PluginChain(self.fs, self.max_block, "Vocal")     # cadeia FX (plugins VST3)

        fs = self.fs
        self.VP = np.zeros(VP_SIZE)
        self.VS = np.zeros(VS_SIZE)
        self.BQ = np.zeros((NBQ, 5))
        self.BQ[:] = IDENTITY
        self.Z = np.zeros((NBQ, 2))
        self.X = np.zeros(self.max_block)
        self.KB = np.zeros((self.max_block, 2))
        self.RW = np.zeros((2, self.max_block))
        self.DBB = np.zeros(_next_pow2(int(0.035 * fs) + 4))
        self.DLB = np.zeros((2, _next_pow2(int(DELAY_MAX_MS / 1000.0 * fs) + 2)))
        self.PDB = np.zeros(_next_pow2(int(PREDELAY_MAX_MS / 1000.0 * fs) + 2))
        # reverb: mesmas linhas do Freeverb das trilhas (dsp/track.py)
        scale = fs / 44100.0
        lens = []
        for side in range(2):
            lens += [max(1, int((t + Ly.RV_STEREO_SPREAD * side) * scale)) for t in Ly.RV_COMB_TUNING]
        for side in range(2):
            lens += [max(1, int((t + Ly.RV_STEREO_SPREAD * side) * scale)) for t in Ly.RV_AP_TUNING]
        self.RVLEN = np.array(lens, dtype=np.int64)
        self.RVOFF = np.concatenate(([0], np.cumsum(self.RVLEN)[:-1])).astype(np.int64)
        self.RVB = np.zeros(int(self.RVLEN.sum()))
        self.RVPOS = np.zeros(Ly.RV_UNITS, dtype=np.int64)
        self.RVFS = np.zeros(2 * Ly.RV_COMBS)
        self.RVD = np.zeros(Ly.D_SIZE)          # parâmetros do fx_reverb (índices RV_* do layout)
        self.pre_arrays = (self.VP, self.VS, self.BQ, self.Z, self.X, self.KB)
        self.amb_arrays = (self.VP, self.VS, self.BQ, self.Z, self.KB, self.DBB, self.DLB, self.PDB, self.RW,
                           self.RVD, self.RVB, self.RVOFF, self.RVLEN, self.RVPOS, self.RVFS)
        self.out_arrays = (self.VP, self.VS, self.Z, self.KB)
        self.arrays = (self.VP, self.VS, self.BQ, self.Z, self.X, self.KB, self.DBB, self.DLB, self.PDB,
                       self.RW, self.RVD, self.RVB, self.RVOFF, self.RVLEN, self.RVPOS, self.RVFS)
        self.reset_dsp_state()
        self.update_all()
        self._snap_gains()

    # ------------------------------------------------------------------ API pública
    @property
    def on(self):
        return bool(self.values["track"]["on"])

    @property
    def running(self):
        """O motor chama process(): ligada, ou ainda terminando a rampa de desligar."""
        return self.on or self.VS[S_GL] != 0.0 or self.VS[S_GR] != 0.0

    def set_param(self, effect, key, value):
        if effect == "track" and key in TRACK_SWITCHES:
            self.set_switch(key, value)
            return
        self.values[effect][key] = value
        self._update(effect)

    def set_on(self, effect, on):
        if effect == "track":
            self.set_switch("on", on)
            return
        was = self.values[effect]["on"]
        self.values[effect]["on"] = bool(on)
        if on and not was:
            self._reset_effect(effect)        # religar sem a cauda/estado antigo
        self._update(effect)

    def set_switch(self, key, value):
        """Liga/desliga da trilha, mute e inverter fase (com rampa no áudio)."""
        value = bool(value)
        tr = self.values["track"]
        if key == "on" and value and not tr["on"] and not self.running:
            self.reset_dsp_state()            # parada de verdade: religa sem a cauda antiga
        tr[key] = value
        self._update("track")

    def set_bpm(self, bpm):
        self.bpm = float(bpm)
        if int(round(self.values["delay"]["sync"])):
            self._update("delay")

    def get_state(self):
        return {"values": copy.deepcopy(self.values), "fx_chain": self.fx_chain.to_list()}

    def load_state(self, state):
        """Sessão/preset completo. Chaves desconhecidas e valores fora da faixa são ignorados/corrigidos.
        Sem "fx_chain" (preset sem plugins, sessão antiga): a trilha fica sem plugins, como no TrackDSP."""
        state = state if isinstance(state, dict) else {}
        was_running = self.running
        old = self.values
        self.values = clean_values(state.get("values", {}))
        if not was_running:
            self.reset_dsp_state()
        else:
            for e in VOCAL_EFFECTS:           # efeito que liga agora começa sem estado antigo
                if self.values[e.key]["on"] and not old[e.key]["on"]:
                    self._reset_effect(e.key)
        self.fx_chain.apply(state.get("fx_chain", []))
        self.update_all()

    def apply_preset(self, preset):
        """Preset de voz (efeitos e plugins): mantém liga/desliga, volume e ganho de entrada."""
        preset = preset if isinstance(preset, dict) else {}
        vals = dict(preset.get("values", {})) if isinstance(preset.get("values"), dict) else {}
        vals["track"] = copy.deepcopy(self.values["track"])
        self.load_state({"values": vals, "fx_chain": preset.get("fx_chain", [])})

    def meters(self):
        """Lê e zera os picos (entrada, saída) desde a última leitura (mesmo formato do TrackDSP)."""
        VS = self.VS
        pin, pout = float(VS[S_PEAK_IN]), float(VS[S_PEAK_OUT])
        VS[S_PEAK_IN] = 0.0
        VS[S_PEAK_OUT] = 0.0
        return pin, pout

    def dyn_meters(self):
        """Lê e zera (redução do compressor em dB, redução do de-esser em dB, gate aberto, clip)."""
        VS = self.VS
        gr = float(VS[S_C_GRMAX]) if self.values["comp"]["on"] else 0.0
        gmin = float(VS[S_DS_GMIN])
        ds = -20.0 * math.log10(gmin) if 0.0 < gmin < 1.0 and self.values["deess"]["on"] else 0.0
        gate_open = (not self.values["gate"]["on"]) or VS[S_G_OPEN] > 0.5
        clip = VS[S_CLIP] > 0.5
        VS[S_C_GRMAX] = 0.0
        VS[S_DS_GMIN] = 1.0
        VS[S_CLIP] = 0.0
        return gr, ds, bool(gate_open), bool(clip)

    def reset_dsp_state(self):
        """Zera filtros, envelopes e linhas de atraso (stream parado ou trilha parada)."""
        for a in (self.Z, self.X, self.KB, self.RW, self.DBB, self.DLB, self.PDB, self.RVB, self.RVFS):
            a[:] = 0.0
        self.RVPOS[:] = 0
        VS = self.VS
        keep = VS[S_GIN], VS[S_GL], VS[S_GR]
        VS[:] = 0.0
        VS[S_GIN], VS[S_GL], VS[S_GR] = keep
        VS[S_G_GAIN] = 1.0
        VS[S_G_OPEN] = 1.0
        VS[S_DS_G] = 1.0
        VS[S_DS_GMIN] = 1.0
        VS[S_DB_PH2] = 0.37

    def _reset_effect(self, effect):
        VS, Z = self.VS, self.Z
        if effect == "hpf":
            Z[BQ_HPF1:BQ_HPF2 + 1] = 0.0
        elif effect == "gate":
            VS[S_G_ENV] = 0.0
            VS[S_G_GAIN] = 1.0
            VS[S_G_OPEN] = 1.0
            VS[S_G_HOLD] = 0.0
        elif effect == "comp":
            VS[S_C_GR] = 0.0
        elif effect == "eq":
            Z[BQ_EQ_LOW:BQ_EQ_LP + 1] = 0.0
        elif effect == "deess":
            Z[BQ_DS] = 0.0
            Z[BQ_DS_SHELF] = 0.0
            VS[S_DS_EH] = VS[S_DS_EF] = 0.0
            VS[S_DS_G] = 1.0
        elif effect == "double":
            self.DBB[:] = 0.0
        elif effect == "delay":
            self.DLB[:] = 0.0
            Z[BQ_DL_HPL:BQ_DL_HPR + 1] = 0.0
            VS[S_DL_LPL] = VS[S_DL_LPR] = 0.0
        elif effect == "reverb":
            self.PDB[:] = 0.0
            self.RVB[:] = 0.0
            self.RVFS[:] = 0.0
            Z[BQ_RV_HP:BQ_RV_LP + 1] = 0.0

    def _snap_gains(self):
        """Ganhos já no valor final (sem rampa): construção e testes."""
        self.VS[S_GIN] = self.VP[P_INGAIN]
        self.VS[S_GL] = self.VP[P_GL]
        self.VS[S_GR] = self.VP[P_GR]

    # ------------------------------------------------------------------ áudio (tempo real)
    def process(self, src, ch, n, mix):
        """Thread de áudio: canal `ch` de src [n, canais] (float32 do driver) -> soma estéreo em mix."""
        mb = self.max_block
        if n > mb:                            # nunca escrever além dos buffers (os kernels não conferem)
            for i in range(0, n, mb):
                m = min(mb, n - i)
                self.process(src[i:i + m], ch, m, mix[i:i + m])
            return
        if self.VS[S_BAD] > 0.5:
            self._recover()
        plug = self.fx_chain
        if not (plug.slots and plug.active):
            process_vocal(src, ch, n, mix, *self.arrays)
            return
        v_pre(src, ch, n, *self.pre_arrays)
        end = self.VP[P_PLUG_POS] > 0.5
        if not end:
            plug.process(self.KB, n)
        v_ambient(n, *self.amb_arrays)
        if end:
            plug.process(self.KB, n)
        v_out(n, mix, *self.out_arrays)

    def _recover(self):
        """Depois de uma amostra inválida: zera o estado (sem alocar) para o som voltar no próximo bloco."""
        for a in (self.Z, self.X, self.KB, self.RW, self.DBB, self.DLB, self.PDB, self.RVB, self.RVFS):
            a[:] = 0.0
        VS = self.VS
        for k in (S_G_ENV, S_C_GR, S_DS_EH, S_DS_EF, S_DL_LPL, S_DL_LPR, S_BAD):
            VS[k] = 0.0
        VS[S_DS_G] = 1.0

    def render(self, x, block=256):
        """Offline (testes/ferramentas): processa o sinal mono x e devolve a saída estéreo [len(x), 2]."""
        x = np.asarray(x, dtype=np.float32).reshape(-1, 1)
        n = len(x)
        out = np.zeros((n, 2))
        mix = np.zeros((self.max_block, 2))
        for i in range(0, n, block):
            m = min(block, n - i)
            mix[:m] = 0.0
            self.process(x[i:i + m], 0, m, mix)
            out[i:i + m] = mix[:m]
        return out

    # ------------------------------------------------------------------ curva (para a tela)
    def response(self, freqs):
        """Resposta em dB do filtro de graves + EQ de voz (os que estão ligados)."""
        z = np.exp(-2j * np.pi * np.asarray(freqs, dtype=float) / self.fs)
        h = np.ones_like(z)
        slots = []
        if self.values["hpf"]["on"]:
            slots += [BQ_HPF1] + ([BQ_HPF2] if self.VP[P_HPF_N] > 1.5 else [])
        if self.values["eq"]["on"]:
            slots += [BQ_EQ_LOW, BQ_EQ_BODY, BQ_EQ_PRES, BQ_EQ_AIR] + ([BQ_EQ_LP] if self.VP[P_EQ_LP] > 0.5 else [])
        for s in slots:
            b0, b1, b2, a1, a2 = self.BQ[s]
            h *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
        return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9))

    # ------------------------------------------------------------------ cálculo de coeficientes
    def update_all(self):
        for e in VOCAL_EFFECTS:
            self._update(e.key)
        self._update("track")

    def _update(self, effect):
        v = self.values[effect]
        if effect != "track":
            self.VP[_ON_SLOT[effect]] = 1.0 if v["on"] else 0.0
        getattr(self, "_upd_" + effect)(v, self.VP, self.fs)

    def _upd_track(self, v, VP, fs):
        VP[P_SMOOTH] = onepole_coef(fs, 0.015)
        VP[P_INGAIN] = db(v["input_gain"]) * (-1.0 if v["phase"] else 1.0)
        live = v["on"] and not v["mute"]
        vol = db(v["volume"]) if v["volume"] > -59.9 and live else 0.0
        pan = float(v["pan"])
        if pan == 0.0:
            pl = pr = 1.0                     # centro exato: com tudo desligado a saída é a entrada
        else:
            p = (pan + 100.0) / 200.0 * (math.pi / 2)
            pl, pr = math.cos(p) * math.sqrt(2), math.sin(p) * math.sqrt(2)
        VP[P_GL] = vol * pl
        VP[P_GR] = vol * pr
        VP[P_PLUG_POS] = float(round(v.get("plug_pos", 0)))

    def _upd_hpf(self, v, VP, fs):
        f = v["freq"]
        if int(round(v["slope"])):            # Butterworth de 4ª ordem
            self.BQ[BQ_HPF1] = biquad("hp", fs, f, q=0.5412)
            self.BQ[BQ_HPF2] = biquad("hp", fs, f, q=1.3066)
            VP[P_HPF_N] = 2.0
        else:
            self.BQ[BQ_HPF1] = biquad("hp", fs, f, q=0.7071)
            self.BQ[BQ_HPF2] = IDENTITY
            VP[P_HPF_N] = 1.0

    def _upd_gate(self, v, VP, fs):
        thr = db(v["threshold"])
        VP[P_G_THR] = thr * thr                         # o detector trabalha com a média quadrática
        VP[P_G_CLOSE] = thr * thr * 0.5                 # fecha 3 dB abaixo do limiar
        VP[P_G_FLOOR] = db(-v["range"])
        VP[P_G_ATT] = onepole_coef(fs, 0.002)
        VP[P_G_REL] = onepole_coef(fs, v["release"] / 1000.0)
        VP[P_G_HOLD] = 0.08 * fs
        VP[P_G_DET] = 1.0 - math.exp(-1.0 / (0.008 * fs))

    def _upd_comp(self, v, VP, fs):
        amt = v["amount"] / 100.0
        thr = -8.0 - 27.0 * amt                       # -8 .. -35 dBFS
        ratio = 1.5 + 4.5 * amt                       # 1,5:1 .. 6:1
        slope = 1.0 - 1.0 / ratio
        att, rel = COMP_TIMES[int(round(v["speed"]))]
        VP[P_C_THR] = thr
        VP[P_C_SLOPE] = slope
        VP[P_C_ATT] = 1.0 - math.exp(-1.0 / (att * fs))
        VP[P_C_REL] = 1.0 - math.exp(-1.0 / (rel * fs))
        VP[P_C_FAST] = 1.0 - math.exp(-1.0 / (0.0004 * fs))
        # compensação automática: um pico de voz a -12 dBFS sai no mesmo nível (as partes baixas sobem)
        auto = max(0.0, -12.0 - thr) * slope
        VP[P_C_MAKEUP] = db(auto + v["gain"])

    def auto_makeup_db(self):
        return 20.0 * math.log10(self.VP[P_C_MAKEUP]) - self.values["comp"]["gain"]

    def _upd_eq(self, v, VP, fs):
        self.BQ[BQ_EQ_LOW] = biquad("ls", fs, EQ_FREQS["low"], v["low"], q=0.7)
        self.BQ[BQ_EQ_BODY] = biquad("peak", fs, EQ_FREQS["body"], v["body"], q=0.9)
        self.BQ[BQ_EQ_PRES] = biquad("peak", fs, EQ_FREQS["presence"], v["presence"], q=0.9)
        self.BQ[BQ_EQ_AIR] = biquad("hs", fs, EQ_FREQS["air"], v["air"], q=0.7)
        hc = v["highcut"]
        VP[P_EQ_LP] = 1.0 if hc < 19500.0 else 0.0
        self.BQ[BQ_EQ_LP] = biquad("lp", fs, hc, q=0.7071) if hc < 19500.0 else IDENTITY

    def _upd_deess(self, v, VP, fs):
        amt = v["amount"] / 100.0
        self.BQ[BQ_DS] = biquad("hp", fs, v["freq"], q=0.7071)
        VP[P_DS_THR] = -4.0 - 12.0 * amt              # agudos a menos de 4..16 dB do sinal todo = "S"
        VP[P_DS_MAX] = 3.0 + 12.0 * amt               # até 3..15 dB de redução nos agudos
        VP[P_DS_EATT] = 1.0 - math.exp(-1.0 / (0.0005 * fs))
        VP[P_DS_EREL] = 1.0 - math.exp(-1.0 / (0.030 * fs))
        VP[P_DS_GATT] = 1.0 - math.exp(-1.0 / (0.001 * fs))
        VP[P_DS_GREL] = 1.0 - math.exp(-1.0 / (0.050 * fs))
        VP[P_DS_FLOOR] = db(-60.0)
        w = 2.0 * math.pi * min(0.75 * v["freq"], 0.45 * fs) / fs     # shelf um pouco abaixo do "S"
        VP[P_DS_CW] = math.cos(w)
        VP[P_DS_AL] = math.sin(w) / (2.0 * 0.7)

    def _upd_double(self, v, VP, fs):
        VP[P_DB_MIX] = 0.8 * v["mix"] / 100.0
        VP[P_DB_WIDTH] = v["width"] / 100.0
        VP[P_DB_BASE1] = 0.012 * fs
        VP[P_DB_BASE2] = 0.019 * fs
        VP[P_DB_DEPTH] = 0.0015 * fs
        VP[P_DB_RATE1] = 0.31 / fs
        VP[P_DB_RATE2] = 0.43 / fs

    def delay_ms(self):
        v = self.values["delay"]
        beats = DELAY_BEATS[int(round(v["sync"]))]
        ms = 60000.0 / max(self.bpm, 30.0) * beats if beats else v["time"]
        return min(ms, DELAY_MAX_MS)

    def _upd_delay(self, v, VP, fs):
        VP[P_DL_TIME] = self.delay_ms() / 1000.0 * fs
        VP[P_DL_FB] = v["feedback"] / 100.0
        VP[P_DL_MIX] = v["mix"] / 100.0
        VP[P_DL_DAMP] = 1.0 - math.exp(-2.0 * math.pi * 5000.0 / fs)
        VP[P_DL_PING] = float(round(v["ping"]))
        hp = biquad("hp", fs, 180.0, q=0.7071)
        self.BQ[BQ_DL_HPL] = hp
        self.BQ[BQ_DL_HPR] = hp

    def _upd_reverb(self, v, VP, fs):
        base, extra, damp, width, lo, hi = REVERB_VOICING[int(round(v["type"]))]
        mix = v["mix"] / 100.0
        D = self.RVD
        D[Ly.RV_FB] = min(base + extra * v["size"] / 100.0, 0.985)
        D[Ly.RV_DAMP] = damp
        D[Ly.RV_WET] = mix * 1.2
        D[Ly.RV_DRY] = 0.0                      # o fx_reverb devolve só o molhado; o seco fica em KB
        D[Ly.RV_WIDTH] = width
        VP[P_RV_DRY] = 1.0 - 0.3 * mix
        VP[P_RV_PRE] = min(v["predelay"], PREDELAY_MAX_MS) / 1000.0 * fs
        self.BQ[BQ_RV_HP] = biquad("hp", fs, lo, q=0.7071)
        self.BQ[BQ_RV_LP] = biquad("lp", fs, min(hi, 0.45 * fs), q=0.7071)


_ON_SLOT = dict(hpf=P_HPF_ON, gate=P_G_ON, comp=P_C_ON, eq=P_EQ_ON, deess=P_DS_ON, double=P_DB_ON,
                delay=P_DL_ON, reverb=P_RV_ON)


def warmup(fs=48000.0):
    """Compila (ou carrega do cache) os kernels da trilha Vocal antes de abrir o stream."""

    class _Fake:
        active = True
        slots = (1,)

        @staticmethod
        def process(KB, n):
            pass

    v = VocalChain(fs, 64)
    for e in VOCAL_EFFECTS:
        v.set_on(e.key, True)
    v.set_switch("on", True)
    src = np.full((64, 2), 0.1, dtype=np.float32)
    mix = np.zeros((64, 2))
    v.process(src, 0, 64, mix)
    v.fx_chain = _Fake()
    v.process(src, 1, 64, mix)
