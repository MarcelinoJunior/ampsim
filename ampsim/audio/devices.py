"""Enumeração de APIs de áudio e dispositivos via PortAudio (sounddevice)."""
import os
import sys
from dataclasses import asdict, dataclass

# O DLL do PortAudio com ASIO só é carregado se a variável existir ANTES do import.
os.environ.setdefault("SD_ENABLE_ASIO", "1")
import sounddevice as sd  # noqa: E402

# ordem de preferência: menor latência primeiro
HOSTAPI_ORDER = ("ASIO", "Windows WASAPI", "Windows WDM-KS", "Windows DirectSound", "MME")
SAMPLE_RATES = (44100, 48000, 88200, 96000)
BLOCK_SIZES = (16, 32, 64, 128, 256, 512, 1024)


@dataclass
class AudioConfig:
    hostapi: str = ""
    input_device: str = ""          # "" = sem entrada (só pads)
    output_device: str = ""
    samplerate: int = 48000
    blocksize: int = 128
    wasapi_exclusive: bool = True
    output_offset: int = 0          # primeiro canal do par de saída estéreo

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in (d or {}).items() if k in fields})


@dataclass
class Device:
    index: int
    name: str
    max_in: int
    max_out: int
    default_sr: float


def refresh():
    """Reinicia o PortAudio para enxergar dispositivos conectados depois da abertura do app."""
    sd._terminate()
    sd._initialize()


def hostapis():
    names = [h["name"] for h in sd.query_hostapis()]
    ordered = [n for n in HOSTAPI_ORDER if n in names]
    return ordered + [n for n in names if n not in ordered]


def _hostapi_index(name):
    for i, h in enumerate(sd.query_hostapis()):
        if h["name"] == name:
            return i
    return None


def devices(hostapi_name, kind):
    """Dispositivos de uma API. kind = 'input' ou 'output'."""
    hi = _hostapi_index(hostapi_name)
    if hi is None:
        return []
    out = []
    for idx in sd.query_hostapis(hi)["devices"]:
        d = sd.query_devices(idx)
        dev = Device(idx, d["name"], d["max_input_channels"], d["max_output_channels"],
                     d["default_samplerate"])
        if (kind == "input" and dev.max_in > 0) or (kind == "output" and dev.max_out > 0):
            out.append(dev)
    return out


def find_device(hostapi_name, name, kind):
    for d in devices(hostapi_name, kind):
        if d.name == name:
            return d
    return None


def default_config():
    """Melhor palpite inicial: ASIO se houver driver, senão WASAPI."""
    cfg = AudioConfig()
    for api in hostapis():
        outs = devices(api, "output")
        if not outs:
            continue
        cfg.hostapi = api
        cfg.output_device = outs[0].name
        ins = devices(api, "input")
        if api == "ASIO":
            both = [d for d in outs if d.max_in > 0]
            if both:
                cfg.output_device = cfg.input_device = both[0].name
        elif ins:
            cfg.input_device = ins[0].name
        return cfg
    return cfg


def is_asio(hostapi_name):
    return hostapi_name == "ASIO"


def show_asio_panel(device_index):
    """Abre o painel do driver ASIO (ex.: ASIO4ALL) para ajustar buffer/canais."""
    import ctypes

    lib = ctypes.CDLL(sd._libname)
    fn = lib.PaAsio_ShowControlPanel
    fn.argtypes = [ctypes.c_int, ctypes.c_void_p]
    fn.restype = ctypes.c_int
    err = fn(device_index, None)
    if err != 0:
        raise RuntimeError(f"PortAudio retornou erro {err}")


def promote_audio_thread():
    """Registra a thread atual (a do driver, que chama o callback) no MMCSS "Pro Audio".

    WASAPI já faz isso, mas muitos drivers ASIO não: sem MMCSS a thread de áudio disputa a CPU
    com as outras janelas e perde o "empurrão" de primeiro plano quando o AmpSim sai de foco.
    Devolve o id da thread para o chamador não repetir a chamada.
    """
    import threading

    if sys.platform == "win32":
        import ctypes

        try:
            avrt = ctypes.windll.avrt
            idx = ctypes.c_ulong(0)
            avrt.AvSetMmThreadCharacteristicsW.restype = ctypes.c_void_p
            h = avrt.AvSetMmThreadCharacteristicsW("Pro Audio", ctypes.byref(idx))
            if h:
                AVRT_PRIORITY_CRITICAL = 2
                avrt.AvSetMmThreadPriority(ctypes.c_void_p(h), AVRT_PRIORITY_CRITICAL)
            else:
                THREAD_PRIORITY_TIME_CRITICAL = 15
                k32 = ctypes.windll.kernel32
                k32.SetThreadPriority(k32.GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL)
        except (AttributeError, OSError):
            pass
    return threading.get_ident()
