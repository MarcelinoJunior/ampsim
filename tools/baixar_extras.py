"""Baixa extras gratuitos para third_party/ (fora do git).

Uso: .venv\\Scripts\\python tools\\baixar_extras.py

Primeiro tenta a cópia mantida no GitHub do próprio AmpSim (release "extras-N", conferida por
SHA-256): assim a instalação não quebra se algum projeto mudar o lugar dos arquivos. Se essa
cópia falhar, baixa de cada fonte oficial abaixo. O pacote é montado por montar_pacote_extras.py.

- Plugin NAM: https://github.com/sdatkinson/NeuralAmpModelerPlugin (release oficial, MIT)
- Capturas: https://github.com/pelennor2170/NAM_models (coleção da comunidade, GPL-3.0)
- FluidSynth: https://github.com/FluidSynth/fluidsynth (motor de SoundFont, LGPL-2.1)
- GeneralUser GS: https://github.com/mrbumpy409/GeneralUser-GS (banco de timbres, licença livre)
"""
import hashlib
import io
import os
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = Path(os.environ.get("AMPSIM_EXTRAS_DEST") or ROOT / "third_party")
MIRROR = "https://github.com/MarcelinoJunior/ampsim/releases/download/extras-1/"
EXTRAS_ZIP = MIRROR + "ampsim-extras-1.zip"
EXTRAS_SHA256 = "ee5bc2cb0b97fc6a4baeaa7d1db259dfa0b6be492fc6ae5319dde4b5793e65c4"
NAM_MIRROR = MIRROR + "NeuralAmpModeler-v0.7.13-win.zip"
NAM_SHA256 = "8da37afde1f0797c773d6b8709da89bdda40c0e45f67cf3e4d87291e9b5e9da5"
NAM_VERSION = "v0.7.13"
NAM_ZIP = (f"https://github.com/sdatkinson/NeuralAmpModelerPlugin/releases/download/"
           f"{NAM_VERSION}/NeuralAmpModeler-{NAM_VERSION}-win.zip")
MODELS_RAW = "https://raw.githubusercontent.com/pelennor2170/NAM_models/main/"
FLUID_VERSION = "v2.6.1"
FLUID_ZIP = (f"https://github.com/FluidSynth/fluidsynth/releases/download/{FLUID_VERSION}/"
             f"fluidsynth-{FLUID_VERSION}-win10-x64-cpp11.zip")
FLUID_SHA256 = "fab7a2e4b85675b66970f97a39bbc239729c5e0f237198b5922a6a73cbc8677c"
SF2_URL = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2"
SF2_LICENSE = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/documentation/LICENSE.txt"

# arquivo no repositório -> nome curto usado no AmpSim
CAPTURES = {
    "Tim R Fender TwinVerb Norm Bright.nam": "Fender Twin Reverb (limpo).nam",
    "Phillipe P VOXAC15-TopBoost.nam": "Vox AC15 Top Boost.nam",
    "Tim R JCM2000 Crunch.nam": "Marshall JCM2000 Crunch.nam",
    "Tim R JCM90050WDualVerbChBG16.nam": "Marshall JCM900 Lead.nam",
    "Roman A LT_MESA_MARKIV_1.nam": "Mesa Boogie Mark IV.nam",
    "Helga B 5150 BlockLetter - Boosted.nam": "EVH 5150 Block Letter (boost).nam",
    "Jason Z Soldano - Super Lead Overdrive pedal nice crunchy rhythm tone.nam":
        "Soldano SLO pedal (crunch).nam",
    "Tom C Axe FX 2 Orange Rockerverb.nam": "Orange Rockerverb.nam",
    "Jason Z Tech21 dUg DP3X bass preamp pedal all dimed no shift.nam":
        "Baixo - Tech21 dUg DP3X (drive).nam",
}

NOTICE = """Arquivos de terceiros baixados por tools/baixar_extras.py (não versionados).

NeuralAmpModeler.vst3 — Steven Atkinson, licença MIT
  https://github.com/sdatkinson/NeuralAmpModelerPlugin

nam_models/*.nam — capturas da comunidade reunidas em pelennor2170/NAM_models, licença GPL-3.0
  https://github.com/pelennor2170/NAM_models
  Os nomes de marcas nos arquivos identificam o equipamento capturado; não há afiliação.

fluidsynth/ — FluidSynth (motor de SoundFont), licença LGPL-2.1
  https://github.com/FluidSynth/fluidsynth

soundfonts/GeneralUser-GS.sf2 — S. Christian Collins, GeneralUser GS License v2.0
  https://github.com/mrbumpy409/GeneralUser-GS  (licença em soundfonts/GeneralUser-GS-LICENSE.txt)
"""


def complete():
    """Já tem tudo o que o AmpSim usa (FluidSynth, banco de timbres, capturas)?"""
    fl = list((DEST / "fluidsynth").glob("*/bin/libfluidsynth-3.dll"))
    return bool(fl) and (DEST / "soundfonts" / "GeneralUser-GS.sf2").exists() and all(
        (DEST / "nam_models" / name).exists() for name in CAPTURES.values())


def install_from_mirror():
    """Pacote completo da cópia do AmpSim. -> True se instalou."""
    print("Baixando timbres e motores (cópia do AmpSim no GitHub, ~33 MB)…")
    try:
        data = fetch(EXTRAS_ZIP)
    except OSError as exc:
        print("  cópia do AmpSim indisponível:", exc)
        return False
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXTRAS_SHA256:
        print(f"  pacote com conteúdo diferente do esperado ({digest[:12]}…); descartado")
        return False
    dest = DEST.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if info.is_dir() or dest not in target.parents:
                continue                                    # nada fora de third_party/
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
    print("  ->", DEST)
    return True


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AmpSim"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


SYSTEM_VST3 = Path(r"C:\Program Files\Common Files\VST3")


def install_plugin():
    if (SYSTEM_VST3 / "NeuralAmpModeler.vst3").exists():
        print("Plugin NAM já instalado em", SYSTEM_VST3)
        return
    installer = DEST / "NeuralAmpModeler Installer.exe"
    if not installer.exists():
        print(f"Baixando Neural Amp Modeler {NAM_VERSION}…")
        data = None
        for url in (NAM_MIRROR, NAM_ZIP):                  # cópia do AmpSim, depois a oficial
            try:
                data = fetch(url)
            except OSError as exc:
                print("  indisponível:", url, exc)
                continue
            if hashlib.sha256(data).hexdigest() == NAM_SHA256:
                break
            print("  arquivo diferente do esperado:", url)
            data = None
        if data is None:
            print("  não foi possível baixar o plugin NAM agora (opcional)")
            return
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("installer.exe")), None)
            if name is None:
                raise SystemExit("O zip não contém o instalador: " + ", ".join(z.namelist()))
            with z.open(name) as src, open(installer, "wb") as dst:
                shutil.copyfileobj(src, dst)
    print("\n>>> Para instalar o plugin, execute:", installer)
    print("    (o instalador oficial coloca o NeuralAmpModeler.vst3 em", SYSTEM_VST3, ")\n")


def install_captures():
    out = DEST / "nam_models"
    out.mkdir(parents=True, exist_ok=True)
    for src, name in CAPTURES.items():
        path = out / name
        if path.exists():
            continue
        print("Baixando captura:", name)
        path.write_bytes(fetch(MODELS_RAW + urllib.parse.quote(src)))


def install_fluidsynth():
    out = DEST / "fluidsynth"
    if list(out.glob("*/bin/libfluidsynth-3.dll")):          # o zip oficial tem uma pasta da versão
        return
    print(f"Baixando FluidSynth {FLUID_VERSION}…")
    data = fetch(FLUID_ZIP)
    digest = hashlib.sha256(data).hexdigest()
    if digest != FLUID_SHA256:
        raise SystemExit(f"Hash do FluidSynth não confere ({digest}); download descartado.")
    shutil.rmtree(out, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(out)
    print("  ->", out)


def install_soundfont():
    out = DEST / "soundfonts"
    out.mkdir(parents=True, exist_ok=True)
    sf2 = out / "GeneralUser-GS.sf2"
    if not sf2.exists():
        print("Baixando GeneralUser GS (32 MB)…")
        tmp = sf2.with_suffix(".part")
        tmp.write_bytes(fetch(SF2_URL))
        tmp.replace(sf2)
    lic = out / "GeneralUser-GS-LICENSE.txt"
    if not lic.exists():
        lic.write_bytes(fetch(SF2_LICENSE))


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    if not complete() and not install_from_mirror():
        print("Usando as fontes oficiais de cada projeto…")
    # completa o que faltar (ou tudo, se a cópia do AmpSim falhou) pelas fontes oficiais
    install_captures()
    install_fluidsynth()
    install_soundfont()
    if not (DEST / "LEIA-ME.txt").exists():
        (DEST / "LEIA-ME.txt").write_text(NOTICE, encoding="utf-8")
    install_plugin()
    print("Pronto." if complete() else "Faltou algum arquivo: rode de novo com internet.")
    return 0 if complete() else 1


if __name__ == "__main__":
    sys.exit(main())
