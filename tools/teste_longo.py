"""Teste longo do motor de áudio: simula um culto inteiro (2 h por padrão) sem placa de som.

Toca notas, pads, troca de timbre e de tom do pad contínuo, mexe em knobs e grava/toca uma gravação,
o mais rápido que o computador consegue. No fim mostra a memória usada, o pior tempo de bloco e se
apareceu algum valor inválido (NaN/inf) no som.

    python tools/teste_longo.py            (2 horas de áudio)
    python tools/teste_longo.py 30         (30 minutos)
"""
import os
import random
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402


def main(minutes=120.0, block=128, seed=7):
    from ampsim.audio.engine import AudioEngine
    from ampsim.dsp.kernels import warmup
    from ampsim.instruments import CONT_PAD_SOUNDS, KEY_NAMES, READY

    warmup()
    e = AudioEngine()
    inst = e.instruments
    rnd = random.Random(seed)
    fs = int(e.fs)
    out = np.zeros((block, 2), np.float32)
    blocks = int(minutes * 60 * fs / block)
    readies = list(READY)
    held = []
    worst = 0.0
    bad = 0
    tracemalloc.start()
    mem = []
    t_start = time.perf_counter()
    e.sampler.put("teste", (0.2 * np.sin(np.linspace(0, 2000, 24000))).astype(np.float32)[:, None].repeat(2, 1), fs)
    inst.pad_sounds[7] = "Gravação: teste"
    for b in range(blocks):
        r = rnd.random()
        if r < 0.02:
            n = rnd.randint(40, 84)
            inst.key_on(n, rnd.randint(40, 127))
            held.append(n)
        elif r < 0.035 and held:
            inst.key_off(held.pop(0))
        elif r < 0.04:
            inst.pad_hit(rnd.randrange(8), rnd.randint(60, 127))
        elif r < 0.0402:
            inst.set_ready(rnd.choice(readies))
        elif r < 0.0404:
            inst.set_cont_sound(rnd.choice(CONT_PAD_SOUNDS))
            inst.start_cont_pad(rnd.choice(KEY_NAMES))
        elif r < 0.0405:
            inst.stop_cont_pad()
        elif r < 0.041:
            inst.set_knob(rnd.randrange(8), rnd.randint(0, 127))
        if b % 12 == 0:
            inst.tick(block * 12 / fs)
        t0 = time.perf_counter()
        e._render(None, out, block)
        worst = max(worst, time.perf_counter() - t0)
        if not np.isfinite(out).all():
            bad += 1
        if b % (blocks // 8 or 1) == 0:
            mem.append(tracemalloc.get_traced_memory()[0] / 1e6)
    tracemalloc.stop()
    took = time.perf_counter() - t_start
    print(f"áudio simulado: {minutes:.0f} min em {took / 60:.1f} min de relógio")
    print(f"pior bloco: {worst * 1000:.2f} ms (prazo {block / fs * 1000:.2f} ms)")
    print("memória Python (MB) ao longo do teste: " + " ".join(f"{m:.1f}" for m in mem))
    print(f"blocos com valor inválido: {bad}")
    grow = mem[-1] - mem[1] if len(mem) > 2 else 0.0
    ok = bad == 0 and grow < 5.0
    print("RESULTADO:", "OK" if ok else "PROBLEMA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 120.0))
