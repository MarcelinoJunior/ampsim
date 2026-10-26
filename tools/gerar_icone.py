"""Gera assets/ampsim.ico: o logo do AmpSim (ondas brancas num quadrado azul) em todos os tamanhos
que o Windows usa (barra de tarefas, Explorer, atalhos), cada um desenhado para o seu tamanho.

    python tools/gerar_icone.py
"""
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def draw(s):
    img = QImage(s, s, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0, 0, s, s)
    path = QPainterPath()
    path.addRoundedRect(r, s * 0.22, s * 0.22)
    g = QLinearGradient(0, 0, 0, s)
    g.setColorAt(0, QColor("#4b90ff"))
    g.setColorAt(1, QColor("#1f5fd1"))
    qp.fillPath(path, g)
    # ícone pequeno: menos barras e mais grossas (continua legível com 16 px)
    hs = (0.34, 0.7, 0.46, 0.82, 0.5) if s <= 48 else (0.26, 0.5, 0.76, 0.52, 0.86, 0.58, 0.36)
    n = len(hs)
    width = s * (0.1 if s <= 24 else 0.085 if s <= 48 else 0.06)
    qp.setPen(QPen(QColor("white"), width, Qt.SolidLine, Qt.RoundCap))
    left, right = s * 0.24, s * 0.76
    for i, h in enumerate(hs):
        x = left + (right - left) * i / (n - 1)
        half = s * 0.62 * h / 2
        qp.drawLine(QPointF(x, s / 2 - half), QPointF(x, s / 2 + half))
    qp.end()
    return img


def png(img):
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main(out=os.path.join(ROOT, "assets", "ampsim.ico")):
    QApplication.instance() or QApplication(sys.argv[:1])
    images = [(s, png(draw(s))) for s in SIZES]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    with open(out, "wb") as f:
        f.write(head + entries + blobs)
    print(out, f"{len(head + entries + blobs) / 1024:.0f} KB", [s for s, _ in images])


if __name__ == "__main__":
    main()
