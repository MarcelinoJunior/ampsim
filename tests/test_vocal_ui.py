"""Aba Vocal na janela (QA rodada 8): escolher o preset na lista da barra de cima também move o destaque do
Banco de presets (Vocal, Guitarra e Baixo), como ◀ ▶ e a tela remota."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ampsim import storage  # noqa: E402
from ampsim.ui.preset_bank import ROLE  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from ampsim.ui.theme import STYLE
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "app" / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "app" / "presets")
    monkeypatch.setattr(storage, "SHARE_DIR", tmp_path / "Documentos" / "AmpSim")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    from ampsim.audio.engine import AudioEngine
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    w.resize(1536, 800)
    w.show()
    app.processEvents()
    yield w
    w.timer.stop()
    w.close()
    w.deleteLater()
    app.processEvents()


def _bank_current(win):
    it = win.bank.tree.currentItem()
    return it.data(0, ROLE) if it is not None else None


@pytest.mark.parametrize("kind", ["vocal", "guitar", "bass"])
def test_topbar_preset_combo_moves_bank_highlight(win, app, kind):
    page = win.pages[kind]
    win.tabs.setCurrentWidget(page)
    app.processEvents()
    combo = page.preset
    assert win.topbar.preset_stack.currentWidget() is combo
    i = combo.count() - 1                                    # o último ★ da lista (não o atual)
    assert combo.currentIndex() != i
    combo.setCurrentIndex(i)
    combo.activated.emit(i)                                  # o mesmo sinal de escolher com o mouse
    app.processEvents()
    app.processEvents()
    want = ("track", (kind,) + tuple(combo.itemData(i)))
    assert _bank_current(win) == want
