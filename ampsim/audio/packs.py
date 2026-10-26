"""Timbres adicionais: pacotes de SoundFont baixados pela tela "Timbres adicionais" (ou pelo instalador).

Os arquivos ficam na Release "timbres-pianos-1" do GitHub do AmpSim (fora do histórico do git, que
não aceita arquivos grandes) e são instalados em %LOCALAPPDATA%\\AmpSim\\timbres\\<pacote>, uma pasta
onde o usuário sempre pode gravar (mesmo com o AmpSim instalado em Arquivos de Programas).
"""
import hashlib
import os
import shutil
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

RELEASE = "https://github.com/MarcelinoJunior/ampsim/releases/download/timbres-pianos-1/"
KEEP = (".sf2", ".sf3", ".txt", ".jpg")          # o que sai do pacote (timbre e licença)


@dataclass(frozen=True)
class Pack:
    id: str
    nome: str
    descricao: str
    licenca: str
    download_mb: int
    disco_mb: int
    url: str
    sha256: str
    arquivo: str            # o .sf2 dentro do pacote
    sound: str              # nome do timbre em instruments.SOUNDS


PACKS = (
    Pack("piano-upright", "Piano de Armário (Upright KW)",
         "Piano Kawai de armário gravado numa sala: som íntimo, bom para louvor acústico.",
         "CC0 (domínio público) · FreePats", 44, 56, RELEASE + "piano-upright.zip",
         "dc44e338cd4055243596dfec2d96d359daabeae30de4228ab8d1952249ece2f6",
         "UprightPianoKW-20220221.sf2", "Piano de Armário (Upright)"),
    Pack("piano-ydp", "Piano de Cauda YDP (Yamaha Disklavier)",
         "Piano de cauda Yamaha, leve e brilhante.",
         "CC BY 3.0 · FreePats / Zenph Studios", 52, 113, RELEASE + "piano-ydp.zip",
         "ee32495a5f923215e2dc3606dce6594c58bc18ae403501d59ed54bfd2ebcbe0e",
         "YDP-GrandPiano-20160804.sf2", "Piano de Cauda YDP"),
    Pack("piano-salamander", "Piano de Cauda Salamander (Yamaha C5)",
         "O melhor piano gratuito: 16 camadas de dinâmica. Grande: usa ~1,3 GB de disco e de memória.",
         "CC BY 3.0 · Alexander Holm / FreePats", 296, 1208, RELEASE + "piano-salamander.tar.xz",
         "15edb061d7ba60d58332f72dba8f8ce40988048cc703f935e6320f37d650e213",
         "SalamanderGrandPiano-V3+20200602.sf2", "Piano de Cauda Salamander"),
)
PACK_BY_ID = {p.id: p for p in PACKS}


class PackError(RuntimeError):
    pass


def packs_dir():
    base = os.environ.get("AMPSIM_PACKS_DIR")
    if base:
        return Path(base)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AmpSim" / "timbres"


def sf2_path(pack):
    """Caminho do .sf2 instalado, ou None."""
    p = packs_dir() / pack.id / pack.arquivo
    return p if p.exists() else None


def installed():
    return {p.id: sf2_path(p) for p in PACKS if sf2_path(p) is not None}


def _download(url, dest, sha256, progress, cancel):
    req = urllib.request.Request(url, headers={"User-Agent": "AmpSim"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel and cancel():
                raise PackError("Cancelado.")
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total, "baixando")
    if h.hexdigest() != sha256:
        raise PackError("O arquivo baixado não confere (download incompleto ou alterado). Tente de novo.")


def _check_sha(path, sha256):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != sha256:
        raise PackError("O arquivo do pacote não confere.")


def _extract(archive, target, progress):
    """Só arquivos de timbre/licença, sem pastas e sem nada fora de `target`."""
    target.mkdir(parents=True, exist_ok=True)
    name = str(archive).lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                base = os.path.basename(info.filename)
                if base and base.lower().endswith(KEEP):
                    with z.open(info) as src, open(target / base, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    if progress:
                        progress(0, 0, "instalando")
    elif name.endswith((".tar.xz", ".tar.gz", ".tar.bz2", ".tar")):
        with tarfile.open(archive) as t:
            for m in t:
                base = os.path.basename(m.name)
                if m.isfile() and base.lower().endswith(KEEP):
                    src = t.extractfile(m)
                    with src, open(target / base, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    if progress:
                        progress(0, 0, "instalando")
    else:
        raise PackError("Formato de pacote desconhecido.")


def install(pack, progress=None, cancel=None, source=None):
    """Baixa (ou usa `source`, um arquivo já baixado), confere o SHA-256 e instala. -> caminho do .sf2."""
    base = packs_dir()
    base.mkdir(parents=True, exist_ok=True)
    target = base / pack.id
    suffix = ".tar.xz" if pack.url.endswith(".tar.xz") else ".zip"
    part = base / f"{pack.id}.download{suffix}"
    try:
        free = shutil.disk_usage(base).free / 1e6
        need = (0 if source else pack.download_mb) + pack.disco_mb + 50
        if free < need:
            raise PackError(f"Espaço em disco insuficiente: precisa de ~{need} MB livres, há {free:.0f} MB.")
        if source:
            _check_sha(source, pack.sha256)
            archive = Path(source)
        else:
            _download(pack.url, part, pack.sha256, progress, cancel)
            archive = part
        tmp = base / f"{pack.id}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        _extract(archive, tmp, progress)
        if not (tmp / pack.arquivo).exists():
            shutil.rmtree(tmp, ignore_errors=True)
            raise PackError("O pacote não tem o timbre esperado.")
        shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
    except OSError as exc:
        raise PackError(f"Não foi possível instalar: {exc}") from exc
    finally:
        if part.exists():
            part.unlink()
    return target / pack.arquivo


def remove(pack):
    shutil.rmtree(packs_dir() / pack.id, ignore_errors=True)
