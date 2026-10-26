"""Atualização automática a partir do GitHub (MarcelinoJunior/ampsim).

Três jeitos de instalação:
- instalado pelo AmpSim-Setup.exe (programa "congelado"): procura nas Releases do GitHub um
  instalador mais novo, baixa, confere o SHA-256 e, no "Reiniciar", roda o instalador em silêncio
  (ele fecha o AmpSim, atualiza e abre de novo);
- clonado com git: `git fetch` + `git merge --ff-only`, com o login do GitHub que o git já usa
  (funciona com o repositório privado); nunca sobrescreve mudanças locais: se a cópia tiver
  commits que o GitHub não tem, não mexe em nada;
- baixado em ZIP: baixa o ZIP do branch, confere o commit (o GitHub grava o id no comentário do
  ZIP) e copia os arquivos por cima, sem tocar em .venv, third_party (timbres) e .git. O commit
  instalado fica em versao.json.

Se o requirements.txt mudar, as bibliotecas são atualizadas com o pip do .venv. Tudo roda numa
thread (a interface só recebe o resultado) e qualquer falha de rede apenas adia a atualização.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = "MarcelinoJunior/ampsim"
BRANCH = "main"
API_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = "versao.json"
KEEP = {".venv", "third_party", ".git", VERSION_FILE}      # nunca são substituídos
MAX_ZIP = 60 * 1024 * 1024
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
SETUP_PREFIX = "AmpSim-Setup-"
MAX_SETUP = 1024 * 1024 * 1024
PENDING = {"installer": None}         # instalador baixado esperando o "Reiniciar para atualizar"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # git/pip sem abrir console


@dataclass
class UpdateInfo:
    mode: str = "zip"                 # "git", "zip" ou "exe" (instalado pelo AmpSim-Setup.exe)
    local: str = ""                   # commit instalado ("" = desconhecido)
    remote: str = ""                  # commit mais novo no GitHub
    message: str = ""
    date: str = ""
    available: bool = False
    reason: str = ""                  # por que não dá para atualizar (ex.: mudanças locais)
    notes: list = field(default_factory=list)
    version: str = ""                 # número da versão nova (ampsim/version.py no GitHub)
    asset: dict = None                # modo exe: instalador da Release (url, tamanho, sha256)

    def label(self):
        return f"{self.version} ({self.remote[:7]})" if self.version else self.remote[:7]


def _run(args, root, timeout=60):
    return subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW)


def _git(root, *args, timeout=60):
    r = _run(["git", *args], root, timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"git {args[0]} falhou")
    return r.stdout.strip()


def install_mode(root=ROOT):
    if getattr(sys, "frozen", False):
        return "exe"
    return "git" if (Path(root) / ".git").exists() and shutil.which("git") else "zip"


def version_key(v):
    """"1.0.0-beta" -> (1, 0, 0, 0); "1.0.0" -> (1, 0, 0, 1): a estável vem depois da beta."""
    import re
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(.*)", v or "")
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1)


def local_version():
    from .version import CHANNEL, VERSION
    return VERSION + (f"-{CHANNEL}" if CHANNEL else "")


def latest_installer(fetch=None):
    """O AmpSim-Setup-<versão>.exe mais novo das Releases (ou None)."""
    data = json.loads((fetch or (lambda: _http_get(RELEASES_URL, 8, 4_000_000)))())
    best = None
    for rel in data if isinstance(data, list) else []:
        if rel.get("draft"):
            continue
        for a in rel.get("assets", []):
            name = a.get("name", "")
            if name.startswith(SETUP_PREFIX) and name.endswith(".exe"):
                ver = name[len(SETUP_PREFIX):-4]
                if best is None or version_key(ver) > version_key(best["version"]):
                    digest = a.get("digest") or ""
                    best = dict(version=ver, url=a.get("browser_download_url", ""), size=a.get("size", 0),
                                sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
                                name=rel.get("name") or rel.get("tag_name", ""), date=rel.get("published_at", ""))
    return best


def _http_get(url, timeout, limit=None):
    req = urllib.request.Request(url, headers={"User-Agent": "AmpSim-updater",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 - URL fixa do GitHub
        data = r.read(limit + 1 if limit else -1)
    if limit and len(data) > limit:
        raise RuntimeError("download grande demais")
    return data


def remote_commit(timeout=6):
    """(sha, mensagem, data) do último commit do branch no GitHub."""
    d = json.loads(_http_get(API_URL, timeout))
    c = d.get("commit", {})
    return d["sha"], (c.get("message") or "").split("\n")[0][:120], (c.get("committer") or {}).get("date", "")


def local_commit(root=ROOT):
    root = Path(root)
    if install_mode(root) == "git":
        try:
            return _git(root, "rev-parse", "HEAD")
        except (RuntimeError, OSError, subprocess.SubprocessError):
            return ""
    try:
        return json.loads((root / VERSION_FILE).read_text(encoding="utf-8")).get("commit", "")
    except (OSError, ValueError):
        return ""


PRIVATE_MSG = ("O repositório do AmpSim ainda é privado: a atualização automática de cópias baixadas "
               "em ZIP funciona quando ele ficar público. Instalações feitas com git clone (com acesso "
               "ao repositório) já se atualizam.")


def check(root=ROOT, remote=remote_commit):
    """Compara o instalado com o GitHub. Não altera nada."""
    root = Path(root)
    info = UpdateInfo(mode=install_mode(root), local=local_commit(root))
    if info.mode == "exe":
        info.local = local_version()
        best = latest_installer()
        if best and version_key(best["version"]) > version_key(info.local):
            info.available = True
            info.remote = info.version = best["version"]
            info.message, info.date, info.asset = best["name"], best["date"], best
        return info
    if info.mode == "git":
        try:
            _git(root, "fetch", "--quiet", "origin", BRANCH, timeout=60)
            info.remote = _git(root, "rev-parse", f"origin/{BRANCH}")
            info.message, _, info.date = _git(root, "log", "-1", "--format=%s%x00%cI",
                                              f"origin/{BRANCH}").partition("\x00")
            behind = int(_git(root, "rev-list", "--count", f"HEAD..origin/{BRANCH}") or 0)
            ahead = int(_git(root, "rev-list", "--count", f"origin/{BRANCH}..HEAD") or 0)
            dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=no"))
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            info.reason = f"git: {exc}"
            return info
        if behind == 0:
            return info
        if ahead or dirty:
            info.reason = "esta cópia tem mudanças locais; atualize pelo git"
            return info
        info.available = True
        return info
    try:
        info.remote, info.message, info.date = remote()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:                  # repositório privado (ou renomeado)
            info.reason = PRIVATE_MSG
            return info
        raise
    info.available = bool(info.remote) and info.local != info.remote
    return info


def _requirements_hash(root):
    try:
        return hashlib.sha256((Path(root) / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""


def extract_update(data, root, expected_sha=""):
    """Copia o ZIP do GitHub por cima da instalação (sem .venv, third_party, .git). -> commit"""
    root = Path(root).resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        sha = zf.comment.decode("ascii", "ignore").strip()
        if expected_sha and sha and sha != expected_sha:
            raise RuntimeError("o ZIP baixado não é a versão esperada")
        names = zf.namelist()
        prefix = names[0].split("/")[0] + "/" if names and "/" in names[0] else ""
        for info in zf.infolist():
            if not info.filename.startswith(prefix) or info.is_dir():
                continue
            rel = info.filename[len(prefix):]
            parts = Path(rel).parts
            if not rel or parts[0] in KEEP or ".." in parts or Path(rel).is_absolute():
                continue
            dest = (root / rel).resolve()
            if root not in dest.parents:
                continue                                # nada fora da pasta do AmpSim
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".novo")
            tmp.write_bytes(zf.read(info))
            os.replace(tmp, dest)
    return sha or expected_sha


def apply(info, root=ROOT, download=None):
    """Baixa e instala a versão `info.remote`. -> lista de avisos (vazia = tudo certo)."""
    root = Path(root)
    notes = []
    if info.mode == "exe":
        return [_download_installer(info.asset, download)]
    req_before = _requirements_hash(root)
    if info.mode == "git":
        _git(root, "merge", "--ff-only", f"origin/{BRANCH}", timeout=120)
    else:
        data = (download or (lambda: _http_get(ZIP_URL, 60, MAX_ZIP)))()
        sha = extract_update(data, root, info.remote)
        (root / VERSION_FILE).write_text(json.dumps({"commit": sha, "data": info.date}, indent=2),
                                         encoding="utf-8")
    if _requirements_hash(root) != req_before:
        py = root / ".venv" / "Scripts" / "python.exe"
        if py.exists():
            r = _run([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"], root, timeout=900)
            if r.returncode != 0:
                notes.append("não foi possível atualizar as bibliotecas; rode instalar.bat")
        else:
            notes.append("bibliotecas novas: rode instalar.bat")
    return notes


def _download_installer(asset, download=None):
    """Baixa o instalador novo para a pasta temporária e confere o SHA-256. -> aviso para a tela."""
    import tempfile
    data = (download or (lambda: _http_get(asset["url"], 120, MAX_SETUP)))()
    if asset.get("sha256") and hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise RuntimeError("o instalador baixado não confere")
    path = Path(tempfile.gettempdir()) / f"{SETUP_PREFIX}{asset['version']}.exe"
    path.write_bytes(data)
    PENDING["installer"] = str(path)
    return "o instalador termina a atualização ao reiniciar"


RAW_VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/ampsim/version.py"


def remote_version(info, root=ROOT):
    """Número da versão que está no GitHub (só para mostrar; falha = vazio)."""
    from .version import parse_version

    if info.mode == "exe":
        return info.version
    try:
        if info.mode == "git":
            src = _git(Path(root), "show", f"origin/{BRANCH}:ampsim/version.py")
        else:
            src = _http_get(RAW_VERSION_URL, 6, 20000).decode("utf-8", "replace")
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        return ""
    return parse_version(src)


def check_and_apply(root=ROOT, auto=True, remote=remote_commit, download=None):
    """Usado pela interface (numa thread). -> UpdateInfo (notes preenchido se instalou)."""
    info = check(root, remote)
    if info.available:
        info.version = remote_version(info, root)
    if info.available and auto:
        info.notes = apply(info, root, download) or ["ok"]
    return info


def restart_command(root=ROOT):
    """Comando para abrir o AmpSim de novo depois de atualizar (exe: roda o instalador em silêncio,
    que fecha, atualiza e abre o AmpSim de novo)."""
    if PENDING["installer"]:
        return [PENDING["installer"], "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], str(root)
    if getattr(sys, "frozen", False):
        return [sys.executable], str(Path(sys.executable).parent)
    exe = sys.executable
    pyw = Path(exe).with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else exe), "-m", "ampsim"], str(root)
