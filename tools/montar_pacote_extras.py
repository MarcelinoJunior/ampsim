"""Monta o pacote de extras (timbres e motores) publicado no GitHub do AmpSim.

Uso (depois de rodar tools/baixar_extras.py uma vez pelas fontes oficiais):
    .venv\\Scripts\\python tools\\montar_pacote_extras.py 1

Gera dist/ampsim-extras-<n>.zip com a mesma estrutura de third_party/ (FluidSynth, GeneralUser GS,
capturas NAM) + licenças + LEIA-ME, e mostra o SHA-256 para colocar em baixar_extras.py.
Publique como asset do release "extras-<n>" junto com o código-fonte do FluidSynth (LGPL).
"""
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "third_party"
LIC = Path(__file__).resolve().parent / "extras_licencas"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from baixar_extras import CAPTURES, FLUID_VERSION, MODELS_RAW  # noqa: E402

README = """AmpSim — pacote de extras {n} (timbres e motores gratuitos)
=====================================================================

Cópia mantida no GitHub do AmpSim para a instalação não depender de links de terceiros.
Os arquivos são os originais, sem modificação. Cada um mantém a sua licença (pasta licencas/).

fluidsynth/   FluidSynth {fluid} (binários oficiais para Windows x64), motor de SoundFont.
              Licença: GNU LGPL-2.1 (licencas/fluidsynth-LGPL-2.1.txt). Inclui as DLLs:
                - libsndfile (sndfile.dll): GNU LGPL-2.1 (licencas/libsndfile-LGPL-2.1.txt)
                - SDL3 (SDL3.dll): zlib (licencas/SDL3-zlib.txt)
              Código-fonte: anexado ao mesmo release do AmpSim (fluidsynth-{fluid_n}.tar.gz) e em
                https://github.com/FluidSynth/fluidsynth/releases/tag/{fluid}
                https://github.com/libsndfile/libsndfile  ·  https://github.com/libsdl-org/SDL
              O AmpSim carrega a DLL sem alterá-la; você pode trocá-la por outra versão compatível.

soundfonts/   GeneralUser GS (S. Christian Collins). Uso livre, inclusive comercial
              (licencas/GeneralUser-GS-LICENSE.txt). Site: https://www.schristiancollins.com
              (o autor prefere cópias locais a links diretos para os arquivos dele).

nam_models/   Capturas de amplificadores da coleção da comunidade pelennor2170/NAM_models,
              licença GNU GPL-3.0 (licencas/NAM_models-GPL-3.0.txt).
              https://github.com/pelennor2170/NAM_models
              Nomes originais (com o autor de cada captura):
{captures}
              As marcas nos nomes identificam o equipamento capturado; não há afiliação.
"""


def build(n):
    files = []
    for sub in ("fluidsynth", "soundfonts", "nam_models"):
        base = SRC / sub
        if not base.is_dir():
            raise SystemExit(f"Falta third_party/{sub}: rode tools/baixar_extras.py antes")
        files += [p for p in sorted(base.rglob("*")) if p.is_file()]
    caps = "\n".join(f"                {short}  <-  {orig}" for orig, short in CAPTURES.items())
    text = README.format(n=n, fluid=FLUID_VERSION, fluid_n=FLUID_VERSION.lstrip("v"), captures=caps)
    out = ROOT / "dist" / f"ampsim-extras-{n}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("LEIA-ME.txt", text)
        for p in sorted(LIC.glob("*.txt")):
            z.write(p, f"licencas/{p.name}")
        for p in files:
            z.write(p, p.relative_to(SRC).as_posix())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"{out}  ({out.stat().st_size / 1e6:.1f} MB)\nSHA-256: {digest}")
    print(f"Capturas: {MODELS_RAW}")
    return out, digest


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "1")
