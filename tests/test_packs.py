"""Timbres adicionais: instalar/remover pacotes de pianos, conferir o arquivo e tocar com eles."""
import hashlib
import io
import os
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ampsim.audio import packs  # noqa: E402
from ampsim.audio.soundfont import available  # noqa: E402

UPRIGHT_ZIP = Path(os.environ.get("TEMP", "")) / "pianos" / "piano-upright.zip"
needs_sf = pytest.mark.skipif(not available(), reason="timbres não baixados (tools/baixar_extras.py)")
needs_zip = pytest.mark.skipif(not UPRIGHT_ZIP.exists(), reason="pacote do piano não está no computador")


@pytest.fixture()
def pdir(tmp_path, monkeypatch):
    monkeypatch.setenv("AMPSIM_PACKS_DIR", str(tmp_path / "timbres"))
    return tmp_path / "timbres"


def fake_pack(tmp_path, kind):
    """Pacote pequeno de mentira (.zip ou .tar.xz) com um "sf2" e a licença."""
    data = {"Coisa.sf2": b"RIFF" + os.urandom(2000), "licenca.txt": b"CC0", "../fora.sf2": b"x"}
    path = tmp_path / ("pack.zip" if kind == "zip" else "pack.tar.xz")
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as z:
            for k, v in data.items():
                z.writestr("pasta/" + k, v)
    else:
        with tarfile.open(path, "w:xz") as t:
            for k, v in data.items():
                info = tarfile.TarInfo("pasta/" + k)
                info.size = len(v)
                t.addfile(info, io.BytesIO(v))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    url = "https://exemplo/" + path.name
    return packs.Pack("teste-" + kind, "Teste", "", "CC0", 1, 1, url, sha, "Coisa.sf2", "Piano de Cauda"), path


@pytest.mark.parametrize("kind", ["zip", "tarxz"])
def test_install_and_remove(pdir, tmp_path, kind):
    p, src = fake_pack(tmp_path, kind)
    path = packs.install(p, source=src)
    assert path == pdir / p.id / "Coisa.sf2" and path.exists()
    assert (pdir / p.id / "licenca.txt").exists()
    assert not (pdir / "fora.sf2").exists()                      # nada sai da pasta do pacote
    assert packs.sf2_path(p) == path
    packs.remove(p)
    assert packs.sf2_path(p) is None


def test_wrong_file_is_refused(pdir, tmp_path):
    p, src = fake_pack(tmp_path, "zip")
    bad = packs.Pack(p.id, p.nome, "", "", 1, 1, p.url, "0" * 64, p.arquivo, p.sound)
    with pytest.raises(packs.PackError):
        packs.install(bad, source=src)
    assert packs.sf2_path(bad) is None and not list(pdir.glob("*.tmp"))


def test_not_enough_disk(pdir, tmp_path, monkeypatch):
    import shutil
    from collections import namedtuple
    p, src = fake_pack(tmp_path, "zip")
    du = namedtuple("du", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: du(10, 10, 1000))
    with pytest.raises(packs.PackError, match="Espaço"):
        packs.install(p, source=src)


def test_catalog_matches_sounds():
    from ampsim.instruments import SOUND_BY_NAME
    from ampsim.ui.widgets import PHOTO_BY_NAME
    for p in packs.PACKS:
        s = SOUND_BY_NAME[p.sound]
        assert s.pack == p.id and s.cat == "Pianos" and p.sound in PHOTO_BY_NAME
        assert p.url.startswith("https://github.com/MarcelinoJunior/ampsim/releases/download/")
        assert len(p.sha256) == 64


@needs_sf
@needs_zip
def test_real_upright_piano_plays(pdir):
    from ampsim.audio.engine import AudioEngine
    from ampsim.dsp.kernels import warmup
    p = packs.PACK_BY_ID["piano-upright"]
    warmup()
    e = AudioEngine()
    inst = e.instruments
    assert inst.pack_missing("Piano de Armário (Upright)") is p
    packs.install(p, source=UPRIGHT_ZIP)
    assert inst.pack_missing("Piano de Armário (Upright)") is None
    inst.load_packs()
    assert "piano-upright" in inst.sf.fonts
    inst.set_sound(1, "Piano de Armário (Upright)")
    inst.keys["layer2_on"] = False
    out = np.zeros((256, 2), np.float32)
    inst.key_on(60, 100)
    peak = 0.0
    for _ in range(60):
        e._render(None, out, 256)
        peak = max(peak, float(np.abs(out).max()))
    inst.key_off(60)
    assert peak > 0.01


@needs_sf
def test_missing_pack_falls_back_to_grand_piano(pdir):
    from ampsim.audio.engine import AudioEngine
    from ampsim.dsp.kernels import warmup
    warmup()
    e = AudioEngine()
    inst = e.instruments
    inst.set_sound(1, "Piano de Cauda Salamander")              # não instalado: toca o piano padrão
    inst.keys["layer2_on"] = False
    out = np.zeros((256, 2), np.float32)
    inst.key_on(60, 100)
    peak = 0.0
    for _ in range(40):
        e._render(None, out, 256)
        peak = max(peak, float(np.abs(out).max()))
    assert peak > 0.01


def test_installer_downloads_are_found(pdir, tmp_path, monkeypatch):
    """Pacote que o instalador deixou em <AmpSim>/_timbres (programa instalado) ou <timbres>/_instalar."""
    import sys
    app = tmp_path / "AmpSim"
    (app / "_timbres").mkdir(parents=True)
    (app / "_timbres" / "piano-ydp.zip").write_bytes(b"x")
    (pdir / "_instalar").mkdir(parents=True)
    (pdir / "_instalar" / "piano-upright.zip").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "AmpSim.exe"))
    found = {p.id: f for p, f in packs.pending()}
    assert set(found) == {"piano-ydp", "piano-upright"} and found["piano-ydp"].parent.name == "_timbres"
