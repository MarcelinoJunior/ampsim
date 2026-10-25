"""Índices dos arrays compartilhados entre a thread de UI (Python) e a de áudio (Numba).

O Python calcula valores "derivados" (ganhos lineares, coeficientes, tempos em
amostras) e grava no array D; o código Numba só lê D, BQ e os buffers de estado.
Constantes globais inteiras viram constantes de compilação no Numba.
"""

OVERSAMPLE = 4
OS_TAPS = 64                     # taps do filtro de oversampling (múltiplo de OVERSAMPLE)
OS_PHASE = OS_TAPS // OVERSAMPLE

MAX_BLOCK = 4096                 # maior bloco de áudio suportado
IR_MAX = 2048                    # taps máximos da IR de gabinete (convolução direta, latência zero)
IR_BUF = 2048                    # tamanho do histórico (>= IR_MAX)
CHORUS_BUF = 8192                # potência de 2
CAB_MAX_BQ = 6
EQ_BANDS = 5

# ---------------------------------------------------------------- array D
G_ON, G_THR, G_ATT, G_REL = 0, 1, 2, 3
C_ON, C_THR_DB, C_SLOPE, C_ATT, C_REL, C_MAKEUP = 4, 5, 6, 7, 8, 9
O_ON, O_DRIVE, O_LEVEL = 10, 11, 12
A_ON, A_STAGES, A_G1, A_G2, A_G3, A_BIAS, A_PDRIVE, A_OUT, A_BLEND, A_SAG = range(13, 23)
CAB_ON, CAB_MODE, CAB_NBQ, CAB_IRLEN, CAB_GAIN = range(23, 28)
EQ_ON, EQ_LEVEL = 28, 29
CH_ON, CH_RATE, CH_DEPTH, CH_BASE, CH_MIX = range(30, 35)
DL_ON, DL_TIME, DL_FB, DL_MIX, DL_DAMP, DL_PING = range(35, 41)
RV_ON, RV_FB, RV_DAMP, RV_WET, RV_DRY, RV_WIDTH = range(41, 47)
T_VOL, T_PANL, T_PANR, T_ON, T_INGAIN = range(47, 52)
G_DET = 52                       # coeficiente de release do detector do gate
A_SAGCOEF = 53                   # coeficiente do envelope de "sag" (taxa 4x)
NR_ON, NR_HUM, NR_DYN, NR_THR, NR_ATT, NR_REL, NR_FMIN, NR_FMAX, NR_HPF, NR_LPF = range(54, 64)
A_HEAD = 65                      # folga do estágio de potência (1 = satura cedo)
T_AMP = 64                       # 0 = trilha sem amp/gabinete/pedais de entrada (só efeitos)
D_SIZE = 80

# ---------------------------------------------------------------- slots de biquad (BQ/Z)
BQ_OD_HPF = 0       # taxa base
BQ_OD_TONE = 1      # taxa base
BQ_A_HPF = 2        # 4x
BQ_A_INTER1 = 3     # 4x
BQ_A_INTER2 = 4     # 4x
BQ_A_BASS = 5       # 4x
BQ_A_MID = 6        # 4x
BQ_A_TREB = 7       # 4x
BQ_A_PRES = 8       # taxa base
BQ_A_DEPTH = 9      # taxa base
BQ_A_DI = 10        # taxa base (EQ do sinal limpo do blend)
BQ_CAB = 11         # 11..16
BQ_EQ = BQ_CAB + CAB_MAX_BQ   # 17..21
NR_NOTCHES = 4
BQ_NR_HUM = BQ_EQ + EQ_BANDS  # 22..25 (notches da fundamental e harmônicos da rede)
BQ_NR_HPF = BQ_NR_HUM + NR_NOTCHES
BQ_NR_LPF = BQ_NR_HPF + 1
NBQ = BQ_NR_LPF + 1

# ---------------------------------------------------------------- estado escalar (ST)
S_GATE_ENV, S_GATE_GAIN = 0, 1
S_COMP_ENV = 2
S_SAG = 3
S_CH_PHASE = 4
S_CH_POS = 5
S_DL_POS = 6
S_DL_LP_L, S_DL_LP_R = 7, 8
S_IR_POS = 9
S_OSU0, S_OSD0 = 10, 11       # índices dos oversamplers (overdrive)
S_OSU1, S_OSD1 = 12, 13       # índices dos oversamplers (amp)
S_PEAK_IN, S_PEAK_OUT = 14, 15
S_GATE_OPEN = 16
S_DL_LEN = 17                 # tamanho do buffer de delay (potência de 2)
S_NR_ENV, S_NR_IC1, S_NR_IC2 = 18, 19, 20
ST_SIZE = 32

# ---------------------------------------------------------------- reverb (Freeverb)
RV_COMBS = 8
RV_APS = 4
RV_UNITS = 2 * (RV_COMBS + RV_APS)   # L e R
RV_COMB_TUNING = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
RV_AP_TUNING = (556, 441, 341, 225)
RV_STEREO_SPREAD = 23

# ---------------------------------------------------------------- synth
MAX_VOICES = 16
# estado de cada voz (VS[v, campo])
V_ACTIVE, V_NOTE, V_VEL, V_FREQ, V_PH1, V_PH2, V_PHS = range(7)
V_ESTAGE, V_ELEVEL, V_FSTAGE, V_FLEVEL, V_IC1, V_IC2, V_AGE, V_HELD, V_GATE = range(7, 16)
VS_SIZE = 16
# parâmetros derivados do synth (SD)
SY_WAVE1, SY_WAVE2, SY_DETUNE, SY_SEMI2, SY_MIX2, SY_SUB = range(6)
SY_CUTOFF, SY_RESO, SY_FENV, SY_KEYTRK = range(6, 10)
SY_AATT, SY_ADEC, SY_ASUS, SY_AREL = range(10, 14)
SY_FATT, SY_FDEC, SY_FSUS, SY_FREL = range(14, 18)
SY_LFORATE, SY_LFODEPTH, SY_VOL, SY_VELSENS, SY_BEND_RANGE = range(18, 23)
SY_PULSE_DEPTH, SY_PULSE_RATE, SY_PULSE_SHAPE, SY_PULSE_FILT, SY_PULSE_RETRIG = range(23, 28)
SD_SIZE = 32
# estado global do synth (SST)
SS_LFO, SS_BEND, SS_SUSTAIN, SS_MOD, SS_AGE, SS_PULSE = range(6)
SS_PRESTART, SS_XF, SS_XFMUL, SS_XFOCT = range(6, 10)   # recomeço do pulso (Tap) com transição
SST_SIZE = 12

# tipos de evento
EV_NOTE_ON, EV_NOTE_OFF, EV_SUSTAIN, EV_BEND, EV_MOD, EV_ALL_OFF = 1, 2, 3, 4, 5, 6
