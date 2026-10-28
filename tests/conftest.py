"""Configuração comum dos testes."""
import gc
import os

import pytest

# a janela não procura atualização no GitHub durante os testes
os.environ["AMPSIM_NO_UPDATE"] = "1"


@pytest.fixture(autouse=True)
def _free_closed_windows():
    """Depois de cada teste: apaga de verdade as janelas fechadas com deleteLater() (fora de um laço de
    eventos o Qt só as apaga quando os eventos adiados são entregues) e recolhe os ciclos. Sem isto cada
    janela principal (com o motor de áudio e os timbres) ficava na memória até o fim da bateria: ~60 MB
    por teste de interface, 8 GB no teste ~370 e o processo caía (Aborted / access violation)."""
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
    except ImportError:
        return
    app = QCoreApplication.instance()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()


@pytest.fixture(autouse=True, scope="module")
def _plugins_idle_between_files():
    """Nenhum plugin VST3 trocado fica vivo de um arquivo de teste para o outro: fecha o painel aberto e
    destrói os plugins aposentados na thread dos plugins (a thread continua: o JUCE fica preso à primeira
    thread que carregou um plugin, então ela não pode ser trocada no meio do processo)."""
    yield
    import sys
    vst = sys.modules.get("ampsim.audio.vst")
    if vst is not None and vst.host()._thread is not None:
        gc.collect()
        vst.host().shutdown()
