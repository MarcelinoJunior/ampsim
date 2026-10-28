"""Subjanelas (QDockWidget): menu Exibir, mostrar/esconder, travar, layout padrão, salvar/restaurar
entre aberturas, subjanela solta fora da tela volta, troca de aba e Faders em subjanela própria."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget, QMessageBox, QScrollArea  # noqa: E402

from ampsim import storage  # noqa: E402
from ampsim.ui.docks import DOCKS, LAYOUT_VERSION  # noqa: E402

PAD_DOCKS = ("timbre", "pad_continuo", "instrumento")


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from ampsim.ui.theme import STYLE
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "app" / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "app" / "presets")
    monkeypatch.setattr(storage, "SHARE_DIR", tmp_path / "Documentos" / "AmpSim")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    return tmp_path


def make(app, size=(1536, 800)):
    from ampsim.audio.engine import AudioEngine
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    w.resize(*size)
    w.show()
    app.processEvents()
    return w


def close(app, w):
    w.timer.stop()
    w.close()
    w.deleteLater()
    app.processEvents()


@pytest.fixture()
def win(app, dirs):
    w = make(app)
    yield w
    close(app, w)


def test_menus_list_every_subwindow(win):
    bar = win.menu_bar
    assert [a.text().replace("&", "") for a in bar.actions()] == ["Arquivo", "Exibir"]
    texts = [a.text() for a in win.view_menu.actions() if a.text()]
    assert texts[:len(DOCKS)] == [t for _k, t, *_ in DOCKS]
    assert texts[-2:] == ["Travar subjanelas", "Restaurar layout padrão"]
    # Arquivo tem as ações do botão Arquivo e do menu ☰ (o ☰ e o botão continuam lá)
    arq = bar.actions()[0].menu()
    names = [a.text() for a in arq.actions() if a.text()]
    for a in win.file_menu.actions():
        if a.text():
            assert a.text() in names
    assert any("Placa de som" in n for n in names) and any("Sair" in n for n in names)
    assert win.topbar.file_btn.menu() is win.file_menu and win.topbar.menu_btn.menu() is win.main_menu
    # cada parte é uma subjanela de verdade
    for key, title, *_ in DOCKS:
        d = win.panels.docks[key]
        assert isinstance(d, QDockWidget) and d.windowTitle() == title
    assert win.panels.docks["instrumento"].widget() is win.pad_view.side_panel
    assert win.panels.docks["pad_continuo"].widget() is win.pad_view.cont_card
    assert win.panels.docks["barra"].widget() is win.dock


def test_default_layout_like_before(win, app):
    win.tabs.setCurrentWidget(win.pad_view)
    app.processEvents()
    d = win.panels.docks
    area = win.dockWidgetArea
    assert area(d["setlist"]) == area(d["banco"]) == Qt.LeftDockWidgetArea
    assert area(d["instrumento"]) == Qt.RightDockWidgetArea and area(d["barra"]) == Qt.BottomDockWidgetArea
    assert area(d["timbre"]) == area(d["pad_continuo"]) == Qt.TopDockWidgetArea
    assert d["setlist"].geometry().bottom() < d["banco"].geometry().top()          # Setlist em cima do Banco
    assert d["timbre"].geometry().right() < d["pad_continuo"].geometry().left()   # Timbre | Pad contínuo
    assert all(d[k].isVisible() for k in ("setlist", "banco", "timbre", "pad_continuo", "instrumento", "barra"))
    assert not d["faders"].isVisible() and not win.dock.faders_detached
    # cabe na janela de 1536x800 sem barra de rolagem
    assert (win.width(), win.height()) == (1536, 800)
    assert not [s for s in win.findChildren(QScrollArea) if s.isVisible()
                and (s.verticalScrollBar().isVisible() or s.horizontalScrollBar().isVisible())]


def test_window_fits_1366_wide(win, app):
    """Largura mínima caiu de 1524 para caber em 1366 (a barra de cima fica compacta, sem texto cortado)."""
    win.tabs.setCurrentWidget(win.pad_view)
    app.processEvents()
    assert win.minimumSizeHint().width() <= 1366
    win.resize(1366, 760)
    app.processEvents()
    assert win.width() == 1366 and win.topbar._compact
    for b in win.topbar.nav:
        assert b.width() >= b.fontMetrics().horizontalAdvance(b.text()) + 22
    # fechando subjanelas a janela pode ficar bem mais estreita
    for k in ("instrumento", "pad_continuo"):
        win.panels.set_visible(k, False)
    app.processEvents()
    assert win.minimumSizeHint().width() < 1200


def test_hide_and_show_from_the_menu(win, app):
    act = win.panels.actions["banco"]
    act.trigger()                                     # desmarca
    app.processEvents()
    assert not act.isChecked() and win.panels.docks["banco"].isHidden()
    act.trigger()
    app.processEvents()
    assert act.isChecked() and win.panels.docks["banco"].isVisible()
    # o X da subjanela também desmarca no menu
    win.panels.docks["setlist"].close()
    app.processEvents()
    assert not win.panels.actions["setlist"].isChecked() and not win.panels.user_visible["setlist"]


def test_lock_and_unlock(win, app):
    win.panels.set_locked(True)
    app.processEvents()
    assert win.panels.action_lock.isChecked()
    for key, d in win.panels.docks.items():
        assert d.features() == QDockWidget.NoDockWidgetFeatures
        t = win.panels.titles[key]
        if d.isFloating():        # solta (Faders, por padrão) continua com o nome
            assert d.titleBarWidget() is t and t.close_btn.isHidden()
        elif t.extras:            # Setlist e Pad contínuo: a barra fica (tem botões), sem destacar/fechar
            assert d.titleBarWidget() is t and t.float_btn.isHidden() and t.close_btn.isHidden()
            assert all(not w.isHidden() for w in t.extras)
        else:
            assert d.titleBarWidget() is not None and d.titleBarWidget().sizeHint().height() == 0   # sem título
    # sem a barra, o título de dentro do painel volta (Banco, Instrumento / Layer)
    assert not win.bank.head_widgets[1].isHidden() and not win.pad_view.side_head[1].isHidden()
    win.panels.set_locked(False)
    app.processEvents()
    full = QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
    for key, d in win.panels.docks.items():
        assert d.features() == full and d.titleBarWidget() is win.panels.titles[key]
    assert win.bank.head_widgets[1].isHidden() and win.pad_view.side_head[1].isHidden()


def test_restore_default_layout(win, app):
    d = win.panels.docks
    d["instrumento"].setFloating(True)
    win.addDockWidget(Qt.LeftDockWidgetArea, d["barra"])
    win.panels.set_visible("banco", False)
    app.processEvents()
    win.panels.action_restore.trigger()
    app.processEvents()
    assert not d["instrumento"].isFloating()
    assert win.dockWidgetArea(d["barra"]) == Qt.BottomDockWidgetArea
    assert d["banco"].isVisible() and win.panels.actions["banco"].isChecked()


def test_layout_saved_and_restored_between_sessions(app, dirs):
    w = make(app)
    d = w.panels.docks
    w.addDockWidget(Qt.RightDockWidgetArea, d["setlist"])
    w.panels.set_visible("banco", False)
    w.panels.set_locked(True)
    app.processEvents()
    w.save_state()
    saved = storage.load_state()["ui"]["janela"]
    assert saved["versao"] == LAYOUT_VERSION and saved["travado"] and saved["visiveis"]["banco"] is False
    close(app, w)
    w2 = make(app)
    try:
        d2 = w2.panels.docks
        assert w2.dockWidgetArea(d2["setlist"]) == Qt.RightDockWidgetArea
        assert d2["banco"].isHidden() and not w2.panels.actions["banco"].isChecked()
        assert w2.panels.locked and d2["setlist"].features() == QDockWidget.NoDockWidgetFeatures
    finally:
        close(app, w2)
    # layout de outra versão (ou estragado) é ignorado: volta o padrão
    st = storage.load_state()
    st["ui"]["janela"] = {"versao": LAYOUT_VERSION + 99, "estado": "lixo", "geometria": "@@"}
    storage.save_state(st)
    w3 = make(app)
    try:
        assert w3.dockWidgetArea(w3.panels.docks["setlist"]) == Qt.LeftDockWidgetArea and not w3.panels.locked
        assert w3.panels.restore({"versao": LAYOUT_VERSION, "estado": "não é base64!", "geometria": 3}) is False
    finally:
        close(app, w3)


def test_floating_subwindow_off_screen_comes_back(win, app):
    d = win.panels.docks["setlist"]
    d.setFloating(True)
    d.resize(300, 400)
    d.move(QPoint(-50000, -50000))                    # o 2º monitor foi desligado
    app.processEvents()
    win.panels.bring_back_offscreen()
    app.processEvents()
    screen = QApplication.primaryScreen().availableGeometry()
    assert screen.intersects(d.frameGeometry()) and d.isFloating()


def test_page_switch_hides_and_restores_pad_piano_subwindows(win, app):
    p = win.panels
    win.tabs.setCurrentWidget(win.pad_view)
    win.panels.set_visible("pad_continuo", False)    # o usuário escondeu esta
    app.processEvents()
    win.tabs.setCurrentIndex(0)                       # Guitarra
    app.processEvents()
    assert all(p.docks[k].isHidden() for k in PAD_DOCKS)
    assert p.docks["setlist"].isVisible() and p.docks["barra"].isVisible()
    assert p.actions["timbre"].isChecked() and not p.actions["pad_continuo"].isChecked()   # menu lembra
    assert (win.width(), win.height()) == (1536, 800)                                     # sem crescer
    win.tabs.setCurrentWidget(win.pad_view)
    app.processEvents()
    assert p.docks["timbre"].isVisible() and p.docks["instrumento"].isVisible()
    assert p.docks["pad_continuo"].isHidden()          # continuou escondida
    assert (win.width(), win.height()) == (1536, 800)
    # marcar no menu fora da Pad/Piano: aparece quando voltar
    win.tabs.setCurrentIndex(1)
    p.set_visible("pad_continuo", True)
    app.processEvents()
    assert p.docks["pad_continuo"].isHidden()
    win.tabs.setCurrentWidget(win.pad_view)
    app.processEvents()
    assert p.docks["pad_continuo"].isVisible()


def test_faders_in_their_own_subwindow(win, app):
    """Faders numa subjanela própria (ex. 2º monitor): saem da aba Faders / Pads e voltam ao fechar."""
    dock, fd = win.dock, win.panels.docks["faders"]
    win.panels.set_visible("faders", True)
    app.processEvents()
    assert dock.faders_detached and fd.widget() is dock.faders_box and dock.faders_box.isVisible()
    assert fd.isFloating()                             # 1ª vez: janela própria (não aperta a principal)
    strips ={a: s for (k, a), s, *_ in dock.strips}
    strips["Master"].setValue(40)                      # continuam funcionando lá
    dock.update_meters({"master": 1.0, "comp_gr": 10.0})
    assert strips["Master"].level == 1.0               # medidor anda mesmo com a aba Pads aberta
    fd.setFloating(True)
    app.processEvents()
    assert fd.isFloating() and dock.faders_box.isVisible()
    fd.close()                                         # fechou: voltam para a aba
    app.processEvents()
    assert not dock.faders_detached and dock.faders_box.parent() is not None
    dock.show_tab(1)
    app.processEvents()
    assert dock.faders_box.isVisible() and not win.panels.actions["faders"].isChecked()


def test_bottom_bar_collapse_still_works(win, app):
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    assert win.dock.collapsed and win.panels.docks["barra"].height() < 100
    win.tabs.setCurrentWidget(win.pad_view)
    app.processEvents()
    assert not win.dock.collapsed and win.panels.docks["barra"].height() > 150


def test_left_and_bottom_resize_and_persist(app, dirs):
    """Coluna da esquerda e barra de baixo andam com o divisor (como a da direita), o tamanho fica salvo, a
    barra volta à altura escolhida ao expandir e "Restaurar layout padrão" volta a 242 / 192."""
    from ampsim.ui.dock import DOCK_H
    w = make(app, (1800, 900))
    d = w.panels.docks
    w.tabs.setCurrentWidget(w.pad_view)
    app.processEvents()
    assert w.setlist.minimumWidth() <= 200 and w.bank.minimumWidth() <= 200
    w.resizeDocks([d["setlist"]], [330], Qt.Horizontal)
    w.resizeDocks([d["barra"]], [300], Qt.Vertical)
    app.processEvents()
    assert abs(d["setlist"].width() - 330) <= 4 and abs(d["banco"].width() - 330) <= 4
    assert w.setlist.width() > 300 and w.bank.width() > 300            # o conteúdo estica junto
    tall = w.dock.height()
    assert tall > DOCK_H + 60
    strips = {a: s for (k, a), s, *_ in w.dock.strips}
    w.dock.show_tab(1)
    app.processEvents()
    assert strips["Master"].height() > 75                              # faders mais altos (curso maior)
    # recolher e expandir: volta à mesma altura
    w.dock.set_collapsed(True)
    app.processEvents()
    assert w.dock.height() == 48
    w.dock.set_collapsed(False)
    for _ in range(5):
        app.processEvents()
    assert abs(w.dock.height() - tall) <= 4
    w.save_state()
    close(app, w)
    w2 = make(app, (1800, 900))
    try:
        d2 = w2.panels.docks
        w2.tabs.setCurrentWidget(w2.pad_view)
        for _ in range(5):
            app.processEvents()
        assert abs(d2["setlist"].width() - 330) <= 4
        assert abs(w2.dock.height() - tall) <= 4
        w2.panels.default_layout()
        for _ in range(5):
            app.processEvents()
        assert abs(d2["setlist"].width() - 242) <= 4 and w2.dock.height() == DOCK_H
    finally:
        close(app, w2)



# ---------------------------------------------------------------------- QA rodada 4
def _settle(app, n=3):
    for _ in range(n):
        app.processEvents()


@pytest.mark.parametrize("size", [(1366, 768), (1536, 864)])
def test_faders_open_floating_and_window_never_grows(app, dirs, size):
    """Exibir → Faders abre solta (700x420, no meio da tela da janela); mostrar/esconder Faders e trocar
    de aba 30x não muda o tamanho da janela."""
    w = make(app, size)
    try:
        p, fd = w.panels, w.panels.docks["faders"]
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app)
        p.actions["faders"].trigger()
        _settle(app)
        assert fd.isVisible() and fd.isFloating() and fd.size().toTuple() == (700, 420)
        assert w.screen().availableGeometry().contains(fd.geometry().center())
        assert w.size().toTuple() == size
        for i in range(30):
            p.actions["faders"].trigger()
            _settle(app, 1)
            w.tabs.setCurrentIndex(i % 4)
            _settle(app, 1)
            assert w.size().toTuple() == size, (i, w.size().toTuple())
    finally:
        close(app, w)


def test_subwindow_that_does_not_fit_goes_to_tabs_or_floats(app, dirs):
    """Subjanela que só caberia aumentando a janela (Faders encaixada ao lado do Instrumento, como no layout
    antigo; Setlist/Banco levados para a direita) entra em abas ou fica solta: a janela não cresce."""
    w = make(app, (1366, 728))
    try:
        p, d = w.panels, w.panels.docks
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app)
        d["faders"].setFloating(False)
        w.splitDockWidget(d["instrumento"], d["faders"], Qt.Horizontal)
        d["faders"].hide()
        _settle(app)
        p.set_visible("faders", True)
        _settle(app)
        assert w.size().toTuple() == (1366, 728) and d["faders"].isVisible()
        assert d["faders"].isFloating() or d["faders"] in w.tabifiedDockWidgets(d["instrumento"])
        for k in ("setlist", "banco"):
            p.set_visible(k, False)
            w.splitDockWidget(d["instrumento"], d[k], Qt.Horizontal)
            d[k].hide()
            _settle(app)
            p.set_visible(k, True)
            _settle(app)
            assert w.size().toTuple() == (1366, 728) and d[k].isVisible()
            assert d[k].isFloating() or w.tabifiedDockWidgets(d[k])
    finally:
        close(app, w)


def test_min_height_fits_a_1366x768_screen(app, dirs):
    """Tela de 1366x768 tem ~728 px úteis: o layout padrão cabe em <= 720 (travado ou não) e, em 1366x728,
    nada rola nem corta (as 2 fileiras de pads inteiras, botões de camada com as 2 linhas)."""
    w = make(app, (1366, 728))
    try:
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app, 5)
        assert w.minimumSizeHint().height() <= 720
        assert w.size().toTuple() == (1366, 728)
        assert not [s for s in w.findChildren(QScrollArea) if s.isVisible()
                    and (s.verticalScrollBar().isVisible() or s.horizontalScrollBar().isVisible())]
        sc = w.dock.stack.currentWidget()
        for b in w.dock.cont_tiles + w.dock.drum_tiles:
            top = b.mapTo(sc.viewport(), b.rect().topLeft()).y()
            assert top >= 0 and top + b.height() <= sc.viewport().height()
            assert b.height() >= 40
        for b in w.pad_view.layer_buttons[:2]:
            assert b.height() >= 40
        w.panels.set_locked(True)
        _settle(app)
        assert w.minimumSizeHint().height() <= 720
    finally:
        close(app, w)


@pytest.mark.parametrize("bad", ['{"ui": []}', "[1, 2]", '"texto"', "3",
                                 '{"ui": {"janela": [], "shortcuts": 5}, "tracks": [], "keyboard": "x",'
                                 ' "audio": [], "input_channel": 7, "instruments": [], "synth": 1,'
                                 ' "master_db": "alto"}',
                                 '{"instruments": {"keys": 3}}', '{"instruments": {"levels": [1, 2]}}',
                                 '{"instruments": {"keys": "x", "levels": "y", "pad_sounds": 5}}'])
def test_corrupted_state_json_starts_with_defaults(app, dirs, bad):
    storage.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    storage.STATE_FILE.write_text(bad, encoding="utf-8")
    w = make(app, (1366, 728))
    try:
        assert w.isVisible() and w.panels.docks["setlist"].isVisible()
        assert w.kbd.octave == 4 and w.kbd.velocity == 100
    finally:
        close(app, w)


def test_file_menu_has_no_duplicates(win):
    arq = win.menu_bar.actions()[0].menu()
    names = [a.text().replace("&", "").strip() for a in arq.actions() if not a.isSeparator()]
    assert len(names) == len(set(names)), names
    assert names.count("Sobre o AmpSim…") == 1
    acts = arq.actions()
    assert not acts[0].isSeparator() and not acts[-1].isSeparator()
    assert not any(a.isSeparator() and b.isSeparator() for a, b in zip(acts, acts[1:]))


def test_titles_not_repeated_inside_subwindows(win, app):
    """O nome está na barra da subjanela: o título de dentro some e os botões dele vão para a barra."""
    from PySide6.QtWidgets import QPushButton
    win.tabs.setCurrentWidget(win.pad_view)
    _settle(app)
    p, pv, sl = win.panels, win.pad_view, win.setlist
    for w in sl.head_widgets + win.bank.head_widgets + pv.side_head:
        assert w.isHidden()
    t = p.titles["setlist"]
    assert sl.more.parent() is t and sl.fold.parent() is t and sl.more.isVisible() and sl.fold.isVisible()
    t = p.titles["pad_continuo"]
    assert pv.stop_btn.parent() is t and pv.cont_eq_btn.parent() is t and pv.cont_title.parent() is t
    assert pv.stop_btn.isVisible() and t.label is pv.cont_title
    assert t.sizeHint().height() <= 22                       # barra baixa (sem a linha repetida)
    sl.fold.click()                                          # recolher pela barra continua funcionando
    assert sl.body.isHidden()
    sl.fold.click()
    assert not sl.body.isHidden()
    # textos que cortavam em 1366: Importar inteiro, dica do Setlist quebra a linha, nome no tooltip
    win.resize(1366, 728)
    _settle(app)
    imp = next(b for b in win.bank.findChildren(QPushButton) if "Importar" in b.text())
    assert imp.width() >= imp.sizeHint().width()
    assert sl.songs.wordWrap()
    it = win.bank.tree.topLevelItem(0)
    while it.childCount():
        it = it.child(0)
    assert it.toolTip(0) and it.toolTip(0) in it.text(0)


def test_faders_signal_after_widgets_deleted_does_not_raise(win, app):
    """Python saindo sem fechar a janela: o sinal da subjanela Faders chega com os botões já apagados."""
    from shiboken6 import delete
    win.panels.set_visible("faders", True)
    _settle(app)
    delete(win.dock.strips[0][1])                            # um fader já apagado pelo Qt
    win.panels._place_faders(False)                          # não levanta RuntimeError
    win.panels._toggled("faders", True)



# ---------------------------------------------------------------------- QA rodada 5
def _floating(w, keys=None):
    return [k for k, d in w.panels.docks.items() if d.isFloating() and not d.isHidden()
            and (keys is None or k in keys)]


@pytest.mark.parametrize("size", [(1366, 768), (1536, 864)])
def test_redocking_faders_never_grows_the_window(app, dirs, size):
    """Reencaixar a Faders (botão destacar/encaixar = duplo clique no título) não aumenta a janela; se não
    couber ela volta a ficar solta. Fechar e Restaurar também não mudam o tamanho."""
    w = make(app, size)
    try:
        p, fd = w.panels, w.panels.docks["faders"]
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app)
        p.actions["faders"].trigger()
        _settle(app)
        for _ in range(3):
            p.titles["faders"].float_btn.click()                  # encaixar
            _settle(app, 6)
            assert w.size().toTuple() == size
            if not fd.isFloating():
                p.titles["faders"].float_btn.click()              # soltar de novo
                _settle(app, 6)
        # arrastou para o lado do Instrumento / Layer (como o reencaixe do layout antigo)
        w.splitDockWidget(p.docks["instrumento"], fd, Qt.Horizontal)
        _settle(app, 6)
        assert w.size().toTuple() == size
        assert fd.isFloating() or w.tabifiedDockWidgets(fd)
        fd.close()
        _settle(app, 6)
        assert w.size().toTuple() == size
        p.action_restore.trigger()
        _settle(app, 6)
        assert w.size().toTuple() == size and not _floating(w, PAD_DOCKS)
    finally:
        close(app, w)


def test_window_that_grew_shrinks_back_when_the_subwindow_closes(win, app):
    """Se a janela chegou a crescer com uma subjanela encaixada, fechar essa subjanela volta ao tamanho."""
    p = win.panels
    win.tabs.setCurrentWidget(win.pad_view)
    _settle(app)
    win.resize(1700, 800)                                         # como se tivesse crescido sozinha
    _settle(app)
    p._grown_from = type(win.size())(1536, 800)
    p.docks["banco"].close()
    _settle(app, 6)
    assert win.size().toTuple() == (1536, 800)


def test_narrow_on_guitar_then_back_never_floats_pad_subwindows(app, dirs):
    """Estreitar a janela na Guitarra e voltar à Pad/Piano (e o inverso): a largura mínima é a mesma em
    todas as abas, nada fica solto sem o usuário pedir e a troca de aba não muda o tamanho da janela."""
    w = make(app, (1366, 728))
    try:
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app)
        pads_min = w.minimumSizeHint()
        w.tabs.setCurrentIndex(0)
        _settle(app)
        assert w.minimumSizeHint().width() >= pads_min.width()
        w.resize(1000, 700)
        _settle(app)
        size = w.size().toTuple()
        assert size[0] >= pads_min.width()
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app)
        assert w.size().toTuple() == size and not _floating(w)
        assert all(w.panels.docks[k].isVisible() for k in PAD_DOCKS)
        # o inverso: estreita na Pad/Piano, vai ao Baixo, alarga, volta, estreita no Baixo, volta
        w.resize(900, 600)
        _settle(app)
        w.tabs.setCurrentIndex(1)
        _settle(app)
        w.resize(1600, 820)
        _settle(app)
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app)
        assert w.size().toTuple() == (1600, 820) and not _floating(w)
        w.tabs.setCurrentIndex(1)
        _settle(app)
        w.resize(1000, 640)
        _settle(app)
        size = w.size().toTuple()
        w.tabs.setCurrentWidget(w.pad_view)
        _settle(app)
        assert w.size().toTuple() == size and not _floating(w)
        # a barra de baixo recolher/expandir na Guitarra também não faz a janela crescer
        w.tabs.setCurrentIndex(0)
        _settle(app)
        for on in (False, True, False, True):
            w.dock.set_collapsed(on)
            _settle(app)
            assert w.size().toTuple() == size
    finally:
        close(app, w)


def test_folding_the_setlist_gives_the_space_to_the_bank(win, app):
    d = win.panels.docks
    win.tabs.setCurrentWidget(win.pad_view)
    _settle(app)
    h_set, h_bank = d["setlist"].height(), d["banco"].height()
    win.setlist.fold.click()
    _settle(app, 6)
    title = win.panels.titles["setlist"].sizeHint().height()
    assert d["setlist"].height() <= title + 4                     # só a barra (☰ e recolher)
    assert d["banco"].height() >= h_bank + h_set - title - 8      # o Banco ficou com o espaço
    assert win.setlist.fold.isVisible() and win.setlist.more.isVisible()
    win.setlist.fold.click()
    _settle(app, 6)
    assert abs(d["setlist"].height() - h_set) <= 8 and abs(d["banco"].height() - h_bank) <= 8


@pytest.mark.parametrize("page", [0, 1, 3])
def test_track_page_fits_1366_without_horizontal_scroll(app, dirs, page):
    """Guitarra/Baixo/Vocal em 1366x728: sem rolagem de lado (amp inteiro, pedais com rótulos inteiros); a
    rolagem vertical, se houver, aparece."""
    w = make(app, (1366, 728))
    try:
        w.tabs.setCurrentIndex(page)
        _settle(app, 5)
        pg = w.tabs.currentWidget()
        sc = pg.findChild(QScrollArea)
        assert not sc.horizontalScrollBar().isVisible()
        assert sc.widget().minimumSizeHint().width() <= sc.viewport().width()
        from ampsim.ui.widgets import Knob
        for panel in pg.panels:                                   # nenhum knob abaixo da largura do rótulo
            for k in panel.findChildren(Knob):
                assert k.width() >= k.minimumWidth()
    finally:
        close(app, w)


@pytest.mark.parametrize("page", [0, 1, 2, 3])
def test_every_page_fits_minimum_1344x702(app, dirs, page):
    """Guitarra, Baixo, Pad/Piano e Vocal: a janela pode ficar em 1344x702 (mínimo) e em 1366x728 nenhuma
    aba rola de lado nem faz a janela crescer; a barra de cima (4 abas) não corta texto."""
    w = make(app, (1366, 728))
    try:
        w.tabs.setCurrentIndex(page)
        _settle(app, 5)
        hint = w.minimumSizeHint()
        assert hint.width() <= 1344 and hint.height() <= 702, (page, hint.toTuple())
        assert w.size().toTuple() == (1366, 728)
        assert not [s for s in w.findChildren(QScrollArea) if s.isVisible() and s.horizontalScrollBar().isVisible()]
        for b in w.topbar.nav:
            assert b.width() >= b.fontMetrics().horizontalAdvance(b.text()) + 22
        w.resize(1344, 702)
        _settle(app, 5)
        assert w.size().toTuple() == (1344, 702)
    finally:
        close(app, w)
