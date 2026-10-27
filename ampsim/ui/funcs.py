"""Funções de knob (as mesmas do mapeamento MIDI) com faixa e leitura do valor atual.

Usado pelos knobs grandes do Pad/Piano, pelo mixer e pelo painel lateral: todos mexem no som
pelo mesmo caminho do controlador MIDI (Instruments.apply_knob_func), então a tela e o
controlador físico ficam sempre iguais.
"""
import math

from ..dsp.params import Param

# função: (rótulo curto, mínimo, máximo, unidade)
FUNC_RANGES = {
    "Volume teclas": ("Volume", 0, 100, "%"),
    "Volume camada 1": ("Camada 1", 0, 100, "%"),
    "Volume camada 2": ("Camada 2", 0, 100, "%"),
    "Volume camada 3": ("Camada 3", 0, 100, "%"),
    "Volume camada 4": ("Camada 4", 0, 100, "%"),
    "Volume bateria": ("Bateria", 0, 100, "%"),
    "Volume pad contínuo": ("Pad contínuo", 0, 100, "%"),
    "Reverb": ("Reverb", 0, 100, "%"),
    "Chorus": ("Chorus", 0, 100, "%"),
    "Shimmer": ("Shimmer", 0, 100, "%"),
    "Reverb da bateria": ("Sala bateria", 0, 100, "%"),
    "Rotação (intensidade)": ("Rotação", 0, 100, "%"),
    "Rotação (velocidade)": ("Veloc. rotação", 0, 100, "%"),
    "Drive": ("Drive", 0, 100, "%"),
    "Delay (mix)": ("Delay", 0, 100, "%"),
    "Tempo do delay": ("Tempo delay", 80, 1200, "ms"),
    "Repetições do delay": ("Repetições", 0, 100, "%"),
    "Brilho": ("Brilho", 0, 100, "%"),
    "Release": ("Release", 0, 100, "%"),
    "Ataque": ("Ataque", 0, 100, "%"),
    "Sensibilidade ao toque": ("Toque", 0, 100, "%"),
    "Volume do metrônomo": ("Click", 0, 100, "%"),
    "Master": ("Master", 0, 100, "%"),
    "Compressor": ("Compressor", 0, 100, "%"),
}


def func_param(func, label=None):
    short, lo, hi, unit = FUNC_RANGES[func]
    return Param(func, label or short, lo, hi, lo, unit, step=1.0 if unit == "%" else 0.0)


def func_value(engine, func):
    """Valor atual da função, na escala de FUNC_RANGES."""
    inst = engine.instruments
    lv, fx = inst.levels, inst.fx
    pct127 = {"Reverb": "reverb", "Chorus": "chorus", "Ataque": "attack", "Release": "release",
              "Brilho": "bright", "Reverb da bateria": "drumverb"}
    if func in pct127:
        return lv[pct127[func]] / 1.27
    if func == "Rotação (velocidade)":
        from ..instruments import rot_speed_value
        if not fx["rot_on"]:
            return 0.0
        hz = fx["rot_fast_hz" if fx["rot_fast"] else "rot_slow_hz"] if not fx["rot_sync"] else 0.0
        return rot_speed_value(hz) / 1.27
    if func.startswith("Volume camada "):
        return (inst.layer_volume(int(func[-1])) or 0) / 1.27
    # efeito desligado aparece em 0 (o fader mostra o que se ouve); subir o fader liga o efeito
    on_mix = {"Rotação (intensidade)": ("rot_on", "rot_mix"), "Drive": ("drive_on", "drive"),
              "Delay (mix)": ("delay_on", "delay_mix")}
    if func in on_mix:
        on, key = on_mix[func]
        return fx[key] if fx[on] else 0.0
    return {
        "Shimmer": lv["shimmer"], "Tempo do delay": fx["delay_ms"], "Repetições do delay": fx["delay_fb"],
        "Sensibilidade ao toque": lv["touch"], "Volume teclas": lv["keys"],
        "Volume bateria": lv["drums"],
        "Volume pad contínuo": lv["pad"], "Master": master_pct(engine.master),
        "Volume do metrônomo": engine.metronome.volume * 100,
        "Compressor": lv.get("comp", 0),
    }.get(func, 0.0)


def set_func(engine, func, v):
    """Aplica `v` (escala de FUNC_RANGES) pelo mesmo caminho do MIDI."""
    _, lo, hi, _ = FUNC_RANGES[func]
    engine.instruments.apply_knob_func(func, round((v - lo) / (hi - lo) * 127))


def master_pct(master):
    """engine.master (linear, até 2.0) -> 0-100 na mesma curva do knob MIDI "Master"."""
    return min(100.0, math.sqrt(max(master, 0.0) / 2.0) * 100.0)
