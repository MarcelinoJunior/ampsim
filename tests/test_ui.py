"""Interface: cada botão/menu faz o que promete e tudo cabe em 1536x800 sem rolagem.

Roda sem janela (QT_QPA_PLATFORM=offscreen). Os diálogos (salvar/abrir arquivo, nome, confirmação)
são respondidos pelos testes com monkeypatch.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):                  # mesmas fontes do app de verdade (Segoe UI)
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QScrollArea  # noqa: E402

from ampsim import sharing, storage  # noqa: E402
from ampsim.audio.soundfont import available  # noqa: E402

needs_sf = pytest.mark.skipif(not available(), reason="timbres não baixados (tools/baixar_extras.py)")


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
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: pytest.fail(f"aviso inesperado: {a[2]}")))
    return tmp_path


@pytest.fixture()
def win(app, dirs):
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


def _name(monkeypatch, fm, name="Teste", author="Ministério X"):
    def ask(title, default):
        fm._author = author
        return name
    monkeypatch.setattr(fm, "_ask_name", ask)


# ------------------------------------------------------------------ cabe na tela
def test_everything_fits_1536x800(win, app):
    """Todas as abas e todas as abas da barra inferior, sem barra de rolagem e sem crescer a janela."""
    for page in range(3):
        win.tabs.setCurrentIndex(page)
        for tab in range(4):
            win.dock.show_tab(tab)
            app.processEvents()
            assert (win.width(), win.height()) == (1536, 800), (page, tab)
            scrolls = [s for s in win.findChildren(QScrollArea) if s.isVisible()
                       and (s.verticalScrollBar().isVisible() or s.horizontalScrollBar().isVisible())]
            assert not scrolls, (page, tab, [type(s.widget()).__name__ for s in scrolls])
    hint = win.minimumSizeHint()
    assert hint.width() <= 1536 and hint.height() <= 800


def test_top_nav_switches_pages_and_preset_box(win, app):
    for i, b in enumerate(win.topbar.nav):
        b.click()
        app.processEvents()
        assert win.tabs.currentIndex() == i
        assert win.topbar.preset_stack.currentIndex() == i
        assert [x.isChecked() for x in win.topbar.nav] == [j == i for j in range(3)]


def test_dock_remembers_collapsed_per_page(win, app):
    win.tabs.setCurrentIndex(0)
    assert win.dock.collapsed                      # guitarra: mais tela para o amp
    win.tabs.setCurrentIndex(2)
    assert not win.dock.collapsed
    win.dock.set_collapsed(True)
    win.tabs.setCurrentIndex(0)
    win.tabs.setCurrentIndex(2)
    assert win.dock.collapsed


# ------------------------------------------------------------------ menu Arquivo
def test_file_menu_is_visible_and_complete(win):
    assert "Arquivo" in win.topbar.file_btn.text()
    texts = [a.text() for a in win.file_menu.actions()]
    for want in ("Abrir cena ou preset…", "Salvar cena…", "Exportar preset", "Copiar código para compartilhar",
                 "Abrir a pasta de cenas e presets"):
        assert any(t.startswith(want) for t in texts), want
    main = [a.text() for a in win.topbar.menu_btn.menu().actions()]
    assert "Arquivo" in main and "Sair (salva a sessão)" in main


@needs_sf
def test_scene_save_and_open_roundtrip(win, monkeypatch, dirs):
    fm = win.file_menu
    inst = win.inst
    inst.set_ready("Órgão Gospel (rotação)")
    win.engine.tracks["guitar"].set_param("amp", "gain", 8.5)
    _name(monkeypatch, fm, "Culto domingo")
    target = dirs / "cena.ampsim"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    fm.save_scene()
    assert target.exists()
    doc = sharing.load_file(target)
    assert doc["tipo"] == "cena" and doc["autor"] == "Ministério X"
    inst.set_ready("Piano Brilhante")
    win.engine.tracks["guitar"].set_param("amp", "gain", 1.0)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(target), "")))
    fm.open_file()
    assert inst.keys["sound1"] == "Órgão Hammond" and inst.fx["rot_on"]
    assert win.engine.tracks["guitar"].values["amp"]["gain"] == 8.5


@pytest.mark.parametrize("kind", ["guitar", "bass", "pads", "teclas"])
def test_export_and_import_each_preset_kind(win, monkeypatch, dirs, kind):
    fm = win.file_menu
    _name(monkeypatch, fm, f"Meu {kind}")
    target = dirs / f"{kind}.ampsim"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    fm.export_preset(kind)
    doc = sharing.load_file(target)
    assert doc["trilha"] == kind
    fm.apply_doc(doc)
    stored = storage.list_user_presets(kind)
    assert f"Meu {kind} (Ministério X)" in stored
    win.bank.reload()
    labels = []
    root = win.bank.tree.invisibleRootItem()

    def walk(it):
        for j in range(it.childCount()):
            labels.append(it.child(j).text(0))
            walk(it.child(j))
    walk(root)
    assert f"Meu {kind} (Ministério X)" in labels


def test_share_code_copy_and_paste(win, monkeypatch, app):
    fm = win.file_menu
    _name(monkeypatch, fm, "Timbre do grupo")
    win.inst.set_ready("Rhodes com Delay (balada)") if available() else None
    fm.copy_code("teclas")
    code = app.clipboard().text()
    assert code.startswith(sharing.TEXT_PREFIX)
    doc = sharing.from_text("veja só:\n" + code)
    assert doc["nome"] == "Timbre do grupo"
    fm.apply_doc(doc)
    assert "Timbre do grupo (Ministério X)" in storage.list_user_presets("teclas")


def test_bank_file_list_shows_shared_folder(win, monkeypatch, dirs):
    fm = win.file_menu
    _name(monkeypatch, fm, "Arquivo recebido")
    storage.SHARE_DIR.mkdir(parents=True)
    target = storage.SHARE_DIR / "Arquivo recebido.ampsim"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    fm.export_preset("guitar")
    win.bank.reload()
    files = [win.bank.tree.topLevelItem(i) for i in range(win.bank.tree.topLevelItemCount())
             if win.bank.tree.topLevelItem(i).text(0).startswith("Meus arquivos")][0]
    assert files.child(0).text(0) == "Arquivo recebido"
    win.bank._clicked(files.child(0))              # carregar pelo banco = importar
    assert "Arquivo recebido (Ministério X)" in storage.list_user_presets("guitar")


# ------------------------------------------------------------------ banco e presets
def _bank_items(win):
    out = []

    def walk(it):
        for j in range(it.childCount()):
            ch = it.child(j)
            out.append(ch)
            walk(ch)
    walk(win.bank.tree.invisibleRootItem())
    return out


def test_bank_search_filters(win):
    win.bank.search.setText("gospel")
    visible = [it.text(0) for it in _bank_items(win) if it.data(0, Qt.UserRole) and not it.isHidden()]
    assert visible and all("gospel" in t.lower() for t in visible)
    win.bank.search.setText("")
    assert sum(1 for it in _bank_items(win) if it.data(0, Qt.UserRole) and not it.isHidden()) > 40


@needs_sf
def test_bank_loads_instrument_and_track_presets(win):
    item = next(it for it in _bank_items(win) if it.data(0, Qt.UserRole) == ("ready", "Piano + Pad (culto)"))
    win.bank._clicked(item)
    assert win.inst.ready == "Piano + Pad (culto)" and win.tabs.currentIndex() == 2
    assert "Piano + Pad (culto)" in win.pad_view.title.text()
    item = next(it for it in _bank_items(win) if (it.data(0, Qt.UserRole) or ("",))[0] == "track"
                and it.data(0, Qt.UserRole)[1][0] == "bass")
    win.bank._clicked(item)
    assert win.tabs.currentIndex() == 1
    assert win.pages["bass"].preset.currentData() == item.data(0, Qt.UserRole)[1][1:]


@needs_sf
def test_top_preset_arrows(win):
    win.tabs.setCurrentIndex(2)
    win.pad_view.load_ready("Piano de Concerto")
    win.preset_step(1)
    first = win.inst.ready
    win.preset_step(1)
    assert win.inst.ready and win.inst.ready != first
    win.preset_step(-1)
    assert win.inst.ready == first
    win.tabs.setCurrentIndex(0)
    before = win.pages["guitar"].preset.currentIndex()
    win.preset_step(1)
    assert win.pages["guitar"].preset.currentIndex() == before + 1


@needs_sf
def test_save_my_own_keys_preset(win, monkeypatch):
    win.tabs.setCurrentIndex(2)
    win.pad_view.load_ready("Céu Aberto")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Meu Céu", True)))
    win.save_preset()
    assert "Meu Céu" in storage.list_user_presets("teclas")
    from ampsim.ui.widgets import find_data
    assert find_data(win.ready_combo, ("keys_user", "Meu Céu")) >= 0
    assert win.pad_view.title.text() == "Meu Céu"
    win.load_from_bank("ready", "Piano Brilhante")
    win.load_from_bank("keys_user", "Meu Céu")
    assert win.inst.keys["sound1"] == "Pad Atmosfera"


def test_save_guitar_preset_from_top_bar(win, monkeypatch):
    win.tabs.setCurrentIndex(0)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Meu Drive", True)))
    win.topbar.save_btn.click()
    assert "Meu Drive" in storage.list_user_presets("guitar")
    assert win.pages["guitar"].preset.currentData() == ("user", "Meu Drive")


# ------------------------------------------------------------------ Pad/Piano
@needs_sf
def test_continuous_pad_grid(win):
    pv = win.pad_view
    keys = win.inst.pad_keys
    d = keys.index("D")
    QTest.mouseClick(pv.cont_buttons[d], Qt.LeftButton)
    assert win.inst.cont_key == "D"
    QTest.mouseClick(pv.cont_buttons[keys.index("Parar")], Qt.LeftButton)
    assert win.inst.cont_key is None


def test_drum_tiles_play(win):
    win.inst.set_pad_preset("Worship Moderno")          # pad 1 = bumbo sintetizado
    win.dock.show_tab(0)
    n = len(win.inst.drum_events)
    QTest.mouseClick(win.dock.drum_tiles[0], Qt.LeftButton)
    assert len(win.inst.drum_events) == n + 1
    assert "Bumbo" in win.dock.drum_tiles[0].text()


@needs_sf
def test_big_knobs_change_the_sound(win):
    pv = win.pad_view
    pv.big_knobs["Reverb"].setValue(50, emit=True)
    assert abs(win.inst.levels["reverb"] - 64) <= 1
    pv.big_knobs["Volume teclas"].setValue(30, emit=True)
    assert win.inst.levels["keys"] == 30
    pv.big_knobs["Master"].setValue(50, emit=True)
    assert abs(win.engine.master - 0.5) < 0.01


@needs_sf
def test_layers_split_volume_and_octave(win):
    pv = win.pad_view
    win.load_from_bank("ready", "Piano Brilhante")
    pv.mode.setCurrentIndex(2)
    pv.mode.activated.emit(2)
    k = win.inst.keys
    assert k["mode2"] == "split" and k["layer2_on"] and pv.split.isVisible()
    pv.select_layer(2)
    assert pv.layer_name.text().startswith(k["sound2"][:10])
    pv.layer_vol.setValue(40)
    assert k["vol2"] == 40
    pv.layer_oct.setCurrentIndex(1)
    pv.layer_oct.activated.emit(1)
    assert k["oct2"] == -1
    pv.split.setCurrentIndex(pv.split.findText("divisão em C4"))
    pv.split.activated.emit(pv.split.currentIndex())
    assert k["split"] == 60 and win.pad_view.piano.split_note == 60
    pv.layer2_switch.click()
    assert not k["layer2_on"]


@needs_sf
def test_screen_piano_plays_notes(win, app):
    win.tabs.setCurrentIndex(2)
    app.processEvents()
    piano = win.pad_view.piano
    r, _ = piano._geometry()[60]
    pos = QPoint(int(r.center().x()), int(piano.height() * 0.9))
    QTest.mousePress(piano, Qt.LeftButton, Qt.NoModifier, pos)
    assert 60 in win.inst._held and 60 in piano.active
    QTest.mouseRelease(piano, Qt.LeftButton, Qt.NoModifier, pos)
    assert 60 not in win.inst._held


def test_effect_switches(win):
    pv = win.pad_view
    on = win.inst.fx["rot_on"]
    pv.fx_switch["Rotação liga/desliga"].click()
    assert win.inst.fx["rot_on"] != on
    pv.delay_div.setCurrentIndex(2)
    pv.delay_div.activated.emit(2)
    assert win.inst.fx["delay_div"] == 2 and win.inst.fx["delay_on"]


def test_views_and_drawn_instrument(win, app):
    pv = win.pad_view
    pv.show_view(1)
    assert pv.views.currentIndex() == 1
    pv.show_view(2)
    assert pv.views.currentIndex() == 2
    pv.show_view(0)
    pv.set_device("Roland VR-730")
    assert pv.kbd_stack.currentIndex() == 1 and not pv.knob_card.isVisible()
    assert pv.ctrl.model_name == "Roland VR-730"
    pv.set_device("Teclado simples")
    app.processEvents()
    assert pv.kbd_stack.currentIndex() == 0 and pv.knob_card.isVisible()


def test_midi_learn_maps_screen_control(win, monkeypatch):
    from ampsim.ui import pad_piano

    class FakeDialog:
        def __init__(self, *a, **k):
            self.choice = ["cc", 0, 74]

        def exec(self):
            return True
    monkeypatch.setattr(pad_piano, "MidiLearnDialog", FakeDialog)
    win.pad_view.learn("Reverb")
    assert win.inst.free_map["Reverb"] == ["cc", 0, 74]
    assert "CC74" in win.pad_view.mapped["Reverb"].tag.text()
    win.pad_view.unmap("Reverb")
    assert "Reverb" not in win.inst.free_map


# ------------------------------------------------------------------ barra inferior
def test_mixer_moves_track_and_keys_volumes(win):
    win.dock.show_tab(1)
    strips = {arg: s for (kind, arg), s, _v, _m in win.dock.strips}
    strips["guitar"].setValue(50)
    vol = win.engine.tracks["guitar"].values["track"]["volume"]
    assert -30 < vol < -20
    strips["Volume bateria"].setValue(40)
    assert win.inst.levels["drums"] == 40


def test_midi_tab_function_combos(win):
    win.dock.show_tab(2)
    c = win.dock.knob_combos[0]
    i = c.findText("Drive")
    c.setCurrentIndex(i)
    c.activated.emit(i)
    assert win.inst.knob_funcs[0] == "Drive"


def test_settings_tab(win):
    win.dock.show_tab(3)
    d = win.dock.device
    i = d.findText("Yamaha PSR-E473")
    d.setCurrentIndex(i)
    d.activated.emit(i)
    assert win.inst.device == "Yamaha PSR-E473"
    win.dock.kbd_enable.setChecked(False)
    assert not win.kbd.enabled
    win.dock.use_amp.click()
    assert win.engine.tracks["pads"].values["track"]["use_amp"] == win.dock.use_amp.isChecked()


# ------------------------------------------------------------------ guitarra / baixo
def test_track_side_panel_and_eq_graph(win):
    page = win.pages["guitar"]
    win.tabs.setCurrentIndex(0)
    page.track_knobs["volume"].setValue(-6, emit=True)
    assert win.engine.tracks["guitar"].values["track"]["volume"] == -6
    page.enabled.click()
    assert not win.engine.tracks["guitar"].values["track"]["on"]
    page.enabled.click()
    a = page.analyzer
    a.graph.bandMoved.emit(1, -5.0)
    eq = win.engine.tracks["guitar"].values["eq"]
    assert eq["b1"] == -5.0 and eq["on"]
    a.eq_on.click()
    assert not win.engine.tracks["guitar"].values["eq"]["on"]


# ------------------------------------------------------------------ sessão
@needs_sf
def test_session_is_restored(app, dirs):
    from ampsim.audio.engine import AudioEngine
    from ampsim.ui.main_window import MainWindow

    w = MainWindow(AudioEngine())
    w.load_from_bank("ready", "Coral Etéreo")
    w.tabs.setCurrentIndex(1)
    w.dock.set_collapsed(False)
    w.pad_view.set_device("Roland VR-730")
    w.save_state()
    w.timer.stop()
    w2 = MainWindow(AudioEngine())
    assert w2.inst.ready == "Coral Etéreo"
    assert w2.tabs.currentIndex() == 1 and not w2.dock.collapsed
    assert w2.inst.device == "Roland VR-730"
    w2.timer.stop()
