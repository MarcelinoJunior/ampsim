"""Instalador dos extras (timbres e motores): cópia do AmpSim primeiro, fontes oficiais se falhar."""
import hashlib
import importlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


@pytest.fixture()
def bx(tmp_path, monkeypatch):
    monkeypatch.setenv("AMPSIM_EXTRAS_DEST", str(tmp_path / "third_party"))
    import baixar_extras
    mod = importlib.reload(baixar_extras)
    monkeypatch.setattr(mod, "install_plugin", lambda: None)     # o plugin tem teste próprio
    return mod


def fake_package(mod, evil=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fluidsynth/fluidsynth-v9/bin/libfluidsynth-3.dll", b"dll")
        z.writestr("soundfonts/GeneralUser-GS.sf2", b"sf2")
        z.writestr("soundfonts/GeneralUser-GS-LICENSE.txt", b"licenca")
        for name in mod.CAPTURES.values():
            z.writestr(f"nam_models/{name}", b"nam")
        z.writestr("LEIA-ME.txt", b"leia")
        if evil:
            z.writestr("../fora.txt", b"mal")
    return buf.getvalue()


def test_installs_from_ampsim_copy(bx, monkeypatch, tmp_path):
    data = fake_package(bx, evil=True)
    monkeypatch.setattr(bx, "EXTRAS_SHA256", hashlib.sha256(data).hexdigest())
    asked = []
    monkeypatch.setattr(bx, "fetch", lambda url: asked.append(url) or data)
    assert bx.main() == 0
    assert asked == [bx.EXTRAS_ZIP]                                 # nada das fontes oficiais
    assert bx.complete() and not (tmp_path / "fora.txt").exists()   # nada fora de third_party
    asked.clear()
    assert bx.main() == 0 and asked == []                           # já completo: não baixa


def test_falls_back_to_official_sources(bx, monkeypatch):
    calls = []

    def fetch(url):
        calls.append(url)
        if url == bx.EXTRAS_ZIP:
            raise OSError("404")                                    # cópia do AmpSim fora do ar
        if url == bx.FLUID_ZIP:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("fluidsynth-v2/bin/libfluidsynth-3.dll", b"dll")
            return buf.getvalue()
        return b"x"
    monkeypatch.setattr(bx, "fetch", fetch)
    monkeypatch.setattr(bx, "FLUID_SHA256", hashlib.sha256(fetch(bx.FLUID_ZIP)).hexdigest())
    calls.clear()
    assert bx.main() == 0
    assert calls[0] == bx.EXTRAS_ZIP and bx.SF2_URL in calls and bx.FLUID_ZIP in calls
    assert bx.complete()


def test_tampered_copy_is_rejected(bx, monkeypatch):
    data = fake_package(bx)
    monkeypatch.setattr(bx, "fetch", lambda url: data)
    assert not bx.install_from_mirror()                             # SHA-256 não confere
    assert not bx.complete()


def test_real_package_hash_is_pinned():
    import baixar_extras
    assert len(baixar_extras.EXTRAS_SHA256) == 64 and baixar_extras.EXTRAS_ZIP.startswith(
        "https://github.com/MarcelinoJunior/ampsim/releases/download/")
