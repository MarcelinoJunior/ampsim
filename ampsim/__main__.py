"""Ponto de entrada: python -m ampsim"""
import gc
import os
import sys

os.environ.setdefault("SD_ENABLE_ASIO", "1")      # precisa vir antes de importar sounddevice
# BLAS (usado pelas capturas NAM) em uma thread só: blocos pequenos não ganham com threads e
# acordar threads extras dentro do callback causa picos de latência.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
if getattr(sys, "frozen", False):
    # instalado pelo AmpSim-Setup.exe: a pasta do programa pode não aceitar gravação; o código
    # compilado pelo Numba fica no perfil do usuário
    os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "AmpSim", "numba-cache"))


def _raise_priority():
    """Prioridade alta para o processo e nada de economia de energia quando a janela perde o foco.

    O Windows 11 rebaixa processos em segundo plano (EcoQoS/"power throttling": núcleos de
    eficiência e clock menor) e o relógio do sistema volta a 15,6 ms; para áudio em tempo real
    isso vira som picotado sempre que outra janela fica na frente.
    """
    if sys.platform == "win32":
        import ctypes

        HIGH_PRIORITY_CLASS = 0x80
        k32 = ctypes.windll.kernel32
        # HANDLE é ponteiro: sem restype o ctypes trunca o pseudo-handle (-1) e tudo falha calado
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        k32.SetProcessInformation.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)
        proc = k32.GetCurrentProcess()
        k32.SetPriorityClass(proc, HIGH_PRIORITY_CLASS)

        class _Throttle(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong),
                        ("StateMask", ctypes.c_ulong)]

        ProcessPowerThrottling = 4
        EXECUTION_SPEED, IGNORE_TIMER_RESOLUTION = 0x1, 0x4
        st = _Throttle(1, EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION, 0)   # controlar e desligar
        try:
            k32.SetProcessInformation(proc, ProcessPowerThrottling, ctypes.byref(st), ctypes.sizeof(st))
            ctypes.windll.winmm.timeBeginPeriod(1)
        except (AttributeError, OSError):
            pass


def _install_error_log():
    """Sem console (pythonw), erros inesperados vão para %APPDATA%\\AmpSim\\error.log."""
    import traceback

    from .storage import APP_DIR

    def hook(exc_type, exc, tb):
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            with open(APP_DIR / "error.log", "a", encoding="utf-8") as f:
                traceback.print_exception(exc_type, exc, tb, file=f)
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def selftest(out_path):
    """AmpSim.exe --selftest arquivo.txt: liga o motor sem janela e sem placa, toca notas, pads e o
    pad contínuo e grava o resultado (usado para testar o instalador). -> código de saída."""
    import time
    lines = []
    ok = False
    try:
        import numpy as np

        from .audio.engine import AudioEngine
        from .audio.soundfont import available
        from .dsp.kernels import warmup
        t0 = time.time()
        warmup()
        lines.append(f"warmup: {time.time() - t0:.1f} s")
        e = AudioEngine()
        inst = e.instruments
        lines.append(f"timbres (FluidSynth + GeneralUser): {'sim' if available() and inst.sf else 'NÃO'}")
        inst.set_ready("Piano + Pad (culto)")
        out = np.zeros((256, 2), np.float32)
        peak = 0.0
        inst.key_on(60, 100)
        inst.pad_hit(0, 110)
        inst.start_cont_pad("D")
        for b in range(int(48000 * 2 / 256)):
            if b % 6 == 0:
                inst.tick(1 / 30)
            e._render(None, out, 256)
            peak = max(peak, float(np.abs(out).max()))
        lines.append(f"pico do som: {peak:.3f}")
        # trilha Vocal: microfone simulado (canal do vocal) passando pela cadeia de voz (dsp/vocal.py)
        from .vocal_presets import DEFAULT_VOCAL_PRESET, VOCAL_FACTORY
        voc = e.tracks["vocal"]
        voc.apply_preset(VOCAL_FACTORY[DEFAULT_VOCAL_PRESET])
        voc.set_switch("on", True)
        ch = e.input_channel["vocal"]
        mic = np.zeros((256, ch + 1), np.float32)
        voc.meters()
        vpk = 0.0
        for b in range(40):
            mic[:, ch] = 0.2 * np.sin(2 * np.pi * 220.0 * (np.arange(256) + b * 256) / e.fs)
            e._render(mic, out, 256)
            vpk = max(vpk, voc.meters()[1])
        voc.set_switch("on", False)
        vocal_ok = 0.05 < vpk < 2.0 and bool(np.isfinite(out).all())
        lines.append(f"trilha Vocal (microfone simulado): {'ok' if vocal_ok else 'NÃO'} · pico {vpk:.3f}")
        from .ui.widgets import PHOTO_DIR
        lines.append(f"fotos dos timbres: {len(os.listdir(PHOTO_DIR))}")
        ok = peak > 0.01 and np.isfinite(out).all() and inst.sf is not None and vocal_ok
        # plugins VST3: o pedalboard entrou no pacote e a thread dos plugins responde
        from .audio import vst
        vst_ok = vst.available() and vst.host().call(lambda: True, timeout=10.0) is True
        lines.append(f"plugins VST3 (pedalboard): {'ok' if vst_ok else 'NÃO'} · "
                     f"{len(vst.find_plugins())} plugin(s) nas pastas de VST3")
        ok = ok and vst_ok
        # textos do Qt em português (o qtbase_pt_BR.qm entrou no pacote)
        from .ui.i18n import load_translator
        tr = load_translator()
        tr_ok = tr is not None and tr.translate("QPlatformTheme", "Close") == "Fechar"
        lines.append(f"tradução do Qt (pt_BR): {'ok' if tr_ok else 'NÃO'}")
        ok = ok and tr_ok
        # tela remota: servidor só em 127.0.0.1, a página e o QR code (websockets e segno no pacote)
        import urllib.request

        import segno

        from .web import config as wcfg
        from .web.server import WebServer
        srv = WebServer(lambda *a: None, dict)
        web_ok = srv.start(wcfg.default(), host="127.0.0.1", port=0)
        if web_ok:
            page = urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/", timeout=5).read()
            web_ok = b"AmpSim Remoto" in page and bool(segno.make("http://127.0.0.1").matrix)
            srv.stop()
        lines.append(f"tela remota: {'ok' if web_ok else 'FALHOU ' + srv.error}")
        ok = ok and web_ok
    except Exception as exc:  # noqa: BLE001 - o teste relata qualquer erro
        import traceback
        lines.append("ERRO: " + "".join(traceback.format_exception(exc)))
    lines.append("RESULTADO: " + ("OK" if ok else "FALHOU"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    _install_error_log()
    # A thread de áudio precisa do GIL a cada callback: trocar de thread mais rápido que o
    # padrão (5 ms) evita que a UI segure o GIL por um buffer inteiro.
    sys.setswitchinterval(0.0005)
    _raise_priority()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from PySide6.QtGui import QColor, QIcon, QPixmap

    if sys.platform == "win32":
        # ícone próprio na barra de tarefas (em vez do ícone do Python)
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AmpSim.App")
    app = QApplication(sys.argv)
    app.setApplicationName("AmpSim")
    from .ui.i18n import install_translator

    install_translator(app)            # Fechar/Cancelar/Sim/Não… dos diálogos do Qt em português
    icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ampsim.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .ui.theme import STYLE

    app.setStyleSheet(STYLE)

    pix = QPixmap(460, 120)
    pix.fill(QColor("#16181d"))
    splash = QSplashScreen(pix)
    splash.show()
    splash.showMessage("AmpSim\nCompilando o DSP (só demora na primeira execução)…",
                       Qt.AlignCenter, QColor("#d8dae0"))
    app.processEvents()

    from .audio.engine import AudioEngine
    from .dsp.kernels import warmup

    warmup()
    engine = AudioEngine()

    from .ui.main_window import MainWindow

    win = MainWindow(engine)
    app.installEventFilter(win.kbd)
    app.applicationStateChanged.connect(
        lambda s: win.kbd.release_all() if s != Qt.ApplicationActive else None)
    win.show()
    splash.finish(win)
    win.install_pending_packs()        # pianos que o instalador baixou: instala na 1ª abertura

    # objetos criados até aqui nunca morrem: tira-os das varreduras do GC (menos pausas)
    gc.collect()
    gc.freeze()
    win.autostart()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
