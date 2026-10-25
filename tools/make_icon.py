"""Gera assets/ampsim.ico (knob de amplificador). Uso: python tools/make_icon.py"""
import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

OUT = Path(__file__).resolve().parent.parent / "assets" / "ampsim.ico"


def draw(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor("#1d2026"))
    qp.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 48 * s, 48 * s)
    c = QPointF(128 * s, 132 * s)
    r = 78 * s
    rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    qp.setPen(QPen(QColor("#3a3e48"), 22 * s, Qt.SolidLine, Qt.RoundCap))
    qp.drawArc(rect, 225 * 16, -270 * 16)
    qp.setPen(QPen(QColor("#e8a33d"), 22 * s, Qt.SolidLine, Qt.RoundCap))
    qp.drawArc(rect, 225 * 16, -200 * 16)
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor("#2f333c"))
    qp.drawEllipse(c, r - 30 * s, r - 30 * s)
    ang = math.radians(225 - 200)
    qp.setPen(QPen(QColor("#f0f0f0"), 14 * s, Qt.SolidLine, Qt.RoundCap))
    qp.drawLine(c, QPointF(c.x() + (r - 36 * s) * math.cos(ang), c.y() - (r - 36 * s) * math.sin(ang)))
    qp.end()
    return img


def main():
    QGuiApplication(sys.argv)
    OUT.parent.mkdir(exist_ok=True)
    # o plugin ICO do Qt grava o maior tamanho; o Windows reduz para os menores
    if not draw(256).save(str(OUT), "ICO"):
        raise SystemExit("Falha ao gravar o .ico")
    print(OUT)


if __name__ == "__main__":
    main()
