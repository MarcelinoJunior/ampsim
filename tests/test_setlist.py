"""Setlist: músicas com o som guardado, ordem, anterior/próxima, vários setlists e arquivo salvo."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ampsim import setlist, storage  # noqa: E402
from ampsim.audio.soundfont import available  # noqa: E402

needs_sf = pytest.mark.skipif(not available(), reason="timbres não baixados (tools/baixar_extras.py)")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "app" / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "app" / "presets")
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


@needs_sf
def test_songs_keep_their_sound(win):
    sl, inst = win.setlist, win.inst
    win.load_from_bank("ready", "Piano + Pad (culto)")
    inst.set_bpm(72)
    sl.add_song("Grandes Coisas")
    win.load_from_bank("ready", "Órgão Gospel (rotação)")
    inst.set_bpm(128)
    inst.set_cont_sound("Pad Órgão")
    sl.add_song("Bondade de Deus")
    assert [s["nome"] for s in sl.songs_list()] == ["Grandes Coisas", "Bondade de Deus"]
    assert sl.load_song(0)
    assert inst.ready == "Piano + Pad (culto)" and inst.bpm == 72 and sl.current == 0
    assert "Grandes Coisas" in win.topbar.info2.text()
    assert sl.step(1) and inst.ready == "Órgão Gospel (rotação)" and inst.bpm == 128
    assert inst.cont_sound == "Pad Órgão"
    assert sl.step(1) and sl.current == 0                         # dá a volta
    assert sl.step(-1) and sl.current == 1
    # arquivo salvo: abre de novo igual
    data = json.loads(setlist.path().read_text(encoding="utf-8"))
    assert [s["nome"] for s in data["listas"][data["atual"]]] == ["Grandes Coisas", "Bondade de Deus"]


@needs_sf
def test_pad_follows_song_key_when_playing(win):
    sl, inst = win.setlist, win.inst
    inst.start_cont_pad("C")
    sl.add_song("Em D")
    sl.songs_list()[-1]["som"]["pad_tom"] = "D"
    sl.add_song("Em G")
    sl.songs_list()[-1]["som"]["pad_tom"] = "G"
    sl.load_song(0)
    assert inst.cont_key == "D"
    sl.load_song(1)
    assert inst.cont_key == "G"
    inst.stop_cont_pad(immediate=True)
    sl.load_song(0)
    assert inst.cont_key is None                                   # parado continua parado


def test_reorder_rename_remove_and_lists(win):
    sl = win.setlist
    for n in ("A", "B", "C"):
        sl.add_song(n)
    sl.current = 2
    it = sl.songs.takeItem(2)                                      # arrastar "C" para o topo
    sl.songs.insertItem(0, it)
    sl._reordered()
    assert [s["nome"] for s in sl.songs_list()] == ["C", "A", "B"] and sl.current == 0
    sl.rename_song(1, "A2")
    sl.remove_song(2, ask=False)
    assert [s["nome"] for s in sl.songs_list()] == ["C", "A2"]
    assert sl.new_list("Culto de domingo") == "Culto de domingo" and sl.songs_list() == []
    assert sl.new_list("Culto de domingo") is None                 # nome repetido
    sl.rename_list("Domingo")
    assert "Domingo" in sl.data["listas"] and sl.lists.currentText() == "Domingo"
    sl.delete_list(ask=False)
    assert sl.data["atual"] == setlist.DEFAULT_LIST and len(sl.songs_list()) == 2
    sl.set_folded(True)
    assert not sl.body.isVisible() and setlist.load()["recolhido"]
    sl.set_folded(False)


def test_broken_file_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "APP_DIR", tmp_path)
    setlist.path().write_text("{ não é json", encoding="utf-8")
    assert setlist.load() == setlist.empty()
    setlist.path().write_text(json.dumps({"atual": "X", "listas": {"X": [{"nome": 3}, {"nome": "ok", "som": {}}]}}),
                              encoding="utf-8")
    d = setlist.load()
    assert d["atual"] == "X" and [s["nome"] for s in d["listas"]["X"]] == ["ok"]


def test_next_song_from_controller_button_and_shortcut(win):
    sl, inst = win.setlist, win.inst
    sl.add_song("1")
    sl.add_song("2")
    sl.load_song(0)
    inst.do_button("Próxima música")                              # pedal/botão do controlador
    QApplication.processEvents()
    assert sl.current == 1
    win.shortcut_action("song_prev")
    assert sl.current == 0
    assert win.shortcuts.keys["song_next"] == "Ctrl+PgDown"
