"""Downloads: timbres adicionais (pacotes de SoundFont) e plugins VST3 gratuitos, baixados pela tela
"Downloads: timbres e plugins" (os pianos também pelo instalador).

Pianos: os arquivos ficam na Release "timbres-pianos-1" do GitHub do AmpSim (fora do histórico do git,
que não aceita arquivos grandes) e são instalados em %LOCALAPPDATA%\\AmpSim\\timbres\\<pacote>, uma pasta
onde o usuário sempre pode gravar (mesmo com o AmpSim instalado em Arquivos de Programas).

Plugins: baixados da release oficial de quem fez o plugin (não ficam na release do AmpSim), conferidos
pelo tamanho e pelo SHA-256; só as pastas .vst3 esperadas saem do zip, para a pasta de VST3 do usuário
(%LOCALAPPDATA%\\Programs\\Common\\VST3, gravável sem administrador e lida pelo AmpSim e pelos DAWs).
"""
import hashlib
import http.client
import os
import shutil
import tarfile
import urllib.error
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


def pending_dirs():
    """Onde o instalador deixa os pacotes que baixou: <pasta do AmpSim>/_timbres (programa instalado)
    ou <timbres>/_instalar."""
    import sys
    dirs = [packs_dir() / "_instalar"]
    if getattr(sys, "frozen", False):
        dirs.insert(0, Path(sys.executable).parent / "_timbres")
    return dirs


def pending():
    """Pacotes baixados pelo instalador e ainda não instalados: [(pacote, arquivo)]."""
    out = []
    for d in pending_dirs():
        for p in PACKS:
            f = d / Path(p.url).name
            if f.exists() and p.id not in {q.id for q, _ in out}:
                out.append((p, f))
    return out


def installed():
    return {p.id: sf2_path(p) for p in PACKS if sf2_path(p) is not None}


NET_ERROR = "Sem conexão com a internet (ou o site não respondeu). Confira a conexão e tente de novo."


def _download(url, dest, sha256, progress, cancel):
    try:
        _fetch(url, dest, sha256, progress, cancel)
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
        raise PackError(NET_ERROR) from exc


def _fetch(url, dest, sha256, progress, cancel):
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


# ------------------------------------------------------------------ plugins VST3
@dataclass(frozen=True)
class PluginPack:
    id: str
    nome: str
    descricao: str
    licenca: str            # "licença · autor", mostrado como nos pianos
    download_mb: int
    disco_mb: int
    url: str
    sha256: str
    tamanho: int            # bytes do download (conferido junto com o SHA-256)
    bundles: tuple          # pastas .vst3 que saem do zip (CLAP, LV2, VST2 e .exe ficam de fora)
    site: str = ""


PLUGIN_PACKS = (
    PluginPack("dragonfly-reverb", "Dragonfly Reverb 3.2.10",
               "Reverbs de sala (Room), salão (Hall), placa (Plate) e primeiras reflexões (Early "
               "Reflections): ótimos para voz e teclado. Escolha no slot “Plugin” de uma camada ou do Master.",
               "GPL-3.0 · Michael Willis e colaboradores", 22, 14,
               "https://github.com/michaelwillis/dragonfly-reverb/releases/download/3.2.10/"
               "dragonfly-reverb-3.2.10-win64.zip",
               "ca5f35f9dcd9a33f06490d3c92f04061a1a798cb81257d5ca5851bdda0824c66", 22447365,
               ("DragonflyRoomReverb.vst3", "DragonflyHallReverb.vst3", "DragonflyPlateReverb.vst3",
                "DragonflyEarlyReflections.vst3"),
               "https://michaelwillis.github.io/dragonfly-reverb/"),
)
PLUGIN_PACK_BY_ID = {p.id: p for p in PLUGIN_PACKS}


def _vst3_dirs():
    """(pasta de VST3 do usuário, pasta do sistema)."""
    from .vst import SYSTEM_VST3_DIR, user_vst3_dir
    return Path(user_vst3_dir()), Path(SYSTEM_VST3_DIR)


def _bundle_ok(path):
    """Pasta .vst3 com o binário de 64 bits dentro."""
    inner = Path(path) / "Contents" / "x86_64-win"
    try:
        return inner.is_dir() and any(f.suffix.lower() == ".vst3" for f in inner.iterdir())
    except OSError:
        return False


def plugin_paths(pack):
    """Caminho de cada plugin do pacote instalado (pasta do usuário ou do sistema), sem os que faltam."""
    out = []
    for b in pack.bundles:
        for d in _vst3_dirs():
            if _bundle_ok(d / b):
                out.append(d / b)
                break
    return out


def plugin_installed(pack):
    return len(plugin_paths(pack)) == len(pack.bundles)


def plugin_removable(pack):
    """Instalado pela tela de downloads (pasta do usuário): dá para remover por aqui."""
    user = _vst3_dirs()[0]
    return any((user / b).exists() for b in pack.bundles)


def _check_file(path, sha256, size):
    if Path(path).stat().st_size != size:
        raise PackError("O arquivo do plugin não tem o tamanho esperado (download incompleto ou alterado).")
    _check_sha(path, sha256)


def _extract_bundles(archive, tmp, bundles, progress):
    """Só arquivos de dentro das pastas .vst3 esperadas, e nada fora de `tmp`."""
    want = {b.lower(): b for b in bundles}
    root = str(tmp.resolve()) + os.sep
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = info.filename.replace("\\", "/").split("/")
            k = next((i for i, part in enumerate(parts) if part.lower() in want), None)
            if k is None or k + 1 >= len(parts):
                continue
            rel = parts[k + 1:]
            if any(p in ("", ".", "..") or ":" in p for p in rel):
                continue
            dest = tmp.joinpath(want[parts[k].lower()], *rel)
            if not str(dest.resolve()).startswith(root):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            if progress:
                progress(0, 0, "instalando")


def install_plugin_pack(pack, progress=None, cancel=None, source=None):
    """Baixa (ou usa `source`, um arquivo já baixado), confere tamanho e SHA-256 e instala as pastas .vst3
    na pasta de VST3 do usuário. -> caminhos instalados."""
    base = packs_dir()
    target = _vst3_dirs()[0]
    part = base / f"{pack.id}.download.zip"
    tmp = target / f".ampsim-{pack.id}.tmp"
    try:
        base.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(target).free / 1e6
        need = (0 if source else pack.download_mb) + pack.disco_mb + 20
        if free < need:
            raise PackError(f"Espaço em disco insuficiente: precisa de ~{need} MB livres, há {free:.0f} MB.")
        if source:
            _check_file(source, pack.sha256, pack.tamanho)
            archive = Path(source)
        else:
            _download(pack.url, part, pack.sha256, progress, cancel)
            _check_file(part, pack.sha256, pack.tamanho)
            archive = part
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        _extract_bundles(archive, tmp, pack.bundles, progress)
        missing = [b for b in pack.bundles if not _bundle_ok(tmp / b)]
        if missing:
            raise PackError("O pacote não tem os plugins esperados: " + ", ".join(missing))
        done = []
        for b in pack.bundles:
            dest = target / b
            try:
                if dest.exists():
                    shutil.rmtree(dest)
            except OSError as exc:
                raise PackError(f"“{b}” está em uso: tire o plugin dos slots (ou feche o AmpSim) e tente "
                                "de novo.") from exc
            (tmp / b).rename(dest)
            done.append(dest)
    except OSError as exc:
        raise PackError(f"Não foi possível instalar: {exc}") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if part.exists():
            part.unlink()
    return done


def remove_plugin_pack(pack):
    """Apaga só as pastas que a tela de downloads instalou (pasta de VST3 do usuário)."""
    user = _vst3_dirs()[0]
    for b in pack.bundles:
        p = user / b
        if p.exists():
            try:
                shutil.rmtree(p)
            except OSError as exc:
                raise PackError(f"Não deu para remover “{b}”: o plugin está em uso (tire dos slots ou "
                                "feche o AmpSim e tente de novo).") from exc
