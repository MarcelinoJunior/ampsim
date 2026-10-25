"""Synth de pads polifônico (parâmetros -> array SD lido pelo kernel Numba)."""
import copy

import numpy as np

from . import layout as Ly
from .filters import db
from .params import SYNTH_PARAMS

SYNTH_PRESETS = {
    "Pad Quente": {},
    "Cordas": dict(wave1=2, wave2=2, mix2=50, detune=14, cutoff=3200, reso=10, fenv=0.8,
                   a_attack=350, a_decay=800, a_sustain=90, a_release=1200, lfo_depth=0.1),
    "Órgão": dict(wave1=0, wave2=0, semi2=12, mix2=40, detune=2, sub=50, cutoff=9000, reso=0,
                  fenv=0, a_attack=5, a_decay=100, a_sustain=100, a_release=80, lfo_depth=0),
    "Saw Brilhante": dict(wave1=2, wave2=2, mix2=50, detune=22, cutoff=5000, reso=25, fenv=2,
                          f_attack=200, a_attack=80, a_release=900),
    "Sino Suave": dict(wave1=0, wave2=1, semi2=19, mix2=30, detune=0, cutoff=6000, fenv=0,
                       a_attack=2, a_decay=2500, a_sustain=0, a_release=2500, lfo_depth=0),
    "Baixo Pulsante": dict(wave1=2, wave2=3, semi2=-12, mix2=40, detune=4, sub=70, cutoff=420,
                           reso=22, fenv=1.6, keytrk=30, f_attack=3, f_decay=220, f_sustain=25,
                           f_release=150, a_attack=4, a_decay=400, a_sustain=95, a_release=160,
                           lfo_depth=0, velsens=40, pulse_depth=85, pulse_filt=2.2, pulse_div=1,
                           pulse_shape=0, pulse_retrig=1),
    "Pad Escuro": dict(wave1=3, wave2=2, semi2=-12, mix2=45, detune=7, sub=30, cutoff=600,
                       reso=35, fenv=1.2, f_attack=2500, a_attack=1500, a_release=3500,
                       lfo_rate=0.15, lfo_depth=0.5),
}


def default_synth_values():
    return {p.key: p.default for p in SYNTH_PARAMS}


PULSE_DIV = (1.0, 2.0, 4.0 / 3.0, 4.0, 0.5)     # ciclos por tempo: 1/4, 1/8, 1/8 pont., 1/16, 1/2


class SynthDSP:
    def __init__(self, fs):
        self.fs = float(fs)
        self.bpm = 100.0
        self.values = default_synth_values()
        self.SD = np.zeros(Ly.SD_SIZE)
        self.VS = np.zeros((Ly.MAX_VOICES, Ly.VS_SIZE))
        self.SST = np.zeros(Ly.SST_SIZE)
        self.update_all()

    def set_param(self, key, value):
        self.values[key] = value
        self.update_all()

    def apply_preset(self, name):
        vals = default_synth_values()
        vals.update(SYNTH_PRESETS.get(name, {}))
        self.values = vals
        self.update_all()

    def get_state(self):
        return copy.deepcopy(self.values)

    def load_state(self, values):
        vals = default_synth_values()
        vals.update({k: v for k, v in values.items() if k in vals})
        self.values = vals
        self.update_all()

    def update_all(self):
        v, SD, fs = self.values, self.SD, self.fs

        def att(ms):
            return 1.0 / max(ms / 1000.0 * fs, 1.0)

        def coef(ms):
            return 1.0 - np.exp(-4.6 / max(ms / 1000.0 * fs, 1.0))

        SD[Ly.SY_WAVE1] = round(v["wave1"])
        SD[Ly.SY_WAVE2] = round(v["wave2"])
        SD[Ly.SY_MIX2] = v["mix2"] / 100.0
        SD[Ly.SY_SEMI2] = round(v["semi2"])
        SD[Ly.SY_DETUNE] = v["detune"]
        SD[Ly.SY_SUB] = v["sub"] / 100.0
        SD[Ly.SY_CUTOFF] = v["cutoff"]
        SD[Ly.SY_RESO] = v["reso"] / 100.0
        SD[Ly.SY_FENV] = v["fenv"]
        SD[Ly.SY_KEYTRK] = v["keytrk"] / 100.0
        SD[Ly.SY_AATT] = att(v["a_attack"])
        SD[Ly.SY_ADEC] = coef(v["a_decay"])
        SD[Ly.SY_ASUS] = v["a_sustain"] / 100.0
        SD[Ly.SY_AREL] = coef(v["a_release"])
        SD[Ly.SY_FATT] = att(v["f_attack"])
        SD[Ly.SY_FDEC] = coef(v["f_decay"])
        SD[Ly.SY_FSUS] = v["f_sustain"] / 100.0
        SD[Ly.SY_FREL] = coef(v["f_release"])
        SD[Ly.SY_LFORATE] = v["lfo_rate"]
        SD[Ly.SY_LFODEPTH] = v["lfo_depth"]
        SD[Ly.SY_VELSENS] = v["velsens"] / 100.0
        SD[Ly.SY_BEND_RANGE] = round(v["bend_range"])
        SD[Ly.SY_VOL] = db(v["volume"])
        SD[Ly.SY_PULSE_DEPTH] = v["pulse_depth"] / 100.0
        SD[Ly.SY_PULSE_FILT] = v["pulse_filt"]
        SD[Ly.SY_PULSE_RATE] = self.bpm / 60.0 * PULSE_DIV[int(round(v["pulse_div"]))]
        SD[Ly.SY_PULSE_SHAPE] = round(v["pulse_shape"])
        SD[Ly.SY_PULSE_RETRIG] = round(v["pulse_retrig"])

    def set_bpm(self, bpm):
        self.bpm = float(bpm)
        self.update_all()

    def restart_pulse(self):
        self.SST[Ly.SS_PULSE] = 0.0

    def reset_voices(self):
        self.VS[:] = 0
        self.SST[:] = 0
