"""Motor de áudio: abre o stream PortAudio e roda o DSP no callback."""
from collections import deque

import numpy as np

from . import devices as dev
from .devices import sd
from ..dsp import layout as Ly
from ..dsp.kernels import process_post, process_pre, process_track, render_synth, write_output
from ..dsp.synth import SynthDSP
from ..dsp.track import TrackDSP

TRACKS = ("guitar", "bass", "pads")
INPUT_TRACKS = ("guitar", "bass")


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
        self.last_error = None
        self._events = deque()
        self._mix = np.zeros((Ly.MAX_BLOCK, 2))
        self._synth_out = np.zeros((Ly.MAX_BLOCK, 1), dtype=np.float32)
        self._ev = np.zeros((256, 3), dtype=np.int32)

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
            s.load_state(self.synth.get_state())
            self.synth = s
        else:
            for t in self.tracks.values():
                t.reset_dsp_state()
            self.synth.reset_voices()
        self._events.clear()

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
                    self._run_track(t, indata, ch, frames, mix)
        s = self.synth
        render_synth(self._synth_out, frames, self._ev, self._drain_events(), s.SD, s.VS, s.SST,
                     self.fs)
        t = tracks["pads"]
        if t.D[Ly.T_ON] > 0.5:
            self._run_track(t, self._synth_out, 0, frames, mix)
        write_output(mix, frames, outdata, self.out_offset, self.master)

    @staticmethod
    def _run_track(t, src, ch, frames, mix):
        if t.external_active():
            process_pre(src, ch, frames, *t.pre_arrays)
            t.run_external(t.W[0], frames)
            process_post(frames, mix, *t.post_arrays)
        else:
            process_track(src, ch, frames, mix, *t.arrays)

    def _duplex_cb(self, indata, outdata, frames, time_info, status):
        if status:
            self.xruns += 1
        self._render(indata, outdata, frames)

    def _output_cb(self, outdata, frames, time_info, status):
        if status:
            self.xruns += 1
        self._render(None, outdata, frames)
