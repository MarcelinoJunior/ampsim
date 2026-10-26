"""Monta o instalador do AmpSim: PyInstaller (pasta AmpSim com o .exe) + Inno Setup (AmpSim-Setup-<versão>.exe).

    python tools/instalador/montar.py                 (monta em %TEMP%\\ampsim-build)
    python tools/instalador/montar.py --testar        (monta, instala em silêncio numa pasta de teste,
                                                        confere o autoteste e o piano baixado, desinstala)
    python tools/instalador/montar.py --so-inno       (reaproveita a pasta do PyInstaller já montada)

Precisa: pip install pyinstaller e o Inno Setup 6 (ISCC.exe).
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))


def version():
    from ampsim.version import CHANNEL, VERSION
    return VERSION + (f"-{CHANNEL}" if CHANNEL else "")


def iscc():
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        for sub in ("Programs/Inno Setup 6/ISCC.exe", "Inno Setup 6/ISCC.exe"):
            p = Path(base) / sub
            if p.exists():
                return p
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    raise SystemExit("Inno Setup 6 (ISCC.exe) não encontrado: instale de https://jrsoftware.org/isdl.php")


def build(out, skip_pyinstaller=False):
    dist = out / "dist"
    if not (skip_pyinstaller and (dist / "AmpSim" / "AmpSim.exe").exists()):
        shutil.rmtree(dist / "AmpSim", ignore_errors=True)
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(dist),
                        "--workpath", str(out / "work"), str(HERE / "ampsim.spec")], check=True)
        shutil.rmtree(out / "work", ignore_errors=True)              # 50 MB que não servem mais
    iss = out / "ampsim.iss"
    iss.write_text((HERE / "ampsim.iss").read_text(encoding="utf-8"), encoding="utf-8-sig")   # Inno: UTF-8 com BOM
    ver = version()
    subprocess.run([str(iscc()), f"/DAmpVer={ver}", f"/DAmpDist={dist / 'AmpSim'}", f"/DAmpRaiz={ROOT}",
                    f"/DAmpSaida={out}", str(iss)], check=True)
    setup = out / f"AmpSim-Setup-{ver}.exe"
    print(f"Instalador: {setup} ({setup.stat().st_size / 1e6:.0f} MB)")
    return setup


def test_install(setup, out):
    """Instala em silêncio (baixando o piano Upright), confere e desinstala."""
    target = out / "teste-instalacao"
    shutil.rmtree(target, ignore_errors=True)
    t0 = time.time()
    r = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={target}",
                        "/TASKS=pianos\\upright", "/NOABRIR=1", f"/LOG={out / 'instalacao.log'}"], timeout=1800)
    print(f"instalação: código {r.returncode} em {time.time() - t0:.0f} s")
    ok = r.returncode == 0
    report = target / "instalacao.txt"
    text = report.read_text(encoding="utf-8") if report.exists() else "(sem autoteste)"
    print("autoteste no fim da instalação:\n" + text)
    ok = ok and "RESULTADO: OK" in text
    pack = target / "_timbres" / "piano-upright.zip"
    if pack.exists():
        sha = hashlib.sha256(pack.read_bytes()).hexdigest()
        print("piano baixado pelo instalador:", pack.name, "ok" if sha.startswith("dc44e338") else "SHA ERRADO")
        ok = ok and sha.startswith("dc44e338")
    else:
        print("piano NÃO foi baixado")
        ok = False
    unins = target / "unins000.exe"
    if unins.exists():
        # o desinstalador do Inno roda uma cópia de si mesmo e volta na hora: espera ela terminar
        subprocess.run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=600)
        end = time.time() + 120
        while (target / "AmpSim.exe").exists() and time.time() < end:
            time.sleep(1)
    print("desinstalado:", not (target / "AmpSim.exe").exists())
    shutil.rmtree(target, ignore_errors=True)
    print("TESTE DO INSTALADOR:", "OK" if ok else "FALHOU")
    return ok


def main():
    out = Path(os.environ.get("AMPSIM_BUILD") or Path(tempfile.gettempdir()) / "ampsim-build")
    out.mkdir(parents=True, exist_ok=True)
    setup = build(out, skip_pyinstaller="--so-inno" in sys.argv)
    if "--testar" in sys.argv:
        return 0 if test_install(setup, out) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
