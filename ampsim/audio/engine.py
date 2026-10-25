"""Motor de áudio: abre o stream PortAudio e roda o DSP no callback."""
from collections import deque
from threading import get_ident

import numpy as np

from . import devices as dev
from .devices import promote_audio_thread, sd
from ..dsp import layout as Ly
from ..dsp.kernels import (
    mix_soundfont, process_post, process_pre, process_track, render_synth, write_output,
)
from ..dsp.synth import SynthDSP
from ..dsp.track import TrackDSP
from ..dsp.keysfx import KeysFX, add_stereo
from ..dsp.padeq import PadEQ
from ..dsp.worship import DrumSynth, ShimmerDSP, render_drums
from ..instruments import Instruments

TRACKS = ("guitar", "bass", "pads")
INPUT_TRACKS = ("guitar", "bass")
RTA_N = 8192                    # amostras guardadas para o analisador (ui/analyzer.py)


class AudioEngine:
    def __init__(self, fs=48000):
        self.fs = float(fs)
        self.tracks = {name: TrackDSP(self.fs) for name in TRACKS}
        self.synth = SynthDSP(self.fs)
        self.input_channel = {"guitar": 0, "bass": 1}
        self.master = 1.0
        self.config = dev.AudioConfig()
        self.stream = None
        self.n_in = 0
        self.xruns = 0
        self._rt_thread = None          # thread do driver já registrada no MMCSS
        self.last_error = None
        self._events = deque()
        self._mix = np.zeros((Ly.MAX_BLOCK, 2))
        self._synth_out = np.zeros((Ly.MAX_BLOCK, 1), dtype=np.float32)
        self._ev = np.zeros((256, 3), dtype=np.int32)
        self.sf_peak = 0.0
        self.out_offset = 0
        self._shim_send = np.zeros(Ly.MAX_BLOCK)
        self._drum_send = np.zeros(Ly.MAX_BLOCK)
        self._drum_ev = np.zeros((64, 2), dtype=np.int64)
        # RTA da aba aberta: entrada seca e saída só desta trilha (anéis lidos pela UI)
        self.rta_track = None
        self.rta_in = np.zeros(RTA_N)
        self.rta_out = np.zeros(RTA_N)
        self.rta_pos_in = self.rta_pos_out = 0
        self._rta_mix = np.zeros((Ly.MAX_BLOCK, 2))
        self._rta_tmp = np.zeros(Ly.MAX_BLOCK)
        self._make_worship()
        self.instruments = Instruments(self)
        self.instruments.start(self.fs, Ly.MAX_BLOCK)

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

        self._rebuild(config.samplerate)
        n_out = min(out_dev.max_out, config.output_offset + 2)
        self.out_offset = min(config.output_offset, max(n_out - 2, 0))
        lat = config.blocksize / config.samplerate
        extra = None
        if config.hostapi == "Windows WASAPI" and config.wasapi_exclusive:
            extra = sd.WasapiSettings(exclusive=True)
        common = dict(samplerate=config.samplerate, blocksize=config.blocksize, dtype="float32",
                      dither_off=True, clip_off=True)
        if in_dev is not None:
            want = max(self.input_channel[t] for t in INPUT_TRACKS) + 1
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

    def _rebuild(self, fs):
        """Recria os buffers de DSP se a taxa mudou; senão só zera o estado."""
        if float(fs) != self.fs:
            self.fs = float(fs)
            for name in TRACKS:
                old = self.tracks[name]
                t = TrackDSP(self.fs)
                t.load_state(old.get_state())
                self.tracks[name] = t
            s = SynthDSP(self.fs)
            s.bpm = self.synth.bpm
            s.load_state(self.synth.get_state())
            self.synth = s
            self.instruments.start(self.fs, Ly.MAX_BLOCK)
            self._make_worship()
        else:
            for t in self.tracks.values():
                t.reset_dsp_state()
            self.synth.reset_voices()
        self._events.clear()

    def _make_worship(self):
        self.drums = DrumSynth(self.fs)
        self.shimmer = ShimmerDSP(self.fs, room=0.93, damp=0.25)
        self.drumverb = ShimmerDSP(self.fs, room=0.84, damp=0.35)
        self.keys_fx = KeysFX(self.fs, Ly.MAX_BLOCK)
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
        s = self.synth
        render_synth(self._synth_out, frames, self._ev, self._drain_events(), s.SD, s.VS, s.SST,
                     self.fs)
        t = tracks["pads"]
        inst = self.instruments
        sf = inst.sf
        shim = self._shim_send
        shimmer = inst.shimmer_amount()
        if sf is not None:
            sf.render(frames)
            to_chain = t.D[Ly.T_AMP] > 0.5 and t.D[Ly.T_ON] > 0.5
            kfx = self.keys_fx
            eq = self.pad_eq
            pk = mix_soundfont(sf.buf, frames, mix, self._synth_out, shim, kfx.KB, to_chain,
                               inst.keys_gain(), inst.drums_gain(), inst.pad_gain(), shimmer,
                               inst.pad_eq["shimmer"] / 100.0, eq.BQ, eq.Z, eq.P)
            if not to_chain:
                kfx.process(frames)
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
        render_drums(mix, send, frames, ev, nev, d.DV, d.DT, self.fs, inst.drums_gain(), d.DS)
        self.drumverb.process(send, frames, mix, 0.25 + inst.levels["drumverb"] / 127.0, 0.0)
        if t.D[Ly.T_ON] > 0.5:
            self._run_track(t, self._synth_out, 0, frames, mix)
        write_output(mix, frames, outdata, self.out_offset, self.master)

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

    @staticmethod
    def _run_track(t, src, ch, frames, mix):
        if t.external_active():
            process_pre(src, ch, frames, *t.pre_arrays)
            t.run_external(t.W[0], frames)
            process_post(frames, mix, *t.post_arrays)
        else:
            process_track(src, ch, frames, mix, *t.arrays)

    def _duplex_cb(self, indata, outdata, frames, time_info, status):
        if self._rt_thread != get_ident():
            self._rt_thread = promote_audio_thread()
        if status:
            self.xruns += 1
        self._render(indata, outdata, frames)

    def _output_cb(self, outdata, frames, time_info, status):
        if self._rt_thread != get_ident():
            self._rt_thread = promote_audio_thread()
        if status:
            self.xruns += 1
        self._render(None, outdata, frames)


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
