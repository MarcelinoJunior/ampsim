"""Baixa o plugin Neural Amp Modeler (MIT) e capturas .nam gratuitas (GPL-3.0) para third_party/.

Uso: .venv\\Scripts\\python tools\\baixar_extras.py

- Plugin: https://github.com/sdatkinson/NeuralAmpModelerPlugin (release oficial para Windows)
- Capturas: https://github.com/pelennor2170/NAM_models (coleção da comunidade)
"""
import io
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "third_party"
NAM_VERSION = "v0.7.13"
NAM_ZIP = (f"https://github.com/sdatkinson/NeuralAmpModelerPlugin/releases/download/"
           f"{NAM_VERSION}/NeuralAmpModeler-{NAM_VERSION}-win.zip")
MODELS_RAW = "https://raw.githubusercontent.com/pelennor2170/NAM_models/main/"

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
"""


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AmpSim"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


SYSTEM_VST3 = Path(r"C:\Program Files\Common Files\VST3")


def install_plugin():
    if (SYSTEM_VST3 / "NeuralAmpModeler.vst3").exists():
        print("Plugin NAM já instalado em", SYSTEM_VST3)
        return
    installer = DEST / "NeuralAmpModeler Installer.exe"
    if not installer.exists():
        print(f"Baixando Neural Amp Modeler {NAM_VERSION}…")
        with zipfile.ZipFile(io.BytesIO(fetch(NAM_ZIP))) as z:
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


def main():
    DEST.mkdir(exist_ok=True)
    (DEST / "LEIA-ME.txt").write_text(NOTICE, encoding="utf-8")
    install_plugin()
    install_captures()
    print("Pronto.")


if __name__ == "__main__":
    sys.exit(main())
