"""Estado de uma trilha (guitarra, baixo ou pads): valores dos knobs + arrays de DSP."""
import copy
import math

import numpy as np

from . import layout as Ly
from .filters import IDENTITY, biquad, db, onepole_coef, oversampling_kernel
from .params import AMP_MODELS, CAB_IR_INDEX, CAB_MODELS, EFFECTS, EQ_FREQS, TRACK_PARAMS
from .wav import read_wav

OS_KERNEL = oversampling_kernel()

ON_SLOT = {
    "gate": Ly.G_ON, "comp": Ly.C_ON, "overdrive": Ly.O_ON, "amp": Ly.A_ON, "cab": Ly.CAB_ON,
    "eq": Ly.EQ_ON, "chorus": Ly.CH_ON, "delay": Ly.DL_ON, "reverb": Ly.RV_ON,
}


def default_values():
    vals = {e.key: {p.key: p.default for p in e.params} for e in EFFECTS}
    for e in EFFECTS:
        vals[e.key]["on"] = False
    vals["track"] = {p.key: p.default for p in TRACK_PARAMS}
    vals["track"]["on"] = True
    return vals


def _next_pow2(n):
    return 1 << max(0, int(math.ceil(math.log2(max(n, 1)))))


class TrackDSP:
    def __init__(self, fs):
        self.fs = float(fs)
        self.values = default_values()
        self.ir_path = None
        self.ir_error = None
        self._ir_data = None          # IR original (antes de reamostrar) para trocar de fs

        self.D = np.zeros(Ly.D_SIZE)
        self.BQ = np.zeros((Ly.NBQ, 5))
        self.BQ[:] = IDENTITY
        self.Z = np.zeros((Ly.NBQ, 2))
        self.ST = np.zeros(Ly.ST_SIZE)
        self.OSU = np.zeros((2, 2 * Ly.OS_PHASE))
        self.OSD = np.zeros((2, 2 * Ly.OS_TAPS))
        self.IR = np.zeros(Ly.IR_MAX)
        self.IRH = np.zeros(2 * Ly.IR_BUF)
        self.CHB = np.zeros(Ly.CHORUS_BUF)
        dl = _next_pow2(int(2.1 * self.fs))
        self.DLB = np.zeros((2, dl))
        self.ST[Ly.S_DL_LEN] = dl

        scale = self.fs / 44100.0
        lens = []
        for side in range(2):
            spread = Ly.RV_STEREO_SPREAD * side
            lens += [max(1, int((t + spread) * scale)) for t in Ly.RV_COMB_TUNING]
        for side in range(2):
            spread = Ly.RV_STEREO_SPREAD * side
            lens += [max(1, int((t + spread) * scale)) for t in Ly.RV_AP_TUNING]
        self.RVLEN = np.array(lens, dtype=np.int64)
        self.RVOFF = np.concatenate(([0], np.cumsum(self.RVLEN)[:-1])).astype(np.int64)
        self.RVB = np.zeros(int(self.RVLEN.sum()))
        self.RVPOS = np.zeros(Ly.RV_UNITS, dtype=np.int64)
        self.RVFS = np.zeros(2 * Ly.RV_COMBS)

        self.W = np.zeros((6, Ly.MAX_BLOCK * Ly.OVERSAMPLE))
        self.arrays = (self.D, self.BQ, self.Z, self.ST, OS_KERNEL, self.OSU, self.OSD, self.IR,
                       self.IRH, self.CHB, self.DLB, self.RVB, self.RVOFF, self.RVLEN, self.RVPOS,
                       self.RVFS, self.W)
        self.update_all()

    # ------------------------------------------------------------------ API pública
    def set_param(self, effect, key, value):
        self.values[effect][key] = value
        self._update(effect)

    def set_on(self, effect, on):
        self.values[effect]["on"] = bool(on)
        self._update(effect)

    def get_state(self):
        return {"values": copy.deepcopy(self.values), "ir_path": self.ir_path}

    def load_state(self, state):
        vals = default_values()
        for eff, params in state.get("values", {}).items():
            if eff in vals:
                vals[eff].update({k: v for k, v in params.items() if k in vals[eff]})
        self.values = vals
        path = state.get("ir_path")
        if path and path != self.ir_path:
            self.load_ir_file(path)
        self.update_all()

    def load_ir_file(self, path):
        try:
            x, rate = read_wav(path)
        except (OSError, ValueError) as exc:
            self.ir_error = str(exc)
            return False
        self.ir_path = path
        self.ir_error = None
        self._ir_data = (x[:, 0].copy(), rate)
        self._apply_ir()
        return True

    def set_cab_ir(self, ir):
        self._ir_data = (np.asarray(ir, dtype=np.float64), self.fs)
        self._apply_ir()
        self.D[Ly.CAB_MODE] = 1.0

    def meters(self):
        """Lê e zera os picos (entrada, saída) acumulados desde a última leitura."""
        pin, pout = self.ST[Ly.S_PEAK_IN], self.ST[Ly.S_PEAK_OUT]
        self.ST[Ly.S_PEAK_IN] = 0.0
        self.ST[Ly.S_PEAK_OUT] = 0.0
        return pin, pout

    def reset_dsp_state(self):
        """Zera filtros e linhas de atraso (chamado com o stream parado)."""
        dl_len = self.ST[Ly.S_DL_LEN]
        for a in (self.Z, self.ST, self.OSU, self.OSD, self.IRH, self.CHB, self.DLB, self.RVB,
                  self.RVFS):
            a[:] = 0
        self.RVPOS[:] = 0
        self.ST[Ly.S_DL_LEN] = dl_len

    # ------------------------------------------------------------------ cálculo de coeficientes
    def update_all(self):
        for e in EFFECTS:
            self._update(e.key)
        self._update("track")

    def _bq(self, slot, coefs):
        self.BQ[slot] = coefs

    def _update(self, effect):
        v = self.values[effect]
        D, fs = self.D, self.fs
        if effect in ON_SLOT:
            D[ON_SLOT[effect]] = 1.0 if v["on"] else 0.0
        getattr(self, "_upd_" + effect)(v, D, fs)

    def _upd_track(self, v, D, fs):
        D[Ly.T_ON] = 1.0 if v["on"] else 0.0
        D[Ly.T_INGAIN] = db(v["input_gain"])
        D[Ly.T_VOL] = db(v["volume"]) if v["volume"] > -59.9 else 0.0
        p = (v["pan"] + 100.0) / 200.0 * (math.pi / 2)        # pan de potência constante
        D[Ly.T_PANL] = math.cos(p) * math.sqrt(2)
        D[Ly.T_PANR] = math.sin(p) * math.sqrt(2)

    def _upd_gate(self, v, D, fs):
        D[Ly.G_THR] = db(v["threshold"])
        D[Ly.G_ATT] = onepole_coef(fs, 0.001)
        D[Ly.G_REL] = onepole_coef(fs, v["release"] / 1000.0)
        D[Ly.G_DET] = math.exp(-1.0 / (0.010 * fs))

    def _upd_comp(self, v, D, fs):
        D[Ly.C_THR_DB] = v["threshold"]
        D[Ly.C_SLOPE] = 1.0 - 1.0 / max(v["ratio"], 1.0)
        D[Ly.C_ATT] = onepole_coef(fs, v["attack"] / 1000.0)
        D[Ly.C_REL] = onepole_coef(fs, v["release"] / 1000.0)
        D[Ly.C_MAKEUP] = db(v["makeup"])

    def _upd_overdrive(self, v, D, fs):
        D[Ly.O_DRIVE] = db(6.0 + v["drive"] * 4.4)                # +6 .. +50 dB
        D[Ly.O_LEVEL] = db(-14.0 + v["level"] * 2.4)              # -14 .. +10 dB
        self._bq(Ly.BQ_OD_HPF, biquad("hp", fs, 720, q=0.6))
        tone_f = 600.0 * (12.0 ** (v["tone"] / 10.0))              # 600 Hz .. 7.2 kHz
        self._bq(Ly.BQ_OD_TONE, biquad("lp", fs, tone_f, q=0.6))

    def _upd_amp(self, v, D, fs):
        m = AMP_MODELS[int(round(v["model"]))]
        fso = fs * Ly.OVERSAMPLE
        lo, hi = m["gain_db"]
        total = lo + (hi - lo) * v["gain"] / 10.0
        st = m["stages"]
        per = total / st
        D[Ly.A_STAGES] = st
        D[Ly.A_G1] = db(per)
        D[Ly.A_G2] = db(per + 3.0)
        D[Ly.A_G3] = db(per + 3.0)
        D[Ly.A_BIAS] = m["bias"]
        pd = 0.4 * 10.0 ** (v["master"] / 10.0)
        D[Ly.A_PDRIVE] = pd
        D[Ly.A_OUT] = 0.55 / (0.6 + 0.4 * pd)
        D[Ly.A_SAG] = m["sag"]
        D[Ly.A_SAGCOEF] = onepole_coef(fso, 0.015)
        D[Ly.A_BLEND] = v["blend"] / 100.0
        self._bq(Ly.BQ_A_HPF, biquad("hp", fso, m["hpf"], q=0.6))
        self._bq(Ly.BQ_A_INTER1, biquad("lp", fso, m["inter1"], q=0.6))
        self._bq(Ly.BQ_A_INTER2, biquad("lp", fso, m["inter2"], q=0.6))
        self._bq(Ly.BQ_A_BASS, biquad("ls", fso, m["bass_f"], (v["bass"] - 5.0) * 2.4, q=0.7))
        self._bq(Ly.BQ_A_MID, biquad("peak", fso, m["mid_f"], (v["mid"] - 5.0) * 2.0 + m["mid_off"],
                                     q=m["mid_q"]))
        self._bq(Ly.BQ_A_TREB, biquad("hs", fso, m["treb_f"], (v["treble"] - 5.0) * 2.4, q=0.7))
        self._bq(Ly.BQ_A_PRES, biquad("hs", fs, m["pres_f"], (v["presence"] - 3.0) * 1.3, q=0.7))
        df, dg = m["depth"]
        self._bq(Ly.BQ_A_DEPTH, biquad("ls", fs, df, dg, q=0.7))
        self._bq(Ly.BQ_A_DI, biquad("lp", fs, 6000, q=0.7))

    def _upd_cab(self, v, D, fs):
        idx = int(round(v["model"]))
        D[Ly.CAB_GAIN] = db(v["level"])
        if idx >= CAB_IR_INDEX:
            if self._ir_data is not None:
                D[Ly.CAB_MODE] = 1.0
            else:                       # sem IR carregada: usa o primeiro gabinete
                idx = 0
        if idx < CAB_IR_INDEX:
            filters = CAB_MODELS[idx][1]
            for i, (kind, f, g, q) in enumerate(filters):
                self._bq(Ly.BQ_CAB + i, biquad(kind, fs, f, g, q))
            D[Ly.CAB_NBQ] = len(filters)
            D[Ly.CAB_MODE] = 0.0

    def _apply_ir(self):
        ir, rate = self._ir_data
        if rate != self.fs:
            n_out = int(round(len(ir) * self.fs / rate))
            ir = np.interp(np.arange(n_out) * rate / self.fs, np.arange(len(ir)), ir)
        ir = ir[: Ly.IR_MAX].copy()
        fade = min(64, len(ir))
        ir[-fade:] *= np.linspace(1.0, 0.0, fade)
        peak = np.abs(np.fft.rfft(ir, 8192)).max()
        if peak > 0:
            ir /= peak
        self.D[Ly.CAB_IRLEN] = 0
        self.IR[:] = 0
        self.IR[: len(ir)] = ir
        self.D[Ly.CAB_IRLEN] = len(ir)

    def _upd_eq(self, v, D, fs):
        for i, f in enumerate(EQ_FREQS):
            self._bq(Ly.BQ_EQ + i, biquad("peak", fs, f, v[f"b{i}"], q=1.0))
        D[Ly.EQ_LEVEL] = db(v["level"])

    def _upd_chorus(self, v, D, fs):
        D[Ly.CH_RATE] = v["rate"] / fs
        D[Ly.CH_BASE] = 0.007 * fs
        D[Ly.CH_DEPTH] = 0.004 * fs * v["depth"] / 100.0
        D[Ly.CH_MIX] = v["mix"] / 100.0

    def _upd_delay(self, v, D, fs):
        D[Ly.DL_TIME] = v["time"] / 1000.0 * fs
        D[Ly.DL_FB] = v["feedback"] / 100.0
        D[Ly.DL_MIX] = v["mix"] / 100.0
        cutoff = 800.0 * (20.0 ** (v["tone"] / 10.0))              # 800 Hz .. 16 kHz
        D[Ly.DL_DAMP] = 1.0 - math.exp(-2.0 * math.pi * cutoff / fs)
        D[Ly.DL_PING] = float(round(v["ping"]))

    def _upd_reverb(self, v, D, fs):
        D[Ly.RV_FB] = 0.7 + 0.28 * v["size"] / 100.0
        D[Ly.RV_DAMP] = 0.4 * v["damping"] / 100.0
        mix = v["mix"] / 100.0
        D[Ly.RV_WET] = mix * 1.2
        D[Ly.RV_DRY] = 1.0 - 0.5 * mix
        D[Ly.RV_WIDTH] = v["width"] / 100.0
