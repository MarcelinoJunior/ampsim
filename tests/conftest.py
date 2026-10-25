"""Configuração comum dos testes."""
import os

# a janela não procura atualização no GitHub durante os testes
os.environ["AMPSIM_NO_UPDATE"] = "1"
