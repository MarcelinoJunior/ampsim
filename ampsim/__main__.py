"""Ponto de entrada: python -m ampsim"""
import gc
import os
import sys

os.environ.setdefault("SD_ENABLE_ASIO", "1")      # precisa vir antes de importar sounddevice


def _raise_priority():
    """Prioridade alta para o processo (as threads de áudio do driver já usam MMCSS)."""
    if sys.platform == "win32":
        import ctypes

        HIGH_PRIORITY_CLASS = 0x80
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), HIGH_PRIORITY_CLASS)


def main():
    # A thread de áudio precisa do GIL a cada callback: trocar de thread mais rápido que o
    # padrão (5 ms) evita que a UI segure o GIL por um buffer inteiro.
    sys.setswitchinterval(0.0005)
    _raise_priority()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from PySide6.QtGui import QColor, QPixmap

    app = QApplication(sys.argv)
    app.setApplicationName("AmpSim")
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

    # objetos criados até aqui nunca morrem: tira-os das varreduras do GC (menos pausas)
    gc.collect()
    gc.freeze()
    win.autostart()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
