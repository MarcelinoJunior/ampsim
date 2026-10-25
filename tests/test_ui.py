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
