"""Saúde do áudio: indicador de falhas na barra de cima e janela com o histórico e dicas."""
import time
from time import perf_counter

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QPushButton, QVBoxLayout

from .theme import C

WINDOW = 60.0          # o indicador olha o último minuto


def level(engine, now=None):
    """("ok" | "aviso" | "ruim" | "desligado", falhas no último minuto, blocos lentos no último minuto)."""
    if not engine.running:
        return "desligado", 0, 0
    ev = engine.recent_events(WINDOW, now)
    falhas = sum(1 for _, k in ev if k == "falha")
    lentos = sum(1 for _, k in ev if k == "lento")
    if falhas == 0 and lentos == 0:
        return "ok", 0, 0
    if falhas >= 5 or lentos >= 20:
        return "ruim", falhas, lentos
    return "aviso", falhas, lentos


def badge(engine, now=None):
    """(texto, cor, dica) do indicador da barra de cima."""
    lv, f, s = level(engine, now)
    if lv == "desligado":
        return "", C["faint"], ""
    if lv == "ok":
        return "● sem falhas", C["green"], "Nenhuma falha de áudio no último minuto. Clique para ver o histórico."
    n = f + s
    color = C["yellow"] if lv == "aviso" else C["red"]
    return (f"● {n} falha{'s' if n != 1 else ''}", color,
            f"No último minuto: {f} falha(s) do driver e {s} bloco(s) lento(s).\nClique para ver o histórico e dicas.")


def tips(engine):
    """Dicas para o que aparece no histórico."""
    cfg = engine.config
    ev = engine.recent_events(600)
    f = sum(1 for _, k in ev if k == "falha")
    s = sum(1 for _, k in ev if k == "lento")
    out = []
    if s:
        out.append("Blocos lentos: o computador não deu conta a tempo. Aumente o buffer (ex.: "
                   f"{cfg.blocksize} → {min(cfg.blocksize * 2, 1024)}), feche outros programas e ligue o "
                   "notebook na tomada (modo de energia “Melhor desempenho”).")
    if f:
        out.append("Falhas do driver: o som não chegou à placa a tempo. Aumente o buffer no AmpSim e, no ASIO, "
                   "também no painel do driver (Placa de som e driver… → Painel do driver ASIO).")
        if cfg.hostapi == "Windows WASAPI" and not cfg.wasapi_exclusive:
            out.append("No WASAPI compartilhado o Windows mistura outros sons junto: o modo exclusivo ou um "
                       "driver ASIO costumam ser mais estáveis.")
        if "asio4all" in (cfg.output_device or "").lower():
            out.append("ASIO4ALL: deixe ligado só o aparelho que você usa (desligue fones Bluetooth na lista).")
    if not out:
        out.append("Tudo certo nos últimos 10 minutos.")
    return out


class HealthDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Saúde do áudio")
        self.resize(560, 460)
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.tips = QLabel()
        self.tips.setWordWrap(True)
        self.tips.setStyleSheet(f"color: {C['yellow']};")
        lay.addWidget(self.tips)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        reset = QPushButton("Zerar contador")
        reset.clicked.connect(self.reset)
        buttons.addButton(reset, QDialogButtonBox.ResetRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        lay.addWidget(buttons)
        self.refresh()

    def refresh(self):
        e = self.engine
        lv, f, s = level(e)
        state = {"ok": "sem falhas no último minuto", "aviso": "algumas falhas no último minuto",
                 "ruim": "muitas falhas no último minuto", "desligado": "áudio desligado"}[lv]
        self.summary.setText(f"<b>Agora:</b> {state}<br>Desde que o áudio ligou: {e.xruns} falha(s) do driver "
                             f"· {e.overloads} bloco(s) lento(s)<br><span style='color:{C['dim']}'>"
                             "Falha do driver = picote/estalo que dá para ouvir. Bloco lento = o cálculo passou "
                             "do prazo (costuma virar falha).</span>")
        self.list.clear()
        now_pc, now_wall = perf_counter(), time.time()
        for t, k in reversed(list(e.events)):
            when = time.strftime("%H:%M:%S", time.localtime(now_wall - (now_pc - t)))
            self.list.addItem(f"{when}  ·  {'falha do driver' if k == 'falha' else 'bloco lento'}")
        if not e.events:
            self.list.addItem("(nenhuma falha registrada)")
        self.tips.setText("\n\n".join(tips(e)))

    def reset(self):
        self.engine.reset_health()
        self.refresh()


def style_badge(btn, engine):
    text, color, tip = badge(engine)
    btn.setVisible(bool(text))
    btn.setText(text)
    btn.setToolTip(tip)
    btn.setStyleSheet(f"QPushButton {{ color: {color}; border: none; background: transparent; "
                      "font-size: 8.5pt; font-weight: 700; padding: 0 4px; text-align: left; }")
    return text
