"""Gera as miniaturas dos timbres do synth AmpSim (assets/timbres/synth-*.jpg).

Arte própria (GPL-3.0, como o resto do AmpSim): a forma de onda de cada timbre desenhada como num
osciloscópio, com brilho, sobre um fundo escuro nas cores do timbre.

    python tools/gerar_artes_synth.py
"""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "timbres")
SIZE = 192
TAU = 2 * math.pi


def saw(x):
    return 2.0 * (x % 1.0) - 1.0


def square(x):
    return 1.0 if (x % 1.0) < 0.5 else -1.0


# arquivo: (cor de fundo em cima, embaixo, cor da onda, ondas [(função de t em 0..1 -> -1..1, alfa)])
ARTS = {
    "synth-baixo-pulsante": ("#1a0b2e", "#05020c", "#ff4fd8", [
        (lambda t: square(t * 4) * (0.35 + 0.6 * abs(math.sin(t * TAU * 2))) * 0.8, 255),
        (lambda t: saw(t * 4) * 0.25, 90)]),
    "synth-pad-quente": ("#3a1606", "#0d0402", "#ffb347", [
        (lambda t: 0.55 * math.sin(t * TAU * 1.5), 255),
        (lambda t: 0.45 * math.sin(t * TAU * 1.5 + 0.9), 130),
        (lambda t: 0.35 * math.sin(t * TAU * 3 + 0.4), 80)]),
    "synth-pad-escuro": ("#0d0a24", "#020107", "#7b6cff", [
        (lambda t: 0.5 * math.sin(t * TAU * 1.2) * math.sin(t * TAU * 0.4 + 0.5), 255),
        (lambda t: 0.4 * math.sin(t * TAU * 2.1 + 1.3) * 0.8, 110),
        (lambda t: 0.3 * math.sin(t * TAU * 0.7 + 2.0), 70)]),
    "synth-cordas": ("#2b1f05", "#080500", "#ffd76a", [
        (lambda t: 0.6 * saw(t * 3), 255),
        (lambda t: 0.6 * saw(t * 3 * 1.012 + 0.07), 140),
        (lambda t: 0.6 * saw(t * 3 * 0.988 + 0.15), 90)]),
    "synth-saw-brilhante": ("#04232e", "#010709", "#3ff0ff", [
        (lambda t: 0.75 * saw(t * 5), 255),
        (lambda t: 0.75 * saw(t * 5 + 0.5) * 0.4, 90)]),
    "synth-orgao": ("#20103a", "#06030d", "#c58bff", [
        (lambda t: 0.33 * (math.sin(t * TAU * 2) + 0.6 * math.sin(t * TAU * 4) + 0.4 * math.sin(t * TAU * 6)
                           + 0.25 * math.sin(t * TAU * 8)), 255)]),
    "synth-sino-suave": ("#06213a", "#01070d", "#8fd3ff", [
        (lambda t: 0.8 * math.exp(-3.2 * t) * (math.sin(t * TAU * 9) + 0.4 * math.sin(t * TAU * 25.3)) / 1.4, 255)]),
}

# timbre -> arquivo (usado por ampsim/ui/widgets.py)
SOUND_ART = {"Baixo Pulsante (AmpSim)": "synth-baixo-pulsante", "Pad Quente (AmpSim)": "synth-pad-quente",
             "Pad Escuro (AmpSim)": "synth-pad-escuro", "Cordas (AmpSim)": "synth-cordas",
             "Saw Brilhante (AmpSim)": "synth-saw-brilhante", "Órgão (AmpSim)": "synth-orgao",
             "Sino Suave (AmpSim)": "synth-sino-suave"}


def render(top, bottom, color, waves):
    img = QImage(SIZE, SIZE, QImage.Format_RGB32)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.Antialiasing)
    bg = QLinearGradient(0, 0, 0, SIZE)
    bg.setColorAt(0, QColor(top))
    bg.setColorAt(1, QColor(bottom))
    qp.fillRect(img.rect(), bg)
    glow = QRadialGradient(QPointF(SIZE / 2, SIZE / 2), SIZE * 0.6)
    c = QColor(color)
    c.setAlpha(55)
    glow.setColorAt(0, c)
    c.setAlpha(0)
    glow.setColorAt(1, c)
    qp.fillRect(img.rect(), glow)
    grid = QColor(color)
    grid.setAlpha(28)
    qp.setPen(QPen(grid, 1))
    for k in range(1, 8):                                  # quadriculado de osciloscópio
        p = SIZE * k / 8
        qp.drawLine(QPointF(p, 0), QPointF(p, SIZE))
        qp.drawLine(QPointF(0, p), QPointF(SIZE, p))
    mid, amp = SIZE / 2, SIZE * 0.4
    for fn, alpha in waves:
        path = QPainterPath()
        for i in range(SIZE * 2 + 1):
            t = i / (SIZE * 2)
            pt = QPointF(t * SIZE, mid - fn(t) * amp)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        for width, a in ((9, 0.12), (5, 0.25), (2.2, 1.0)):  # brilho: traços largos e fracos por baixo
            col = QColor(color)
            col.setAlpha(int(alpha * a))
            qp.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            qp.drawPath(path)
    vign = QRadialGradient(QPointF(SIZE / 2, SIZE / 2), SIZE * 0.75)
    vign.setColorAt(0.6, QColor(0, 0, 0, 0))
    vign.setColorAt(1, QColor(0, 0, 0, 150))
    qp.fillRect(QRectF(img.rect()), vign)
    qp.end()
    return img


def main():
    QApplication.instance() or QApplication(sys.argv[:1])
    os.makedirs(OUT, exist_ok=True)
    for name, (top, bottom, color, waves) in ARTS.items():
        render(top, bottom, color, waves).save(os.path.join(OUT, name + ".jpg"), "JPG", 90)
        print(name)


if __name__ == "__main__":
    main()
