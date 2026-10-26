"""Número da versão do AmpSim (mostrado no canto da tela e no "Sobre").

Ao publicar mudanças, suba o número: MAJOR.MINOR.PATCH
    PATCH: correções; MINOR: recursos novos; MAJOR: mudanças grandes (ex.: sessões antigas).
O atualizador lê este arquivo no GitHub para dizer qual versão chegou.
"""
import re

VERSION = "0.9.8"
CHANNEL = "beta"            # "" quando sair da fase de testes

PROJECT = "AmpSim"
TAGLINE = "Live Performance"
AUTHOR = "Marcelino"
REPO_URL = "https://github.com/MarcelinoJunior/ampsim"
LICENSE = "GNU GPL-3.0"


def version_text():
    return f"{VERSION} {CHANNEL}".strip()


def parse_version(source):
    """Lê VERSION de um version.py (texto). -> "x.y.z" ou "" """
    m = re.search(r'^VERSION\s*=\s*["\']([0-9][0-9A-Za-z.\-+]*)["\']', source or "", re.M)
    return m.group(1) if m else ""
