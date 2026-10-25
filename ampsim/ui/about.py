"""Janela "Sobre o AmpSim": versão, missão, autor, licença, créditos, sistema e atualizações."""
import os
import platform

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout,
    QWidget,
)

from .. import updater
from ..version import AUTHOR, LICENSE, PROJECT, REPO_URL, TAGLINE, version_text
from .icons import icon, pixmap
from .theme import ACCENT, C

MISSION = (
    "O AmpSim nasceu para ajudar <b>igrejas, ministérios de louvor, projetos sociais, escolas de "
    "música e bandas com orçamento apertado</b>. Ele junta amplificador de guitarra e baixo, pads de "
    "louvor, pianos, órgãos e bateria nos pads num só programa gratuito, para rodar no computador e "
    "no teclado que vocês já têm."
)

CREDITS = (
    ("FluidSynth", "motor de timbres SoundFont", "LGPL-2.1"),
    ("GeneralUser GS (S. Christian Collins)", "banco de timbres", "licença livre"),
    ("Neural Amp Modeler (Steven Atkinson)", "capturas de amplificadores reais", "MIT / capturas GPL-3.0"),
    ("pedalboard (Spotify)", "plugins VST3", "GPL-3.0"),
    ("PySide6 / Qt", "interface", "LGPL-3.0"),
    ("NumPy, SciPy, Numba", "processamento de áudio", "BSD"),
    ("sounddevice / PortAudio", "ASIO, WASAPI, WDM-KS", "MIT"),
)

NOTICE = (
    "Os nomes e desenhos de amplificadores e teclados (Marshall, Fender, Mesa/Boogie, Vox, Ampeg, "
    "Yamaha, Roland, M-VAVE…) são <b>homenagens</b>; as marcas pertencem aos seus donos e o AmpSim "
    "não é afiliado a eles. <b>Os timbres são exemplos</b> criados pelo AmpSim ou vindos de bancos "
    "gratuitos: não são cópias nem amostras do som dos equipamentos originais."
)


def _root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _qt_version():
    import PySide6
    from PySide6 import QtCore
    return f"PySide6 {PySide6.__version__} · Qt {QtCore.qVersion()}"


def system_info(engine):
    """Linhas de diagnóstico (também vão para a área de transferência pelo botão Copiar)."""
    cfg = engine.config
    sha = updater.local_commit()
    try:
        import numba
        import numpy
        libs = f"NumPy {numpy.__version__} · Numba {numba.__version__}"
    except ImportError:
        libs = ""
    sf = engine.instruments.sf
    return [
        ("Versão", f"{version_text()}  (commit {sha[:7] or '?'}, instalação {updater.install_mode()})"),
        ("Windows", f"{platform.system()} {platform.release()} ({platform.version()})"),
        ("Python", f"{platform.python_version()} {platform.architecture()[0]}"),
        ("Bibliotecas", f"{_qt_version()} · {libs}"),
        ("Áudio", f"{cfg.hostapi or '-'} · {cfg.output_device or 'nenhuma saída'} · {cfg.samplerate} Hz · "
                  f"buffer {cfg.blocksize}" + (" · ligado" if engine.running else " · desligado")),
        ("Timbres", "FluidSynth + GeneralUser GS carregados" if sf else (engine.instruments.error or "-")),
        ("Pasta", _root()),
    ]


class AboutDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(f"Sobre o {PROJECT}")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(pixmap("logo", ACCENT, 56))
        head.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(2)
        title = QLabel(f"{PROJECT}  <span style='color:{C['dim']}; font-size:11pt'>{TAGLINE}</span>")
        title.setObjectName("h1")
        names.addWidget(title)
        self.version_label = QLabel(f"Versão <b>{version_text()}</b> · commit {updater.local_commit()[:7] or '?'}")
        self.version_label.setObjectName("small")
        self.version_label.setStyleSheet("font-size: 10pt;")
        names.addWidget(self.version_label)
        by = QLabel(f"Criado por <b>{AUTHOR}</b> · software livre ({LICENSE})")
        by.setObjectName("small")
        names.addWidget(by)
        head.addLayout(names, 1)
        lay.addLayout(head)

        tabs = QTabWidget()
        tabs.addTab(self._page_about(), "Projeto")
        tabs.addTab(self._page_credits(), "Créditos e licenças")
        tabs.addTab(self._page_system(), "Sistema")
        lay.addWidget(tabs, 1)

        row = QHBoxLayout()
        for text, ic, slot in ((" GitHub", "share", lambda: QDesktopServices.openUrl(QUrl(REPO_URL))),
                               (" Verificar atualizações", "refresh", self._check_updates)):
            b = QPushButton(text)
            b.setIcon(icon(ic, C["text"], 15))
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda *_, f=slot: f())
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Fechar")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    # ------------------------------------------------------------------ abas
    def _page_about(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        for html in (MISSION,
                     "<b>O que tem:</b> amplificadores inspirados nos clássicos e capturas NAM, pedais e "
                     "efeitos, EQ e analisador; pianos, órgãos com rotação, pads com shimmer, até 4 "
                     "camadas com efeitos próprios; bateria worship nos pads e pad contínuo nos 12 tons; "
                     "qualquer teclado MIDI, cenas e presets para compartilhar.",
                     f"<b>Código:</b> <a href='{REPO_URL}' style='color:{ACCENT}'>{REPO_URL}</a><br>"
                     f"<b>Licença:</b> {LICENSE}. Você pode usar, copiar, estudar, modificar e distribuir, "
                     "mantendo a mesma licença e o código aberto.",
                     NOTICE):
            lab = QLabel(html)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.RichText)
            lab.setOpenExternalLinks(True)
            lay.addWidget(lab)
        lay.addStretch(1)
        return w

    def _page_credits(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for r, (name, what, lic) in enumerate(CREDITS):
            n = QLabel(f"<b>{name}</b>")
            n.setTextFormat(Qt.RichText)
            grid.addWidget(n, r, 0)
            d = QLabel(what)
            d.setObjectName("small")
            grid.addWidget(d, r, 1)
            grid.addWidget(QLabel(lic), r, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        note = QLabel("A lista completa, com os avisos de cada licença, está no arquivo CREDITS.md.")
        note.setObjectName("small")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        for text, fname in (("Abrir CREDITS.md", "CREDITS.md"), ("Abrir licença (LICENSE)", "LICENSE")):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda *_, f=fname: QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.join(_root(), f))))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _page_system(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        self.sys_lines = system_info(self.win.engine)
        box = QTextBrowser()
        box.setFrameShape(QFrame.NoFrame)
        box.setHtml("<table cellspacing=4>" + "".join(
            f"<tr><td style='color:{C['dim']}; padding-right:12px'>{k}</td><td>{v}</td></tr>"
            for k, v in self.sys_lines) + "</table>")
        lay.addWidget(box, 1)
        copy = QPushButton(" Copiar (para pedir ajuda)")
        copy.setIcon(icon("copy", C["text"], 15))
        copy.setFocusPolicy(Qt.NoFocus)
        copy.clicked.connect(lambda *_: QGuiApplication.clipboard().setText(
            "\n".join(f"{k}: {v}" for k, v in self.sys_lines)))
        lay.addWidget(copy, 0, Qt.AlignLeft)
        return w

    def _check_updates(self):
        self.accept()
        self.win.check_updates(manual=True)

