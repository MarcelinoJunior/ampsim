"""Atualização pelo GitHub: ZIP (sem git) e clone git, sem rede (GitHub simulado)."""
import io
import json
import os
import shutil
import subprocess
import zipfile

import pytest

from ampsim import updater

SHA_OLD, SHA_NEW = "a" * 40, "b" * 40


def make_zip(files, sha=SHA_NEW, prefix="ampsim-main/"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(prefix + name, data)
        zf.comment = sha.encode()
    return buf.getvalue()


def fake_remote(sha=SHA_NEW):
    return lambda: (sha, "Correções no áudio", "2026-10-25T12:00:00Z")


@pytest.fixture()
def zip_install(tmp_path):
    root = tmp_path / "AmpSim"
    (root / "ampsim").mkdir(parents=True)
    (root / "ampsim" / "velho.py").write_text("x = 1", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "lib.txt").write_text("não mexer", encoding="utf-8")
    (root / "third_party").mkdir()
    (root / "third_party" / "timbres.sf2").write_text("bank", encoding="utf-8")
    (root / "requirements.txt").write_bytes(b"numpy\n")          # como vem no ZIP do GitHub (LF)
    (root / updater.VERSION_FILE).write_text(json.dumps({"commit": SHA_OLD}), encoding="utf-8")
    return root


def test_zip_install_detects_new_version(zip_install):
    info = updater.check(zip_install, fake_remote())
    assert info.mode == "zip" and info.local == SHA_OLD and info.available
    same = updater.check(zip_install, fake_remote(SHA_OLD))
    assert not same.available


def test_zip_update_copies_files_but_keeps_venv_and_sounds(zip_install):
    data = make_zip({"ampsim/velho.py": "x = 2", "ampsim/novo.py": "y = 1", "README.md": "oi",
                     ".venv/lib.txt": "INVADIDO", "third_party/timbres.sf2": "INVADIDO",
                     "versao.json": "{}", "requirements.txt": "numpy\n"})
    info = updater.check(zip_install, fake_remote())
    notes = updater.apply(info, zip_install, download=lambda: data)
    assert notes == []
    assert (zip_install / "ampsim" / "velho.py").read_text(encoding="utf-8") == "x = 2"
    assert (zip_install / "ampsim" / "novo.py").exists()
    assert (zip_install / ".venv" / "lib.txt").read_text(encoding="utf-8") == "não mexer"
    assert (zip_install / "third_party" / "timbres.sf2").read_text(encoding="utf-8") == "bank"
    assert updater.local_commit(zip_install) == SHA_NEW
    assert not updater.check(zip_install, fake_remote()).available


def test_zip_cannot_write_outside_install(zip_install, tmp_path):
    data = make_zip({"../fora.txt": "mal", "ampsim/../../fora2.txt": "mal", "ok.txt": "ok"})
    updater.extract_update(data, zip_install, SHA_NEW)
    assert not (tmp_path / "fora.txt").exists() and not (tmp_path / "fora2.txt").exists()
    assert (zip_install / "ok.txt").exists()


def test_zip_with_wrong_commit_is_rejected(zip_install):
    with pytest.raises(RuntimeError):
        updater.extract_update(make_zip({"a.txt": "1"}, sha="c" * 40), zip_install, SHA_NEW)


def test_new_requirements_are_reported_without_venv_python(zip_install):
    data = make_zip({"requirements.txt": "numpy\nnova-lib\n"})
    info = updater.check(zip_install, fake_remote())
    notes = updater.apply(info, zip_install, download=lambda: data)
    assert notes and "instalar.bat" in notes[0]


def test_private_repo_zip_install_explains_instead_of_failing(zip_install):
    import urllib.error

    def private():
        raise urllib.error.HTTPError(updater.API_URL, 404, "Not Found", {}, None)
    info = updater.check(zip_install, private)
    assert not info.available and "privado" in info.reason


def test_check_and_apply_respects_auto_off(zip_install):
    called = []
    info = updater.check_and_apply(zip_install, auto=False, remote=fake_remote(),
                                   download=lambda: called.append(1))
    assert info.available and not called and not info.notes


# ------------------------------------------------------------------ instalação por git
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git não instalado")


def _g(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture()
def git_repos(tmp_path):
    origin = tmp_path / "origin.git"
    _g(tmp_path, "init", "--bare", "-b", "main", str(origin))
    dev = tmp_path / "dev"
    _g(tmp_path, "clone", str(origin), str(dev))
    (dev / "a.txt").write_text("1", encoding="utf-8")
    _g(dev, "add", "-A")
    _g(dev, "commit", "-m", "primeira")
    _g(dev, "push", "origin", "HEAD:main")
    user = tmp_path / "user"
    _g(tmp_path, "clone", str(origin), str(user))
    return dev, user


@needs_git
def test_git_install_fast_forwards(git_repos):
    dev, user = git_repos
    (dev / "a.txt").write_text("2", encoding="utf-8")
    _g(dev, "commit", "-am", "segunda")
    _g(dev, "push", "origin", "HEAD:main")
    def no_api():
        raise AssertionError("instalação git não usa a API pública (repositório pode ser privado)")
    info = updater.check(user, no_api)
    assert info.mode == "git" and info.available and info.message == "segunda"
    updater.apply(info, user)
    assert (user / "a.txt").read_text(encoding="utf-8") == "2"
    assert not updater.check(user, None).available


@needs_git
def test_git_install_with_local_changes_is_left_alone(git_repos):
    dev, user = git_repos
    (dev / "a.txt").write_text("2", encoding="utf-8")
    _g(dev, "commit", "-am", "segunda")
    _g(dev, "push", "origin", "HEAD:main")
    (user / "a.txt").write_text("mudança minha", encoding="utf-8")
    info = updater.check(user, fake_remote())
    assert not info.available and "mudanças locais" in info.reason
    assert (user / "a.txt").read_text(encoding="utf-8") == "mudança minha"


# ------------------------------------------------------------------ interface
@pytest.fixture()
def win(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ampsim import storage
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(storage, "PRESET_DIR", tmp_path / "presets")
    from ampsim.audio.engine import AudioEngine
    from ampsim.ui.main_window import MainWindow
    w = MainWindow(AudioEngine())
    yield w
    w.timer.stop()
    w.hotplug_timer.stop()
    app.processEvents()


def test_installed_update_shows_restart_button(win):
    info = updater.UpdateInfo(remote=SHA_NEW, message="Correções", available=True, notes=["ok"])
    win._update_done(info, "", False)
    assert win.topbar.update_btn.isVisibleTo(win) and "instalada" in win.dock.version_label.text()


def test_auto_update_runs_in_background_thread(win, monkeypatch):
    calls = []

    def fake(auto=True):
        calls.append(auto)
        return updater.UpdateInfo(remote=SHA_NEW, available=True, notes=["ok"])
    monkeypatch.setattr(updater, "check_and_apply", fake)
    win.check_updates()
    win._update_thread.join(5)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert calls == [win.auto_update] and win.topbar.update_btn.isVisibleTo(win)


def test_restart_reopens_the_app(win, monkeypatch):
    import ampsim.ui.main_window as mw
    started, quit_called = [], []
    monkeypatch.setattr(mw.subprocess, "Popen", lambda cmd, **k: started.append((cmd, k["cwd"])))
    monkeypatch.setattr(mw.QApplication, "quit", staticmethod(lambda: quit_called.append(1)))
    win.restart()
    assert started and started[0][0][-2:] == ["-m", "ampsim"] and quit_called


def test_auto_update_setting_is_saved(win):
    win.dock.auto_update.setChecked(False)
    win.save_state()
    from ampsim import storage
    assert storage.load_state()["ui"]["auto_update"] is False


def test_version_number_parsing_and_label():
    from ampsim.version import parse_version
    assert parse_version('X = 1\nVERSION = "1.4.2"\nCHANNEL = ""') == "1.4.2"
    assert parse_version("nada aqui") == ""
    info = updater.UpdateInfo(remote=SHA_NEW, version="1.4.2")
    assert info.label() == "1.4.2 (bbbbbbb)"
    assert updater.UpdateInfo(remote=SHA_NEW).label() == "bbbbbbb"


@needs_git
def test_update_reports_the_new_version_number(git_repos):
    dev, user = git_repos
    (dev / "ampsim").mkdir()
    (dev / "ampsim" / "version.py").write_text('VERSION = "2.0.0"\n', encoding="utf-8")
    _g(dev, "add", "-A")
    _g(dev, "commit", "-m", "versão 2")
    _g(dev, "push", "origin", "HEAD:main")
    info = updater.check_and_apply(user, auto=False, remote=None)
    assert info.available and info.version == "2.0.0"


def test_exe_mode_finds_and_downloads_newer_installer(monkeypatch, tmp_path):
    """Instalado pelo AmpSim-Setup.exe: acha o instalador mais novo nas Releases, baixa e confere."""
    import hashlib
    import json
    import sys
    from ampsim import updater
    payload = b"MZ instalador de mentira"
    releases = [
        {"name": "AmpSim 0.9.21 (estável)", "tag_name": "v0.9.21", "assets": []},
        {"name": "AmpSim 1.0.1 beta", "tag_name": "v1.0.1-beta", "published_at": "2026-11-01",
         "assets": [{"name": "AmpSim-Setup-1.0.1-beta.exe", "size": len(payload),
                     "browser_download_url": "https://exemplo/AmpSim-Setup-1.0.1-beta.exe",
                     "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}]},
        {"name": "rascunho", "draft": True,
         "assets": [{"name": "AmpSim-Setup-9.9.9.exe", "browser_download_url": "x"}]},
    ]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_http_get", lambda url, *a, **k: json.dumps(releases).encode())
    monkeypatch.setattr(updater, "local_version", lambda: "1.0.0-beta")
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    updater.PENDING["installer"] = None
    info = updater.check(tmp_path)
    assert info.mode == "exe" and info.available and info.version == "1.0.1-beta"
    notes = updater.apply(info, tmp_path, download=lambda: payload)
    assert notes and updater.PENDING["installer"].endswith("AmpSim-Setup-1.0.1-beta.exe")
    cmd, _ = updater.restart_command(tmp_path)
    assert cmd[0] == updater.PENDING["installer"] and "/SILENT" in cmd
    import pytest
    with pytest.raises(RuntimeError):                               # arquivo alterado: recusa
        updater.apply(info, tmp_path, download=lambda: b"outro")
    monkeypatch.setattr(updater, "local_version", lambda: "1.0.1")  # já está na estável: nada
    assert not updater.check(tmp_path).available
    updater.PENDING["installer"] = None


def test_version_order():
    from ampsim.updater import version_key as k
    assert k("1.0.0") > k("1.0.0-beta") > k("0.9.21") and k("1.0.10") > k("1.0.9")
