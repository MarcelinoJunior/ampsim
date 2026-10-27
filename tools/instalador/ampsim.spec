# Receita do PyInstaller para o AmpSim.exe (pasta com o programa e tudo o que ele precisa).
# Use tools/instalador/montar.py, que roda isto e depois o Inno Setup.
import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
TP = os.path.join(ROOT, "third_party")

datas = [
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "ampsim", "web", "static"), os.path.join("ampsim", "web", "static")),   # tela remota
    (os.path.join(TP, "fluidsynth"), os.path.join("third_party", "fluidsynth")),
    (os.path.join(TP, "soundfonts"), os.path.join("third_party", "soundfonts")),
    (os.path.join(TP, "nam_models"), os.path.join("third_party", "nam_models")),
    (os.path.join(TP, "LEIA-ME.txt"), "third_party"),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "CREDITS.md"), "."),
]

a = Analysis(
    [os.path.join(SPECPATH, "entrada.py")],
    pathex=[ROOT],
    datas=datas,
    # websockets e segno são importados só quando a tela remota liga
    hiddenimports=collect_submodules("ampsim") + collect_submodules("websockets") + ["segno"],
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    # o Numba guarda o código compilado ao lado do arquivo .py de cada função: o pacote ampsim
    # vai como código-fonte (não comprimido no .pyz) para isso funcionar
    module_collection_mode={"ampsim": "py"},
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AmpSim",
    console=False,
    icon=os.path.join(ROOT, "assets", "ampsim.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="AmpSim")
