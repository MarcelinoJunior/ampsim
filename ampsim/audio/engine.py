"""Motor de áudio: abre o stream PortAudio e roda o DSP no callback."""
import math
from collections import deque
from threading import get_ident
from time import perf_counter

import numpy as np

from . import devices as dev
from .devices import promote_audio_thread, sd
from .metronome import Metronome
from .sampler import Recorder, Sampler
from .vst import PluginChain, mono_to_stereo, stereo_to_mono
from ..dsp import layout as Ly
from ..dsp.kernels import (
    mix_soundfont, process_post, process_post_fx, process_post_out, process_pre, process_track, render_synth,
    write_output_lim, limiter_state,
)
from ..dsp.synth import SynthDSP
from ..dsp.track import TrackDSP
from ..dsp.vocal import VocalChain
from ..dsp.keysfx import KeysFX, add_stereo
from ..dsp.padeq import PadEQ
from ..dsp.worship import DrumSynth, ShimmerDSP, render_drums
from ..instruments import MAX_LAYERS, Instruments, channel_routes

TRACKS = ("guitar", "bass", "pads", "vocal")    # todas as trilhas (engine.tracks)
DSP_TRACKS = ("guitar", "bass", "pads")          # as que são TrackDSP (a Vocal é dsp/vocal.py)
INPUT_TRACKS = ("guitar", "bass")                # TrackDSP com entrada da placa
INPUT_CHANNEL_TRACKS = ("guitar", "bass", "vocal")   # cada uma escolhe o seu canal de entrada
RTA_N = 8192                    # amostras guardadas para o analisador (ui/analyzer.py)


class AudioEngine:
    def __init__(self, fs=48000):
        self.fs = float(fs)
        self.tracks = {name: TrackDSP(self.fs) for name in DSP_TRACKS}
        # trilha Vocal (microfone): desligada até alguém ligar, para não abrir o microfone sem querer
        self.tracks["vocal"] = VocalChain(self.fs)
        self.synth = SynthDSP(self.fs)
        self.input_channel = {"guitar": 0, "bass": 1, "vocal": 2}
        self.master = 1.0
        self.muted = False              # mute geral (Alt+Espaço): silencia a saída sem mexer no master
        self.config = dev.AudioConfig()
        self.stream = None
        self.n_in = 0
        self.xruns = 0
        self.overloads = 0              # blocos que demoraram mais que o prazo (a CPU não deu conta)
        self.events = deque(maxlen=400)  # (instante perf_counter, "falha" | "lento"): histórico de falhas
        self._rt_thread = None          # thread do driver já registrada no MMCSS
        self.last_error = None
        self._events = deque()
        self._mix = np.zeros((Ly.MAX_BLOCK, 2))
        self._synth_out = np.zeros((Ly.MAX_BLOCK, 1), dtype=np.float32)
        self._synth_gain = 1.0          # volume da camada que usa o synth (rampa quando muda)
        self._gains = {}                # ganhos da bateria e do pad contínuo, mudando aos poucos
        self._ev = np.zeros((256, 3), dtype=np.int32)
        self.sf_peak = 0.0
        self.out_offset = 0
        self._shim_send = np.zeros(Ly.MAX_BLOCK)
        self._drum_send = np.zeros(Ly.MAX_BLOCK)
        self._drum_ev = np.zeros((64, 2), dtype=np.int64)
        self.start_notes = []           # avisos do último start (taxa ajustada, entrada desligada)
        self.recorder = Recorder()      # REC da aba Faders / Pads
        self.sampler = Sampler()        # gravações tocadas pelos pads
        self.metronome = Metronome(self.fs, Ly.MAX_BLOCK)
        self._lim = limiter_state(self.fs)  # limitador da saída (ver write_output_lim)
        self.click_offset = -2          # saída do click aberta agora (-2 nenhuma, -1 principal, n par n)
        self.sampler.set_fs(self.fs)
        self._route = channel_routes()
        # RTA da aba aberta: entrada seca e saída só desta trilha (anéis lidos pela UI)
        self.rta_track = None
        self.rta_in = np.zeros(RTA_N)
        self.rta_out = np.zeros(RTA_N)
        self.rta_pos_in = self.rta_pos_out = 0
        self._rta_mix = np.zeros((Ly.MAX_BLOCK, 2))
        self._rta_tmp = np.zeros(Ly.MAX_BLOCK)
        # cadeias FX de plugins VST3 (audio/vst.py): uma por camada das teclas (depois de drive/rotação/
        # delay), uma no Master (antes do compressor/limitador, que continuam protegendo a saída) e uma em
        # cada trilha (TrackDSP.fx_chain: depois do reverb, antes do volume da trilha)
        self.layer_chains = [PluginChain(self.fs, Ly.MAX_BLOCK, f"L{k + 1}") for k in range(MAX_LAYERS)]
        self.master_chain = PluginChain(self.fs, Ly.MAX_BLOCK, "Master")
        self._tap = np.zeros(MAX_LAYERS)          # camadas com FX ligada quando as teclas vão pelo amp
        self._synth_kb = np.zeros((Ly.MAX_BLOCK, 2))   # o synth AmpSim (mono) passando pela FX da camada
        self._make_worship()
        self.instruments = Instruments(self)
        self.instruments.start(self.fs, Ly.MAX_BLOCK)
        self.tracks["vocal"].set_bpm(self.instruments.bpm)

    # ------------------------------------------------------------------ eventos do synth
    def send_event(self, kind, a=0, b=0):
        """Thread-safe: chamado pela UI (teclado/mouse) e pela thread de MIDI."""
        self._events.append((kind, a, b))

    def note_on(self, note, velocity=100):
        self.send_event(Ly.EV_NOTE_ON, note, velocity)

    def note_off(self, note):
        self.send_event(Ly.EV_NOTE_OFF, note, 0)

    def all_notes_off(self):
        self.send_event(Ly.EV_ALL_OFF)

    # ------------------------------------------------------------------ stream
    @property
    def running(self):
        return self.stream is not None and self.stream.active

    def start(self, config):
        """Abre o stream com a configuração dada. Lança exceção com mensagem legível se falhar."""
        self.stop()
        self.config = config
        out_dev = dev.find_device(config.hostapi, config.output_device, "output")
        if out_dev is None:
            raise RuntimeError(f"Dispositivo de saída não encontrado: {config.output_device!r}")
        in_dev = None
        if config.input_device:
            in_dev = dev.find_device(config.hostapi, config.input_device, "input")
            if in_dev is None:
                raise RuntimeError(f"Dispositivo de entrada não encontrado: {config.input_device!r}")
        if config.blocksize > Ly.MAX_BLOCK:
            raise RuntimeError(f"Buffer máximo suportado: {Ly.MAX_BLOCK}")
        config, in_dev = self._fit_rate(config, out_dev, in_dev)
        self.config = config

        self._rebuild(config.samplerate)
        click = config.click_offset
        want = max(config.output_offset, click) + 2 if click >= 0 else config.output_offset + 2
        n_out = min(out_dev.max_out, want)
        self.out_offset = min(config.output_offset, max(n_out - 2, 0))
        # click num par próprio (fones da banda) só se a placa tem esse par e não é o principal
        self.click_offset = click if click == -1 or (click >= 0 and click + 2 <= n_out
                                                      and click != self.out_offset) else -2
        lat = config.blocksize / config.samplerate
        extra = None
        if config.hostapi == "Windows WASAPI" and config.wasapi_exclusive:
            extra = sd.WasapiSettings(exclusive=True)
        common = dict(samplerate=config.samplerate, blocksize=config.blocksize, dtype="float32",
                      dither_off=True, clip_off=True)
        if in_dev is not None:
            want = max(self.input_channel[t] for t in INPUT_CHANNEL_TRACKS) + 1
            self.n_in = max(1, min(in_dev.max_in, want))
            stream = sd.Stream(device=(in_dev.index, out_dev.index), channels=(self.n_in, n_out),
                               latency=(lat, lat), extra_settings=(extra, extra),
                               callback=self._duplex_cb, **common)
        else:
            self.n_in = 0
            stream = sd.OutputStream(device=out_dev.index, channels=n_out, latency=lat,
                                     extra_settings=extra, callback=self._output_cb, **common)
        self.xruns = 0
        self.stream = stream
        stream.start()

    def _fit_rate(self, config, out_dev, in_dev):
        """Ajusta a taxa ao que a placa aceita (ex.: teclado USB só em 44,1 kHz). Se entrada e
        saída não tiverem taxa em comum, abre só a saída. Os avisos ficam em start_notes."""
        import dataclasses

        from .hotplug import is_keyboard_audio

        self.start_notes = []
        if in_dev is not None and is_keyboard_audio(in_dev.name):
            self.start_notes.append(
                f"A entrada “{in_dev.name}” é o som do próprio teclado, que devolve pelo USB o que o "
                "AmpSim toca: usada como guitarra/baixo, ela faz microfonia. O áudio abriu só com a saída.")
            config = dataclasses.replace(config, input_device="")
            in_dev = None
        excl = config.hostapi == "Windows WASAPI" and config.wasapi_exclusive
        in_index = in_dev.index if in_dev is not None else None
        both = dev.supported_rates(out_dev.index, in_index, exclusive=excl)
        if config.samplerate in both:
            return config, in_dev
        if not both and in_dev is not None:
            outs = dev.supported_rates(out_dev.index, None, exclusive=excl)
            if outs:
                self.start_notes.append(
                    f"A entrada “{in_dev.name}” e a saída “{out_dev.name}” não funcionam na mesma taxa: "
                    "o áudio abriu só com a saída (sem guitarra/baixo). Para usar a entrada, escolha uma "
                    "entrada da mesma placa ou um driver ASIO.")
                config = dataclasses.replace(config, input_device="")
                in_dev, both = None, outs
        rate = dev.best_rate(both, config.samplerate)
        if rate is None:
            return config, in_dev                     # deixa o PortAudio explicar o erro
        if rate != config.samplerate:
            self.start_notes.append(f"Taxa ajustada para {rate:,} Hz: “{out_dev.name}” não aceita "
                                    f"{config.samplerate:,} Hz.".replace(",", "."))
            config = dataclasses.replace(config, samplerate=rate)
        return config, in_dev

    def stop(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
            finally:
                s.close()

    def latency_ms(self):
        """(entrada, saída, total) em ms, segundo o driver."""
        s = self.stream
        if s is None:
            return 0.0, 0.0, 0.0
        if isinstance(s.latency, tuple):
            li, lo = s.latency
        else:
            li, lo = 0.0, s.latency
        return li * 1000, lo * 1000, (li + lo) * 1000

    def cpu_load(self):
        s = self.stream
        return s.cpu_load if s is not None else 0.0

    def read_output_meter(self):
        """(pico da saída, redução nos picos em dB) desde a última leitura, e zera (interface, ~30x/s).

        O pico é o que vai para as caixas (depois do master, do compressor e do limitador). A redução é a
        total nos picos: compressor (ganho aplicado, sem a compensação) vezes limitador, porque para quem
        toca as duas são "compressão nos picos" (com o Compressor em 0 aparece o que o limitador segura).
        O callback grava em self._lim (sem alocar)."""
        lim = self._lim
        peak, cmin = float(lim[9]), float(lim[10])
        lim[9] = 0.0
        lim[10] = 1.0
        gr = -20.0 * math.log10(cmin) if 0.0 < cmin < 1.0 else 0.0
        return peak, gr

    def _rebuild(self, fs):
        """Recria os buffers de DSP se a taxa mudou; senão só zera o estado."""
        if float(fs) != self.fs:
            self.fs = float(fs)
            self.sampler.set_fs(self.fs)
            self.metronome.set_fs(self.fs, Ly.MAX_BLOCK)
            self._lim = limiter_state(self.fs)
            for name in TRACKS:
                old = self.tracks[name]
                t = VocalChain(self.fs) if name == "vocal" else TrackDSP(self.fs)
                t.fx_chain = old.fx_chain          # os plugins continuam carregados (só trocam a taxa)
                t.fx_chain.set_fs(self.fs)
                if name == "vocal":
                    t.bpm = old.bpm
                t.load_state(old.get_state())
                self.tracks[name] = t
            s = SynthDSP(self.fs)
            s.bpm = self.synth.bpm
            s.load_state(self.synth.get_state())
            self.synth = s
            self.instruments.start(self.fs, Ly.MAX_BLOCK)
            self._make_worship()
            for chain in self.layer_chains + [self.master_chain]:
                chain.set_fs(self.fs)
        else:
            for t in self.tracks.values():
                t.reset_dsp_state()
            self.synth.reset_voices()
        self._events.clear()

    def _make_worship(self):
        self.drums = DrumSynth(self.fs)
        self.shimmer = ShimmerDSP(self.fs, room=0.93, damp=0.25)
        self.drumverb = ShimmerDSP(self.fs, room=0.84, damp=0.35)
        # uma cadeia de efeitos (drive, rotação, delay) por camada das teclas
        self._kbs = np.zeros((MAX_LAYERS, Ly.MAX_BLOCK, 2))
        self.keys_fx = [KeysFX(self.fs, Ly.MAX_BLOCK, self._kbs[k]) for k in range(MAX_LAYERS)]
        self.pad_eq = PadEQ(self.fs)
        if hasattr(self, "instruments"):
            self.instruments.apply_fx()
            self.instruments.apply_pad_eq()

    # ------------------------------------------------------------------ callbacks (tempo real)
    def _drain_events(self):
        q = self._events
        ev = self._ev
        n = 0
        while q and n < len(ev):
            k, a, b = q.popleft()
            ev[n, 0] = k
            ev[n, 1] = a
            ev[n, 2] = b
            n += 1
        return n

    def _render(self, indata, outdata, frames):
        mix = self._mix
        tracks = self.tracks
        rec = self.recorder
        if rec.active and rec.source != "out" and indata is not None and rec.source < indata.shape[1]:
            rec.feed(indata[:frames, rec.source:rec.source + 1])
        if indata is not None:
            n_in = indata.shape[1]
            for name in INPUT_TRACKS:
                t = tracks[name]
                ch = self.input_channel[name]
                if t.D[Ly.T_ON] > 0.5 and ch < n_in:
                    if name == self.rta_track:
                        self._run_track_rta(t, indata, ch, frames, mix)
                    else:
                        self._run_track(t, indata, ch, frames, mix)
            v = tracks["vocal"]
            ch = self.input_channel["vocal"]
            if v.running and ch < n_in:                 # microfone: cadeia de voz (dsp/vocal.py)
                if self.rta_track == "vocal":
                    self._run_vocal_rta(v, indata, ch, frames, mix)
                else:
                    v.process(indata, ch, frames, mix)
        s = self.synth
        render_synth(self._synth_out, frames, self._ev, self._drain_events(), s.SD, s.VS, s.SST,
                     self.fs)
        t = tracks["pads"]
        inst = self.instruments
        g0 = self._synth_gain
        g = inst.synth_layer_gain()
        if g is None:
            g = g0
        if g != 1.0 or g0 != 1.0:
            buf = self._synth_out[:frames, 0]
            buf *= g if g == g0 else np.linspace(g0, g, frames, dtype=np.float32)
        self._synth_gain = g
        lch = self.layer_chains
        syn = inst.synth_layer_index()              # camada (0-3) que toca o synth AmpSim, ou -1
        if syn >= 0:
            ch = lch[syn]
            if ch.slots and ch.active:              # FX da camada no synth (mono): antes da trilha
                kb = self._synth_kb
                mono_to_stereo(self._synth_out, kb, frames)
                ch.process(kb, frames)
                stereo_to_mono(kb, self._synth_out, frames, False)
        drums_g = self._glide("drums", inst.drums_gain())
        pad_g = self._glide("pad", inst.pad_gain())
        sf = inst.sf
        shim = self._shim_send
        shimmer = inst.shimmer_amount()
        if sf is not None:
            sf.render(frames)
            to_chain = t.D[Ly.T_AMP] > 0.5 and t.D[Ly.T_ON] > 0.5
            tap = self._tap
            for k in range(len(tap)):
                ch = lch[k]
                tap[k] = 1.0 if (to_chain and k != syn and ch.slots and ch.active) else 0.0
            eq = self.pad_eq
            pk = mix_soundfont(sf.buf, frames, mix, self._synth_out, shim, self._kbs, self._route, to_chain,
                               inst.keys_gain(), drums_g, pad_g, shimmer,
                               inst.pad_eq["shimmer"] / 100.0, eq.BQ, eq.Z, eq.P, tap)
            if to_chain:
                # teclas pelo amplificador: a FX da camada entra antes do amp (o caminho do amp é mono)
                for k in range(len(tap)):
                    if tap[k] > 0.5:
                        kb = self._kbs[k]
                        lch[k].process(kb, frames)
                        stereo_to_mono(kb, self._synth_out, frames, True)
            else:
                for k, kfx in enumerate(self.keys_fx):
                    kfx.process(frames)
                    ch = lch[k]
                    if ch.slots and k != syn:
                        ch.process(kfx.KB, frames)
                    pk = max(pk, add_stereo(mix, kfx.KB, frames))
            if pk > self.sf_peak:
                self.sf_peak = pk
            if shimmer > 0.0 or inst.cont_key is not None or inst._cp:
                self.shimmer.process(shim, frames, mix, 0.5 + 0.5 * shimmer, 0.3 + 0.6 * shimmer)
        # bateria worship sintetizada + sala da bateria
        q = inst.drum_events
        ev = self._drum_ev
        nev = 0
        while q and nev < len(ev):
            ev[nev, 0], ev[nev, 1] = q.popleft()
            nev += 1
        d = self.drums
        send = self._drum_send
        send[:frames] = 0.0
        render_drums(mix, send, frames, ev, nev, d.DV, d.DT, self.fs, drums_g, d.DS)
        self.drumverb.process(send, frames, mix, 0.25 + inst.levels["drumverb"] / 127.0, 0.0)
        self.sampler.render(mix, frames, drums_g)        # gravações nos pads: volume/mute dos pads
        if t.D[Ly.T_ON] > 0.5:
            self._run_track(t, self._synth_out, 0, frames, mix)
        mc = self.master_chain
        if mc.slots:
            mc.process(mix, frames)                         # FX do Master, antes do compressor/limitador
        self._lim[3] = inst.levels.get("comp", 0) / 100.0   # compressor da saída (fader Compressor)
        write_output_lim(mix, frames, outdata, self.out_offset,
                         self._glide("master", 0.0 if self.muted else self.master), self._lim)
        if rec.active and rec.source == "out":
            rec.feed(outdata[:frames, self.out_offset:self.out_offset + 2])
        m = self.metronome
        if m.on and m.render(frames, inst.bpm) and self.click_offset != -2:
            off = self.out_offset if self.click_offset == -1 else self.click_offset
            if off + 2 <= outdata.shape[1] and not (self.muted and self.click_offset == -1):
                outdata[:frames, off] += m.buf[:frames]
                outdata[:frames, off + 1] += m.buf[:frames]

    def _glide(self, key, target):
        """Ganho que anda ~35% do caminho por bloco (mute e fader sem estalo, ~13 ms)."""
        g = self._gains.get(key, target)
        g = target if abs(target - g) < 1e-3 else g + (target - g) * 0.35
        self._gains[key] = g
        return g

    def _run_track_rta(self, t, indata, ch, frames, mix):
        """Como _run_track, guardando entrada e saída da trilha para o analisador."""
        tm = self._rta_mix
        tm[:frames] = 0.0
        self._run_track(t, indata, ch, frames, tm)
        mix[:frames] += tm[:frames]
        tmp = self._rta_tmp[:frames]
        np.add(tm[:frames, 0], tm[:frames, 1], out=tmp)
        tmp *= 0.5
        self.rta_pos_out = _ring_write(self.rta_out, self.rta_pos_out, tmp)
        self.rta_pos_in = _ring_write(self.rta_in, self.rta_pos_in, indata[:frames, ch])

    def _run_vocal_rta(self, v, indata, ch, frames, mix):
        tm = self._rta_mix
        tm[:frames] = 0.0
        v.process(indata, ch, frames, tm)
        mix[:frames] += tm[:frames]
        tmp = self._rta_tmp[:frames]
        np.add(tm[:frames, 0], tm[:frames, 1], out=tmp)
        tmp *= 0.5
        self.rta_pos_out = _ring_write(self.rta_out, self.rta_pos_out, tmp)
        self.rta_pos_in = _ring_write(self.rta_in, self.rta_pos_in, indata[:frames, ch])

    def vocal_channel_ok(self):
        """O canal escolhido para o microfone existe na entrada aberta agora?"""
        return self.n_in > 0 and self.input_channel.get("vocal", 0) < self.n_in

    @staticmethod
    def _run_track(t, src, ch, frames, mix):
        chain = t.fx_chain
        if chain.slots and chain.active:
            # FX da trilha (plugins VST3): depois do reverb, antes do volume/pan da trilha
            process_pre(src, ch, frames, *t.pre_arrays)
            if t.external_active():
                t.run_external(t.W[0], frames)
            process_post_fx(frames, *t.post_arrays)
            chain.process_lr(t.W[3], t.W[4], frames)
            process_post_out(frames, mix, t.D, t.Z, t.ST, t.W)
        elif t.external_active():
            process_pre(src, ch, frames, *t.pre_arrays)
            t.run_external(t.W[0], frames)
            process_post(frames, mix, *t.post_arrays)
        else:
            process_track(src, ch, frames, mix, *t.arrays)

    def _duplex_cb(self, indata, outdata, frames, time_info, status):
        if self._rt_thread != get_ident():
            self._rt_thread = promote_audio_thread()
        t0 = perf_counter()
        if status:
            self._note_xrun(t0)
        self._render(indata, outdata, frames)
        self._note_time(t0, frames)

    def _output_cb(self, outdata, frames, time_info, status):
        if self._rt_thread != get_ident():
            self._rt_thread = promote_audio_thread()
        t0 = perf_counter()
        if status:
            self._note_xrun(t0)
        self._render(None, outdata, frames)
        self._note_time(t0, frames)

    # ------------------------------------------------------------------ saúde do áudio
    def _note_xrun(self, t):
        """O driver avisou que faltou (ou sobrou) som: um estalo/picote que dá para ouvir."""
        self.xruns += 1
        self.events.append((t, "falha"))

    def _note_time(self, t0, frames):
        if perf_counter() - t0 > frames / self.fs:
            self.overloads += 1
            self.events.append((t0, "lento"))

    @property
    def lost(self):
        """O stream parou sozinho (placa desconectada, driver travou) sem ninguém mandar parar."""
        s = self.stream
        return s is not None and not s.active

    def recent_events(self, seconds=60.0, now=None):
        now = perf_counter() if now is None else now
        return [(t, k) for t, k in list(self.events) if now - t <= seconds]

    def reset_health(self):
        self.xruns = 0
        self.overloads = 0
        self.events.clear()


def _ring_write(buf, pos, x):
    n = len(x)
    end = pos + n
    if end <= len(buf):
        buf[pos:end] = x
    else:
        k = len(buf) - pos
        buf[pos:] = x[:k]
        buf[:n - k] = x[k:]
    return end % len(buf)
