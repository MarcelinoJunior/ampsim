"""Textos do próprio Qt em português (botões padrão dos diálogos: Fechar, Cancelar, OK, Sim, Não,
Restaurar padrões…). O AmpSim escreve os seus textos em português; os do Qt vêm do qtbase_pt_BR.qm que
acompanha o PySide6 (e o instalador, ver tools/instalador/ampsim.spec)."""
import os

QM = "qtbase_pt_BR"


def translation_dirs():
    from PySide6.QtCore import QLibraryInfo
    dirs = [QLibraryInfo.path(QLibraryInfo.TranslationsPath)]
    try:
        import PySide6
        dirs.append(os.path.join(os.path.dirname(PySide6.__file__), "translations"))
    except ImportError:
        pass
    return [d for d in dirs if d]


def load_translator(parent=None):
    """QTranslator com o qtbase_pt_BR carregado, ou None se o arquivo não foi encontrado."""
    from PySide6.QtCore import QTranslator
    tr = QTranslator(parent)
    for d in translation_dirs():
        if tr.load(QM, d):
            return tr
    return None


def install_translator(app):
    """Instala o tradutor no QApplication (chamar logo depois de criá-lo). -> o QTranslator ou None."""
    tr = load_translator(app)
    if tr is not None:
        app.installTranslator(tr)
        app._ampsim_translator = tr          # mantém vivo
    return tr
