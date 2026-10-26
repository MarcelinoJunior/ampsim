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


class FakeStream:
    active = True
    latency = (0.003, 0.005)
    cpu_load = 0.1

    def stop(self):
        self.active = False

    def close(self):
        pass


def test_power_button_real_clicks(win, app, monkeypatch):
    """Clicar no bloco "Áudio" (em qualquer ponto) liga e desliga de verdade."""
    e = win.engine
    e.config.output_device = "Placa de teste"
    monkeypatch.setattr(e, "start", lambda cfg: setattr(e, "stream", FakeStream()))
    b = win.topbar.power
    for target in (b, win.topbar.power_title, win.topbar.power_state, win.topbar.dot):
        pos = target.rect().center()
        QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, pos)
        app.processEvents()
        assert e.running, target
        assert "ligado" in win.topbar.power_title.text() and b.isChecked()
        QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, pos)
        app.processEvents()
        assert not e.running, target
        assert "desligado" in win.topbar.power_title.text() and not b.isChecked()


def test_buttons_with_signals_really_fire(win, monkeypatch):
    called = []
    monkeypatch.setattr(win, "open_audio_dialog", lambda: called.append("audio"))
    monkeypatch.setattr(win.file_menu, "open_file", lambda: called.append("import"))
    monkeypatch.setattr(win, "save_preset", lambda: called.append("save"))
    win.topbar.audioSettings.disconnect()
    win.topbar.audioSettings.connect(win.open_audio_dialog)
    win.bank.requestImport.disconnect()
    win.bank.requestImport.connect(win.file_menu.open_file)
    win.bank.requestSave.disconnect()
    win.bank.requestSave.connect(win.save_preset)
    QTest.mouseClick(win.topbar.info, Qt.LeftButton)
    from PySide6.QtWidgets import QPushButton
    for b in win.bank.findChildren(QPushButton):
        QTest.mouseClick(b, Qt.LeftButton)
    assert called == ["audio", "save", "import"]


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
            labels.append(it.child(j).text(0).strip())
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
    win.tabs.setCurrentIndex(0)                    # preset de guitarra: aparece na aba Guitarra
    win.bank.reload()
    files = [win.bank.tree.topLevelItem(i) for i in range(win.bank.tree.topLevelItemCount())
             if win.bank.tree.topLevelItem(i).text(0).strip().startswith("Meus arquivos")][0]
    assert files.child(0).text(0).strip() == "Arquivo recebido"
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
    win.tabs.setCurrentIndex(2)
    win.bank.search.setText("gospel")
    visible = [it.text(0) for it in _bank_items(win) if it.data(0, Qt.UserRole) and not it.isHidden()]
    assert visible and all("gospel" in t.lower() for t in visible)
    win.bank.search.setText("")
    assert sum(1 for it in _bank_items(win) if it.data(0, Qt.UserRole) and not it.isHidden()) > 30


@needs_sf
def test_bank_loads_instrument_and_track_presets(win):
    win.tabs.setCurrentIndex(2)
    item = next(it for it in _bank_items(win) if it.data(0, Qt.UserRole) == ("ready", "Piano + Pad (culto)"))
    win.bank._clicked(item)
    assert win.inst.ready == "Piano + Pad (culto)" and win.tabs.currentIndex() == 2
    assert "Piano + Pad (culto)" in win.pad_view.title.text()
    win.tabs.setCurrentIndex(1)
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
def test_continuous_pad_grid_has_all_12_keys(win):
    pv = win.pad_view
    assert list(pv.cont_buttons) == ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    assert pv.cont_buttons["C#"].text() == "C#\nDb" and pv.cont_buttons["A#"].text() == "A#\nBb"
    c, cs, d = (pv.cont_buttons[k].geometry() for k in ("C", "C#", "D"))
    assert cs.bottom() < c.top() and c.center().x() < cs.center().x() < d.center().x()   # entre C e D
    QTest.mouseClick(pv.cont_buttons["D"], Qt.LeftButton)
    assert win.inst.cont_key == "D"
    QTest.mouseClick(pv.cont_buttons["C#"], Qt.LeftButton)
    assert win.inst.cont_key == "C#"
    QTest.mouseClick(pv.cont_buttons["C#"], Qt.LeftButton)      # mesmo tom de novo = para
    assert win.inst.cont_key is None
    QTest.mouseClick(pv.cont_buttons["F#"], Qt.LeftButton)
    QTest.mouseClick(pv.stop_btn, Qt.LeftButton)
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
    pv.select_layer(2)
    pv.layer_on.click()
    assert not k["layer2_on"]
    assert pv.layer == 2 and "desligada" in pv.fx_title.text()
    pv.layer_on.click()
    assert k["layer2_on"]


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


def test_bpm_box_shows_value(win, app):
    win.tabs.setCurrentIndex(2)
    app.processEvents()
    bpm = win.pad_view.bpm
    assert bpm.text() == str(win.inst.bpm) and bpm.width() >= 50
    bpm.setText("128")
    bpm.editingFinished.emit()
    assert win.inst.bpm == 128
    bpm.setText("999")
    bpm.editingFinished.emit()
    assert win.inst.bpm == 220 and bpm.text() == "220"


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
    strips = {arg: s for (kind, arg), s, *_ in win.dock.strips}
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


# ------------------------------------------------------------------ camadas e efeitos por camada
@needs_sf
def test_layers_panel_add_select_fx_and_remove(win, app):
    win.tabs.setCurrentIndex(2)
    pv = win.pad_view
    win.load_from_bank("ready", "Piano + Pad (culto)")
    QTest.mouseClick(pv.add_layer_btn, Qt.LeftButton)              # Layer 3
    QTest.mouseClick(pv.add_layer_btn, Qt.LeftButton)              # Layer 4
    app.processEvents()
    assert win.inst.layer_count() == 4 and not pv.add_layer_btn.isEnabled()
    assert pv.layer == 4 and pv.fx_title.text().startswith("Efeitos da Layer 4")
    assert all(b.isVisible() for b in pv.layer_buttons)
    # efeitos: rotação só na camada 4, drive só na 1
    pv.fx_switch["Rotação liga/desliga"].click()
    QTest.mouseClick(pv.side_layer_buttons[0], Qt.LeftButton)
    assert pv.fx_title.text().startswith("Efeitos da Layer 1")
    assert not pv.fx_switch["Rotação liga/desliga"].isChecked()      # a 1 mostra os efeitos dela
    pv.fx_switch["Drive liga/desliga"].click()
    lf = win.inst.layer_fx
    assert lf[3]["rot_on"] and not lf[0]["rot_on"] and lf[0]["drive_on"] and not lf[3]["drive_on"]
    # camada 3 só na mão esquerda
    QTest.mouseClick(pv.side_layer_buttons[2], Qt.LeftButton)
    assert pv.layer_zone.isVisible()
    pv.layer_zone.setCurrentIndex(1)
    pv.layer_zone.activated.emit(1)
    assert win.inst.extra_layers[0]["zone"] == "left"
    # remover a camada 3: a 4 (com a rotação) vira a 3
    QTest.mouseClick(pv.remove_layer_btn, Qt.LeftButton)
    assert win.inst.layer_count() == 3 and win.inst.layer_fx[2]["rot_on"]
    assert not pv.layer_buttons[3].isVisible()
    # cabe na tela com camadas extras
    app.processEvents()
    assert (win.width(), win.height()) == (1536, 800)
    side_scroll = [s for s in win.findChildren(QScrollArea) if s.isVisible() and s.verticalScrollBar().isVisible()]
    assert not side_scroll


def test_rotation_speed_slider_and_bpm_checkbox(win, app):
    win.tabs.setCurrentIndex(2)
    pv = win.pad_view
    pv.select_layer(1)
    fx = win.inst.fx
    pv.rot_speed.setCurrentIndex(1)
    pv.rot_speed.activated.emit(1)                                 # Rápida
    assert fx["rot_fast"] and fx["rot_on"]
    pv.rot_rate.setValue(50)                                       # livre: ~1,6 Hz
    assert 1.4 < fx["rot_fast_hz"] < 1.8
    assert "Hz" in pv.rot_rate_lab.text()
    QTest.mouseClick(pv.rot_sync, Qt.LeftButton)                   # segue o BPM
    assert fx["rot_sync"] and pv.rot_rate.maximum() == 7
    pv.rot_rate.setValue(3)                                        # 2 voltas por tempo
    assert fx["rot_fast_mult"] == 2.0 and pv.rot_rate_lab.text() == "2×"
    from ampsim.dsp.keysfx import K_ROT_HZ
    win.inst.set_bpm(120)
    assert win.engine.keys_fx[0].KP[K_ROT_HZ] == pytest.approx(4.0)


# ------------------------------------------------------------------ versão e "Sobre"
def test_version_in_corner_opens_about(win, app, monkeypatch):
    from ampsim.ui import about
    from ampsim.version import VERSION, version_text
    assert win.topbar.version_btn.text() == f"v{version_text()}" and VERSION in win.windowTitle()
    opened = []
    monkeypatch.setattr(about.AboutDialog, "exec", lambda self: opened.append(self) or 0)
    QTest.mouseClick(win.topbar.version_btn, Qt.LeftButton)
    assert opened and VERSION in opened[0].version_label.text()


def test_about_shows_project_data_and_copies_diagnostics(win, app):
    from PySide6.QtWidgets import QLabel, QPushButton

    from ampsim.ui.about import AboutDialog
    from ampsim.version import LICENSE, REPO_URL, version_text
    dlg = AboutDialog(win)
    texts = " ".join(lab.text() for lab in dlg.findChildren(QLabel))
    for want in (version_text(), LICENSE, REPO_URL, "igrejas", "homenagens", "FluidSynth", "GeneralUser GS"):
        assert want in texts, want
    keys = [k for k, _ in dlg.sys_lines]
    assert keys[:3] == ["Versão", "Windows", "Python"]
    copy = next(b for b in dlg.findChildren(QPushButton) if "Copiar" in b.text())
    copy.click()
    assert app.clipboard().text().startswith(f"Versão: {version_text()}")
    dlg.reject()


def test_screen_instrument_matches_settings_box(win):
    win.tabs.setCurrentIndex(2)
    win.pad_view.device.setCurrentText("M-VAVE SMK-25")
    win.pad_view.device.activated.emit(win.pad_view.device.currentIndex())
    assert win.dock.device.currentText() == "M-VAVE SMK-25"
    win.pad_view.set_device("Teclado simples")
    assert win.dock.device.currentText() == "Teclado simples"


@needs_sf
def test_continuous_pad_timbre_buttons(win, app):
    from ampsim.instruments import CONT_PAD_SOUNDS
    win.tabs.setCurrentIndex(2)
    pv = win.pad_view
    assert list(pv.cont_sound_buttons) == list(CONT_PAD_SOUNDS)
    QTest.mouseClick(pv.cont_buttons["E"], Qt.LeftButton)          # pad tocando em E
    QTest.mouseClick(pv.cont_sound_buttons["Pad Cristal"], Qt.LeftButton)
    assert win.inst.cont_sound == "Pad Cristal"
    assert win.inst.cont_key == "E"                                  # continua no mesmo tom
    assert pv.cont_sound_buttons["Pad Cristal"].isChecked()
    assert sum(b.isChecked() for b in pv.cont_sound_buttons.values()) == 1
    dock_tile = win.dock.cont_tiles[list(CONT_PAD_SOUNDS).index("Pad Cristal")]
    assert dock_tile.isChecked()                                     # aba Pads acompanha
    QTest.mouseClick(win.dock.cont_tiles[0], Qt.LeftButton)          # e o caminho inverso
    assert pv.cont_sound_buttons[CONT_PAD_SOUNDS[0]].isChecked()
    win.inst.stop_cont_pad(immediate=True)


def test_map_only_knobs_button_and_unmapped_warning(win, app):
    from PySide6.QtWidgets import QPushButton
    win.dock.show_tab(2)
    b = next(x for x in win.dock.findChildren(QPushButton) if x.text() == "Só os knobs")
    QTest.mouseClick(b, Qt.LeftButton)
    assert win.inst.learn_steps and all(k == "knobs" for k, _ in win.inst.learn_steps)
    assert "KNOB 1" in win.dock.learn_label.text()
    win.inst.stop_learning()
    win.inst.mapping["knobs"] = [None] * 8
    win.inst.handle_midi(0xB0, 75, 40)
    app.processEvents()
    assert "CC 75" in win.topbar.info2.text() and "Só os knobs" in win.topbar.info2.text()


def test_midi_monitor_and_buttons_learning(win, app):
    from PySide6.QtWidgets import QPushButton
    win.dock.show_tab(2)
    win.inst.mapping["pads_b"] = [[9, n] for n in (48, 49, 50, 51, 44, 45, 46, 47)]
    win.inst.handle_midi(0x99, 48, 100)                    # pad B1 (o M-VAVE no banco B)
    win.inst.handle_midi(0xB0, 99, 5)                      # knob sem mapeamento
    app.processEvents()
    top = [win.dock.monitor.item(i).text() for i in range(2)]
    assert "NÃO MAPEADO" in top[0] and "pad 1 do banco B" in top[1]
    assert win.inst.screen_bank == 1                       # a tela foi para o banco B
    b = next(x for x in win.dock.findChildren(QPushButton) if x.text() == "Só os botões")
    QTest.mouseClick(b, Qt.LeftButton)
    assert [k for k, _ in win.inst.learn_steps] == ["buttons"] * 8
    assert "PLAY" in win.dock.learn_label.text() or "botão" in win.dock.learn_label.text()
    win.inst.stop_learning()


def test_restart_button_when_folder_has_newer_version(win, monkeypatch):
    from ampsim import updater
    win._running_commit = "a" * 40
    monkeypatch.setattr(updater, "local_commit", lambda root=None: "b" * 40)
    assert win._check_stale() and win.topbar.update_btn.isVisibleTo(win)


def test_pitch_and_mod_move_on_the_drawing(win, app):
    win.tabs.setCurrentIndex(2)
    win.pad_view.set_device("M-VAVE SMK-25")
    c = win.pad_view.ctrl
    win.inst.handle_midi(0xE0, 127, 127)               # pitch todo para cima (16383)
    win.inst.handle_midi(0xB0, 1, 64)                  # modulação pela metade
    app.processEvents()
    assert c.pitch > 0.99 and abs(c.mod - 64 / 127) < 1e-6
    c.grab()                                           # desenha sem erro com o overlay
    win.inst.handle_midi(0xE0, 0, 64)                  # volta ao centro
    app.processEvents()
    assert abs(c.pitch) < 0.01
    win.pad_view.set_device("Teclado simples")


# ------------------------------------------------------------------ botão direito → mapear controle físico
def test_live_learn_dialog_accepts_only_the_right_kind(win, app):
    from ampsim.ui.midi_learn import MidiLearnDialog
    br = win.pad_view.bridge
    dlg = MidiLearnDialog(win.inst, br, "Knob 1 da tela", win, kinds=("cc",))
    assert win.inst.capture                               # enquanto aberto, o teclado só é monitorado
    br.monitor.emit("note", 0, 60, 100)                   # nota não serve para knob
    assert not dlg.ok.isEnabled()
    br.monitor.emit("cc", 0, 74, 90)                      # o knob girado
    assert dlg.ok.isEnabled()
    dlg._accept()
    assert dlg.choice == ["cc", 0, 74] and not win.inst.capture


def test_right_click_menus_offer_physical_mapping(win):
    pv = win.pad_view
    for kind, i in (("knob", 0), ("button", 7), ("pad", 2), ("pad", 8 + 1)):
        texts = [a.text() for a in pv.context_menu(kind, i).actions()]
        assert any(t.startswith("Mapear controle físico") for t in texts), (kind, i, texts)


def test_map_pad_b_button_by_right_click(win, monkeypatch):
    from ampsim.ui import pad_piano
    pv, inst = win.pad_view, win.inst

    class Fake:                                           # você aperta o PAD-B: chega uma nota
        def __init__(self, *a, **k):
            self.choice = ["note", 0, 98]

        def exec(self):
            return True
    monkeypatch.setattr(pad_piano, "MidiLearnDialog", Fake)
    pv.map_physical("button", 7)                          # botão direito no PAD-B da tela
    assert inst.mapping["buttons"][7] == ["note", 0, 98]
    inst.button_funcs[7] = "Banco de pads A/B (tela)"
    inst.screen_bank = 0
    keys = []
    inst.on_key = lambda n, on: keys.append(n)
    inst.handle_midi(0x90, 98, 100)                       # PAD-B: troca o banco, não toca tecla
    assert inst.screen_bank == 1 and keys == []
    inst.screen_bank = 0


def test_assign_physical_rules(win):
    pv, m = win.pad_view, win.inst.mapping
    assert pv.assign_physical("knob", 0, ["cc", 0, 21])
    assert m["knobs"][0] == [0, 21]
    assert not pv.assign_physical("knob", 1, ["note", 0, 60])   # knob não aceita nota
    assert pv.assign_physical("knob", 1, ["cc", 0, 21])         # o mesmo knob físico vai para o 2
    assert m["knobs"][0] is None and m["knobs"][1] == [0, 21]
    assert pv.assign_physical("button", 2, ["pc", 0, 7])        # botão aceita Program Change
    assert m["buttons"][2] == ["pc", 0, 7]
    assert pv.assign_physical("button", 2, [])                  # remover
    assert m["buttons"][2] is None
    assert pv.assign_physical("pad_b", 0, ["note", 9, 40])      # banco B pode repetir nota do A
    assert m["pads_b"][0] == [9, 40]
    assert pv.physical_key("knob", 1) == ["cc", 0, 21]


@needs_sf
def test_knob_moves_layer_volume_slider(win):
    """Knob do controlador mapeado para "Volume camada N": a barra Volume do painel acompanha."""
    from ampsim.instruments import KNOB_FUNCS
    assert {"Volume camada 1", "Volume camada 3", "Volume camada 4"} <= set(KNOB_FUNCS)
    pv, inst = win.pad_view, win.inst
    win.load_from_bank("ready", "Piano + Pad (culto)")
    inst.knob_funcs[0], inst.knob_funcs[1] = "Volume camada 1", "Volume camada 2"
    pv.select_layer(2)
    inst.set_knob(1, 127)
    QApplication.processEvents()
    win._sync_knob_values()                     # o que o timer de ~30 ms faz
    assert inst.keys["vol2"] == 127 and pv.layer_vol.value() == 127 and pv.layer_vol_lab.text() == "100%"
    inst.set_knob(0, 0)                         # camada 1 não está no painel: a barra da 2 não muda
    win._sync_knob_values()
    assert inst.keys["vol1"] == 0 and pv.layer_vol.value() == 127
    pv.select_layer(1)
    assert pv.layer_vol.value() == 0
    inst.knob_funcs[2] = "Volume camada 4"      # camada que não existe: nada acontece
    inst.set_knob(2, 90)
    assert len(inst.extra_layers) == 0


@needs_sf
def test_knob_from_midi_thread_moves_volume_slider(win):
    """O knob chega pela thread do MIDI (como no PSR): a barra Volume acompanha sem chamar nada à mão."""
    import threading
    import time
    pv, inst = win.pad_view, win.inst
    win.load_from_bank("ready", "Piano + Pad (culto)")
    inst.mapping["knobs"][1] = [1, 71]
    inst.knob_funcs[1] = "Volume camada 2"
    pv.select_layer(2)
    t = threading.Thread(target=lambda: [inst.handle_midi(0xB1, 71, v) for v in (20, 60, 100, 127)])
    t.start()
    t.join()
    end = time.monotonic() + 2.0
    while time.monotonic() < end and pv.layer_vol.value() != 127:
        QApplication.processEvents()
        time.sleep(0.01)
    assert inst.keys["vol2"] == 127
    assert pv.layer_vol.value() == 127 and pv.ctrl.knob_values[1] == 127


@needs_sf
def test_volume_faders_in_faders_pads_tab(win):
    """Faders L1-L4, pad contínuo e pads na aba Faders / Pads (não mais em Configurações)."""
    from PySide6.QtWidgets import QSlider
    d, pv, inst = win.dock, win.pad_view, win.inst
    assert d.tab_buttons[1].text().strip() == "Faders / Pads"
    assert not d.stack.widget(3).findChildren(QSlider)                 # Configurações sem faders
    win.load_from_bank("ready", "Piano + Pad (culto)")
    f = {func: (s, val, layer) for func, layer, s, val, _n in d.vol_faders}
    assert set(f) == {"Volume camada 1", "Volume camada 2", "Volume camada 3", "Volume camada 4",
                      "Volume pad contínuo", "Volume bateria"}
    assert not f["Volume camada 3"][0].isEnabled()          # só 2 camadas: L3/L4 esperando o "+"
    pv.select_layer(1)
    f["Volume camada 1"][0].setValue(50)
    assert inst.keys["vol1"] == round(0.5 * 127) and pv.layer_vol.value() == inst.keys["vol1"]
    pv.layer_vol.setValue(127)                               # barra do painel -> fader acompanha
    assert f["Volume camada 1"][0].value() == 100
    f["Volume bateria"][0].setValue(30)
    assert inst.levels["drums"] == 30
    inst.add_layer()
    win.refresh_sounds()
    assert f["Volume camada 3"][0].isEnabled()


def test_every_timbre_has_a_photo(app):
    """Cada timbre tem a própria imagem (arquivo existe, abre, não se repete) e crédito no CREDITS.md."""
    import os

    from ampsim.instruments import SOUNDS
    from ampsim.ui.widgets import PHOTO_BY_NAME, PHOTO_DIR, ArtTile, _photo, photo_for
    names = [photo_for(s.cat, s.name) for s in SOUNDS]
    assert len(set(names)) == len(SOUNDS), "dois timbres com a mesma foto"
    for s, name in zip(SOUNDS, names):
        assert s.name in PHOTO_BY_NAME and _photo(name) is not None, (s.name, name)
    t = ArtTile(84)
    t.set_kind("Pianos elétricos", "Rhodes")
    assert t.photo == "rhodes"
    assert photo_for("Pianos", "Timbre novo") == "piano-cauda"
    credits = open(os.path.join(os.path.dirname(PHOTO_DIR), "..", "CREDITS.md"), encoding="utf-8").read()
    files = sorted(os.listdir(PHOTO_DIR))
    assert len(files) == len(SOUNDS)
    for f in files:
        if not f.startswith("synth-"):                 # synth-*: arte gerada pelo próprio AmpSim
            assert f"assets/timbres/{f}" in credits, f"{f} sem crédito no CREDITS.md"


@needs_sf
def test_emergency_mute_on_faders(win):
    """Mute de emergência: silencia sem mexer no fader e fica bem sinalizado (botão, fader e painel)."""
    d, pv, inst = win.dock, win.pad_view, win.inst
    win.load_from_bank("ready", "Piano + Pad (culto)")
    pv.select_layer(1)
    f = {func: (s, val, name) for func, layer, s, val, name in d.vol_faders}
    s, val, name = f["Volume camada 1"]
    before = s.value()
    b = d.mute_buttons["Volume camada 1"]
    b.click()
    assert inst.layer_muted(1) and s.value() == before                # o fader fica onde estava
    assert b.text() == "MUDO" and val.text() == "SEM SOM" and pv.layer_vol_lab.text() == "MUDO"
    inst.set_layer_volume(1, 100)                                      # mexer no volume não tira o mute
    assert inst.layer_muted(1)
    b.click()
    assert not inst.layer_muted(1) and b.text() == "M" and val.text().endswith("%")
    d.mute_buttons["Volume bateria"].click()
    d.mute_buttons["Volume pad contínuo"].click()
    assert inst.drums_gain() == 0.0 and inst.pad_gain() == 0.0
    assert f["Volume bateria"][1].text() == "SEM SOM"
    d.mute_buttons["Volume bateria"].click()
    assert inst.drums_gain() > 0.0


@needs_sf
def test_big_photo_follows_selected_layer(win):
    pv = win.pad_view
    win.load_from_bank("ready", "Piano de Concerto")             # piano + cordas lentas
    pv.select_layer(1)
    assert pv.art.photo == "piano-cauda"
    pv.select_layer(2)
    assert pv.art.photo == "cordas-lentas" and pv.layer_art.photo == "cordas-lentas"



def test_recorder_panel_rec_stop_bank_and_pads(win, monkeypatch):
    """REC/STOP grava no banco; a gravação vai para um pad, pode ser renomeada e apagada."""
    import numpy as np

    from ampsim.audio.sampler import REC_PREFIX
    from ampsim.instruments import PAD_PRESETS
    d, inst, e = win.dock, win.inst, win.engine
    d.show_tab(1)
    rec = d.recorder
    monkeypatch.setattr(type(e), "running", property(lambda self: True))
    rec.refresh()
    assert rec.source.itemData(0) == "out" and not rec.play_btn.isEnabled()
    rec.start()
    assert e.recorder.active and rec.rec_btn.text() == "● GRAVANDO" and rec.stop_btn.isEnabled()
    t = np.arange(24000) / 48000.0
    x = (0.3 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    e.recorder.feed(np.stack([x, x], axis=1))
    name = rec.stop()
    assert name == "Gravação 01" and rec.current() == name and name in e.sampler.samples
    assert rec.rec_btn.text() == "● REC" and rec.play_btn.isEnabled()
    rec.assign(2, name)
    assert inst.pad_sounds[2] == REC_PREFIX + name and "● Gravação 01" in d.mix_pad_tiles[2].text()
    inst.pad_hit(2, 120)
    assert e.sampler.events                                    # o pad manda tocar a gravação
    monkeypatch.setattr("ampsim.ui.recorder.QInputDialog.getText", staticmethod(lambda *a, **k: ("Intro", True)))
    rec.rename()
    assert inst.pad_sounds[2] == REC_PREFIX + "Intro" and "Intro" in e.sampler.samples
    assert "Gravação 01" not in e.sampler.samples
    rec.delete()                                               # a confirmação responde Sim (fixture)
    assert inst.pad_sounds[2] == list(PAD_PRESETS.values())[0][2] and rec.current() is None
    rec.start()
    assert rec.stop() is None                                  # só silêncio: nada vai para o banco


def test_pad_eq_drag_points_on_the_curve(win):
    """EQ do pad contínuo: arrastar os pontos na curva muda o EQ e os knobs; knob move o ponto."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtCore import QEvent, QPoint

    from ampsim.ui.analyzer import PadEqDialog, _fx
    inst = win.inst
    inst.set_pad_eq(on=False)
    dlg = PadEqDialog(inst, "#e8a33d", win)
    dlg.resize(760, 470)
    dlg.show()
    QApplication.processEvents()
    g = dlg.graph
    r = g._area()

    def drag(i, to):
        start = g._handle_pos(g.handles[i], r)
        for kind, pos, btn in ((QEvent.MouseButtonPress, start, Qt.LeftButton),
                               (QEvent.MouseMove, to, Qt.LeftButton),
                               (QEvent.MouseButtonRelease, to, Qt.NoButton)):
            ev = QMouseEvent(kind, pos, g.mapToGlobal(pos), Qt.LeftButton, btn, Qt.NoModifier)
            QApplication.sendEvent(g, ev)

    labels = [h.label for h in g.handles]
    mid = labels.index("Médios")
    drag(mid, QPointF(_fx(1000.0, r.left(), r.width()), g._y(6.0, r)))
    pe = inst.pad_eq
    assert pe["on"] and dlg.on.isChecked()                     # mexeu na curva: liga o EQ
    assert pe["mid"] == pytest.approx(6.0, abs=0.5) and pe["mid_f"] == pytest.approx(1000.0, rel=0.05)
    assert dlg.knobs["mid"].value() == pytest.approx(pe["mid"]) and dlg.knobs["mid_f"].value() == pytest.approx(pe["mid_f"])
    drag(labels.index("Corte grave"), QPointF(_fx(200.0, r.left(), r.width()), r.center().y()))
    assert pe["lowcut"] == pytest.approx(200.0, rel=0.05) and dlg.knobs["lowcut"].value() == pytest.approx(pe["lowcut"])
    drag(labels.index("Agudos"), QPointF(_fx(4500.0, r.left(), r.width()), g._y(-9.0, r)))
    assert pe["high"] == pytest.approx(-9.0, abs=0.5)
    q0 = pe["mid_q"]
    c = g._handle_pos(g.handles[mid], r)
    QApplication.sendEvent(g, QWheelEvent(c, g.mapToGlobal(c), QPoint(), QPoint(0, 120), Qt.NoButton,
                                          Qt.NoModifier, Qt.NoScrollPhase, False))
    assert pe["mid_q"] > q0 and dlg.knobs["mid_q"].value() == pytest.approx(pe["mid_q"])
    QTest.mouseDClick(g, Qt.LeftButton, pos=c.toPoint())
    assert pe["mid"] == 0.0 and pe["mid_f"] == 900.0           # duplo-clique: volta ao padrão
    dlg.knobs["high"].setValue(3.0, emit=True)                 # knob -> ponto acompanha
    assert g.values["high"] == 3.0
    dlg.close()



def test_bank_shows_only_presets_of_the_open_tab(win):
    def kinds():
        out = set()
        for it in _bank_items(win):
            d = it.data(0, Qt.UserRole)
            if d:
                out.add(d[1][0] if d[0] == "track" else d[0])
        return out
    win.tabs.setCurrentIndex(0)
    assert kinds() == {"guitar"}
    win.tabs.setCurrentIndex(1)
    assert kinds() == {"bass"}
    win.tabs.setCurrentIndex(2)
    assert kinds() >= {"ready", "pads"} and not kinds() & {"guitar", "bass"}


@needs_sf
def test_bank_right_click_parts(win):
    """Botão direito: timbre na L1/L2/camada nova, só os efeitos; guitarra: só amp, só pedais, no baixo."""
    from ampsim.instruments import READY
    b, inst, pv = win.bank, win.inst, win.pad_view
    win.tabs.setCurrentIndex(2)
    win.load_from_bank("ready", "Piano de Concerto")
    texts = [a.text() for a in b.context_menu("ready", "Órgão Gospel (rotação)").actions() if a.text()]
    assert any("na L1" in t for t in texts) and any("na L2" in t for t in texts)
    sound = READY["Órgão Gospel (rotação)"]["sound1"]
    win.load_part("ready", "Órgão Gospel (rotação)", "l2")
    assert inst.keys["sound2"] == sound and inst.keys["layer2_on"] and pv.layer == 2
    assert inst.keys["sound1"] == READY["Piano de Concerto"]["sound1"]      # a L1 não mudou
    win.load_part("ready", "Órgão Gospel (rotação)", "new_layer")
    assert inst.layer_count() == 3 and inst.extra_layers[0]["sound"] == sound
    pv.select_layer(1)
    win.load_part("ready", "Órgão Gospel (rotação)", "fx")
    fx = READY["Órgão Gospel (rotação)"].get("fx", {})
    assert all(inst.layer_fx[0][k] == v for k, v in fx.items() if k in inst.layer_fx[0])
    win.load_part("ready", "Pad Halo Contínuo (nas teclas)", "cont")
    assert inst.cont_sound == READY["Pad Halo Contínuo (nas teclas)"]["sound1"]
    # guitarra: só o amp mantém os pedais atuais; "no baixo" carrega na outra trilha
    win.tabs.setCurrentIndex(0)
    g = win.engine.tracks["guitar"]
    g.set_on("delay", True)
    win.load_part("track", ("guitar", "factory", "Hi-Gain Rítmico"), "amp")
    assert g.values["delay"]["on"] and g.values["amp"]["on"]
    win.load_part("track", ("guitar", "factory", "Crunch Clássico"), "fx")
    assert not g.values["delay"]["on"] and g.values["reverb"]["on"]
    texts = [a.text() for a in b.context_menu("track", ("guitar", "factory", "Crunch Clássico")).actions()]
    assert "Carregar no Baixo" in texts
    win.load_part("track", ("guitar", "factory", "Crunch Clássico"), "other")
    assert win.tabs.currentIndex() == 1 and win.engine.tracks["bass"].values["reverb"]["on"]


def test_shortcuts_mute_all_and_actions(win, monkeypatch):
    from ampsim.ui.shortcuts import DEFAULTS, ShortcutsDialog, clean_keys, conflicts
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    e, inst = win.engine, win.inst
    assert win.shortcuts.keys == DEFAULTS and len(win.shortcuts._items) == len(DEFAULTS)
    win.activateWindow()
    QTest.keyClick(win, Qt.Key_Space, Qt.AltModifier)          # Alt+Espaço de verdade
    QApplication.processEvents()
    if not e.muted:                                            # sem foco de janela (offscreen): pela ação
        win.shortcut_action("mute_all")
    assert e.muted and win.mute_banner.isVisible()
    win.mute_banner.click()                                    # clicar na faixa volta o som
    assert not e.muted and not win.mute_banner.isVisible()
    win.shortcut_action("mute_l1")
    assert inst.layer_muted(1) and win.dock.mute_buttons["Volume camada 1"].text() == "MUDO"
    win.shortcut_action("mute_l1")
    assert not inst.layer_muted(1)
    win.shortcut_action("tab_bass")
    assert win.current_kind() == "bass"
    win.shortcut_action("tab_pads")
    assert win.current_kind() == "pads"
    assert conflicts({"a": "Ctrl+R", "b": "Ctrl+R", "c": ""}) == {"Ctrl+R": ["a", "b"]}
    assert clean_keys({"rec": "Ctrl+Shift+R", "inventada": "X"})["rec"] == "Ctrl+Shift+R"
    dlg = ShortcutsDialog(win.shortcuts, win)
    from PySide6.QtGui import QKeySequence
    dlg.edits["rec"].setKeySequence(QKeySequence("Ctrl+T"))    # igual ao tap: recusa
    dlg.accept()
    assert win.shortcuts.keys["rec"] == "Ctrl+R" and "Ctrl+T" in warned[0]
    dlg.edits["rec"].setKeySequence(QKeySequence("Ctrl+G"))
    dlg.accept()
    assert win.shortcuts.keys["rec"] == "Ctrl+G"
    win.save_state()
    assert storage.load_state()["ui"]["shortcuts"]["rec"] == "Ctrl+G"
    dlg = ShortcutsDialog(win.shortcuts, win)
    dlg.restore()
    dlg.accept()
    assert win.shortcuts.keys == DEFAULTS


def test_pitch_function_combo_in_midi_tab(win):
    from ampsim.instruments import PITCH_FUNCS
    d = win.dock
    d.show_tab(2)
    i = d.pitch_combo.findText(PITCH_FUNCS[1])
    d.pitch_combo.setCurrentIndex(i)
    d.pitch_combo.activated.emit(i)
    assert win.inst.pitch_func == PITCH_FUNCS[1]


def test_right_click_pitch_on_drawing_chooses_function(win):
    """Botão direito no pitch desenhado (faixa, roda ou alavanca): escolhe a função, como nos knobs."""
    from ampsim.instruments import PITCH_FUNCS
    pv = win.pad_view
    for model in ("M-VAVE SMK-25", "Yamaha PSR-E473", "Roland VR-730"):
        pv.ctrl.set_model(model)
        r = pv.ctrl._pitch_rect()
        assert pv.ctrl._hit(r.center()) == ("pitch", 0), model
    menu = pv.context_menu("pitch", 0)
    acts = {a.text(): a for a in menu.actions() if a.text() in PITCH_FUNCS}
    assert set(acts) == set(PITCH_FUNCS) and acts[PITCH_FUNCS[0]].isChecked()
    acts[PITCH_FUNCS[2]].trigger()
    assert win.inst.pitch_func == PITCH_FUNCS[2]
    win.dock.refresh()
    assert win.dock.pitch_combo.currentText() == PITCH_FUNCS[2]


def test_psr_knob_on_two_channels_is_one_knob(win):
    """PSR: cada knob chega nos canais 1 e 2 juntos; conta como um só (aprendizado e uso)."""
    inst, pv = win.inst, win.pad_view
    m = inst.mapping
    m["knobs"] = [[0, 74], [1, 74], [0, 71], [1, 71], None, None, None, None]     # como ficou no PSR
    inst.knob_funcs[2], inst.knob_funcs[3] = "Volume pad contínuo", "Reverb"
    rev = inst.levels["reverb"]
    inst.handle_midi(0xB0, 71, 30)
    inst.handle_midi(0xB1, 71, 30)                              # cópia da parte Dual: ignorada
    assert inst.knob_values[2] == 30 and inst.levels["reverb"] == rev
    # mapear o KNOB B físico no knob 2 da tela tira o CC 71 dos slots escondidos (os dois canais)
    pv.assign_physical("knob", 1, ["cc", 0, 71])
    assert m["knobs"][1] == [0, 71] and m["knobs"][2] is None and m["knobs"][3] is None
    menu = pv.context_menu("knob", 1)
    assert any(a.text().startswith("Remover mapeamento") for a in menu.actions())
    pv.assign_physical("knob", 1, [])
    assert m["knobs"][1] is None
    # assistente: girar o knob (que manda nos 2 canais) ocupa um passo só
    inst.start_learning(("knobs",))
    for v in (10, 20, 30):
        inst.handle_midi(0xB0, 74, v)
        inst.handle_midi(0xB1, 74, v)
    assert m["knobs"][0] == [0, 74] and inst.learn_steps and inst.learn_steps[0] == ("knobs", 1)
    inst.stop_learning()
    win.dock.refresh()
    assert "CC 74" in win.dock.knob_combos[0].toolTip()


def test_keys_learned_as_pads_can_be_removed(win):
    """Teclas do PSR aprendidas como pads (G# tocando bateria): dá para tirar um ou todos."""
    inst, pv = win.inst, win.pad_view
    m = inst.mapping
    m["pads"][3] = [0, 68]                                       # G#4 virou o pad 4
    hits = []
    inst.on_pad = lambda i, v: hits.append(i)
    inst.handle_midi(0x90, 68, 100)
    assert hits == [3]
    menu = pv.context_menu("pad", 3)
    texts = [a.text() for a in menu.actions()]
    assert any(t.startswith("Remover mapeamento") for t in texts)
    pv.assign_physical("pad", 3, [])
    assert m["pads"][3] is None
    hits.clear()
    inst.handle_midi(0x90, 68, 100)                              # agora é tecla de novo
    assert hits == []
    inst.handle_midi(0x80, 68, 0)
    m["pads_b"][0] = [0, 76]
    pv.clear_pad_mapping()
    assert all(k is None for k in m["pads"] + m["pads_b"])


def test_new_midi_controller_warns_and_old_one_comes_back(win, monkeypatch):
    """Trocar de controlador: novo -> avisa e oferece mapear; antigo -> os mapeamentos dele voltam."""
    class FakeMidi:
        name = None

        def open(self, name):
            self.name = name

        def close(self):
            pass
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    inst = win.inst
    win.midi = FakeMidi()
    inst.midi_device = "2- Digital Keyboard-1"
    inst.mapping["knobs"][0] = [0, 74]
    win._open_midi("SMK-25")
    assert asked and "ainda não foi mapeado" in asked[0] and not inst.learn_steps
    assert inst.mapping["knobs"][0] is None and inst.mapping["pads"][0] == [9, 40]
    win._open_midi("2- Digital Keyboard-1")
    assert len(asked) == 1 and inst.mapping["knobs"][0] == [0, 74]
    assert any("de volta" in line for line in win.dock.midi_log)


def test_audio_reconnects_by_itself(win, monkeypatch):
    """Cabo USB solto: avisa "Áudio caiu" e religa quando a placa volta; desligado no botão não religa."""
    from ampsim.audio import devices as dev
    e = win.engine
    state = {"running": True, "present": False, "starts": 0}
    monkeypatch.setattr(type(e), "running", property(lambda self: state["running"]))
    monkeypatch.setattr(type(e), "lost", property(lambda self: False))
    monkeypatch.setattr(e, "stop", lambda: state.update(running=False))
    monkeypatch.setattr(e, "start", lambda cfg: state.update(running=True, starts=state["starts"] + 1))
    monkeypatch.setattr(dev, "refresh", lambda: None)
    monkeypatch.setattr(dev, "find_device", lambda api, name, kind: object() if state["present"] else None)
    win._want_audio = True
    assert not win.watch_audio(0.0)                              # tudo ligado: nada a fazer
    state["running"] = False                                     # o stream morreu (cabo solto)
    assert not win.watch_audio(1.0) and win.topbar.power_title.text() == "Áudio desligado"
    assert "caiu" in win.topbar.info1.text()
    assert not win.watch_audio(2.0)                              # ainda dentro dos 3 s
    assert not win.watch_audio(4.5)                              # tentou: placa ainda não voltou
    state["present"] = True
    assert win.watch_audio(8.0) and state["running"] and state["starts"] == 1
    assert win._reconnect_at is None and any("religado" in line for line in win.dock.midi_log)
    win.toggle_power(False)                                      # o usuário desligou: não religa
    assert not win.watch_audio(20.0) and not state["running"]


def test_click_button_asks_for_output_and_dialog_choices(win, monkeypatch):
    from ampsim.audio import devices as dev
    from ampsim.ui.audio_dialog import AudioDialog
    e, pv = win.engine, win.pad_view
    answers = [QMessageBox.No, QMessageBox.Yes]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answers.pop(0)))
    e.click_offset = -2
    e.config.click_offset = -2
    pv._action("Metrônomo liga/desliga")                         # sem saída: pergunta; "Não" = continua desligado
    assert not e.metronome.on
    pv._action("Metrônomo liga/desliga")                         # "Sim": toca na saída principal
    assert e.metronome.on and e.config.click_offset == -1
    assert pv.action_buttons["Metrônomo liga/desliga"].isChecked()
    win.shortcut_action("click")                                  # Ctrl+M desliga
    assert not e.metronome.on
    menu_items = []
    from PySide6.QtWidgets import QMenu
    m = QMenu()
    pv._click_menu(m)
    menu_items = [a.text() for a in m.actions()]
    assert any(t.startswith("Volume") for t in menu_items) and "Compasso" in menu_items
    D = dev.Device
    devs = {"ASIO": [D(1, "Placa 4", 0, 4, 48000.0)]}
    monkeypatch.setattr(dev, "hostapis", lambda: ["ASIO"])
    monkeypatch.setattr(dev, "devices", lambda api, kind: [d for d in devs.get(api, [])
                                                         if (d.max_out if kind == "output" else d.max_in)])
    monkeypatch.setattr(dev, "supported_rates", lambda *a, **k: [48000])
    e.config = dev.AudioConfig(hostapi="ASIO", output_device="Placa 4", samplerate=48000, click_offset=2)
    dlg = AudioDialog(e, win)
    datas = [dlg.click_pair.itemData(i) for i in range(dlg.click_pair.count())]
    assert datas == [-2, -1, 2] and dlg.click_pair.currentData() == 2
    cfg, _ = dlg.result_config()
    assert cfg.click_offset == 2
    dlg.reject()


def test_packs_dialog_install_and_offer(win, monkeypatch, tmp_path):
    import hashlib
    import zipfile
    from ampsim.audio import packs
    from ampsim.ui.packs_dialog import PacksDialog
    monkeypatch.setenv("AMPSIM_PACKS_DIR", str(tmp_path / "timbres"))
    src = tmp_path / "p.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("x/UprightPianoKW-20220221.sf2", b"RIFF-falso")
    real = packs.PACK_BY_ID["piano-upright"]
    fake = packs.Pack(real.id, real.nome, real.descricao, real.licenca, 1, 1, real.url,
                      hashlib.sha256(src.read_bytes()).hexdigest(), real.arquivo, real.sound)
    monkeypatch.setattr(packs, "PACKS", (fake,) + packs.PACKS[1:])
    monkeypatch.setitem(packs.PACK_BY_ID, fake.id, fake)
    dlg = PacksDialog(win)
    status, bar, btn = dlg.rows[fake.id]
    assert btn.text() == "Baixar" and "Não instalado" in status.text()
    dlg.download(fake, source=src, wait=True)
    QApplication.processEvents()
    assert dlg.busy is None and btn.text() == "Remover" and "Instalado" in status.text()
    dlg.toggle(fake)                                             # remover (a confirmação responde Sim)
    assert btn.text() == "Baixar" and packs.sf2_path(fake) is None
    dlg.reject()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    assert win.offer_pack("Piano de Cauda Salamander") and "ainda não está no computador" in asked[0]
    assert not win.offer_pack("Piano de Cauda")                  # timbre normal: nada a oferecer


def test_pad_follow_combo(win):
    from ampsim.instruments import PAD_FOLLOW
    d = win.dock
    d.show_tab(0)
    i = d.follow.findText(PAD_FOLLOW[1])
    d.follow.setCurrentIndex(i)
    d.follow.activated.emit(i)
    assert win.inst.pad_follow == PAD_FOLLOW[1] and "segue o acorde" in win.pad_view.cont_title.text()
    d.follow.activated.emit(0)
    assert win.pad_view.cont_title.text() == "Pad contínuo"


def test_pianos_downloaded_by_installer_install_on_first_open(win, monkeypatch, tmp_path):
    import hashlib
    import zipfile
    from ampsim.audio import packs
    monkeypatch.setenv("AMPSIM_PACKS_DIR", str(tmp_path / "timbres"))
    pend = tmp_path / "timbres" / "_instalar"
    pend.mkdir(parents=True)
    src = pend / "piano-upright.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("UprightPianoKW-20220221.sf2", b"RIFF-falso")
    real = packs.PACK_BY_ID["piano-upright"]
    fake = packs.Pack(real.id, real.nome, real.descricao, real.licenca, 1, 1, real.url,
                      hashlib.sha256(src.read_bytes()).hexdigest(), real.arquivo, real.sound)
    monkeypatch.setattr(packs, "PACKS", (fake,))
    monkeypatch.setitem(packs.PACK_BY_ID, fake.id, fake)
    assert win.install_pending_packs()
    import time
    end = time.time() + 10
    while packs.sf2_path(fake) is None and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        QApplication.processEvents()
    assert packs.sf2_path(fake) is not None and not src.exists()        # instalado e o arquivo apagado
    assert not win.install_pending_packs()                                # nada mais pendente
    for w in QApplication.topLevelWidgets():
        if w.windowTitle() == "Timbres adicionais":
            w.close()
