"""Janela "Webserver": liga a tela remota, mostra o link/QR para o celular e define o que cada
perfil vê (ampsim/web). As mudanças valem na hora."""
import copy
import io

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSpinBox, QVBoxLayout,
)

from ..web import config as wcfg
from .theme import C

SHORT = dict(wcfg.PANELS)


def qr_pixmap(text, scale=5):
    """QR code do link (segno); None se a biblioteca faltar."""
    try:
        import segno
    except ImportError:
        return None
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=2, dark="#000000", light="#ffffff")
    pm = QPixmap()
    pm.loadFromData(buf.getvalue(), "PNG")
    return pm


def panels_text(telas):
    if set(telas) == set(wcfg.PANEL_IDS):
        return "todas as telas (espelho)"
    return ", ".join(SHORT[t].split(" (")[0] for t in telas) or "nenhuma tela"


class UserDialog(QDialog):
    """Criar/alterar um usuário: nome, senha e telas que ele vê."""

    def __init__(self, parent, user=None):
        super().__init__(parent)
        self.setWindowTitle("Alterar usuário" if user else "Novo usuário")
        self.resize(380, 0)
        lay = QVBoxLayout(self)
        g = QGridLayout()
        g.addWidget(QLabel("Nome"), 0, 0)
        self.name = QLineEdit(user["nome"] if user else "")
        self.name.setMaxLength(40)
        self.name.setPlaceholderText("ex.: baterista, tecladista, mesa")
        g.addWidget(self.name, 0, 1)
        g.addWidget(QLabel("Senha"), 1, 0)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("deixe vazio para manter a atual" if user else "senha deste usuário")
        g.addWidget(self.password, 1, 1)
        lay.addLayout(g)
        lay.addWidget(QLabel("O que este usuário vê no celular/tablet:"))
        self.checks = {}
        for pid, label in wcfg.PANELS:
            cb = QCheckBox(label)
            cb.setChecked(pid in (user["telas"] if user else wcfg.PANEL_IDS))
            self.checks[pid] = cb
            lay.addWidget(cb)
        row = QHBoxLayout()
        allb = QPushButton("Espelho (todas)")
        allb.setToolTip("As mesmas funções da tela do AmpSim")
        allb.clicked.connect(lambda *_: [c.setChecked(True) for c in self.checks.values()])
        row.addWidget(allb)
        pads = QPushButton("Só pads")
        pads.clicked.connect(lambda *_: [c.setChecked(p == "pads") for p, c in self.checks.items()])
        row.addWidget(pads)
        row.addStretch(1)
        lay.addLayout(row)
        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {C['red']};")
        lay.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.is_new = user is None

    def values(self):
        return self.name.text().strip(), self.password.text(), [p for p, c in self.checks.items() if c.isChecked()]

    def _ok(self):
        name, pw, _ = self.values()
        if not name:
            self.error.setText("Escreva um nome.")
        elif self.is_new and len(pw) < 4:
            self.error.setText("A senha precisa de pelo menos 4 caracteres.")
        elif pw and len(pw) < 4:
            self.error.setText("A senha precisa de pelo menos 4 caracteres.")
        else:
            self.accept()


class WebServerDialog(QDialog):
    def __init__(self, remote, parent=None):
        super().__init__(parent)
        self.remote = remote
        self.cfg = copy.deepcopy(remote.cfg)
        self.setWindowTitle("Webserver · tela remota")
        self.resize(720, 640)
        lay = QVBoxLayout(self)

        intro = QLabel("Use um celular, tablet ou outro computador <b>na mesma rede Wi-Fi</b> como segunda tela "
                       "do AmpSim: pads, faders, setlist, BPM e mute de emergência, direto no navegador.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        # ---- ligar + porta
        top = QHBoxLayout()
        self.on = QCheckBox("Ligar a tela remota")
        self.on.setStyleSheet("font-weight: 600;")
        self.on.setChecked(self.cfg["ligado"] and remote.server.running)
        self.on.toggled.connect(self._toggle)
        top.addWidget(self.on)
        top.addStretch(1)
        top.addWidget(QLabel("Porta"))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self.cfg["porta"])
        self.port.setToolTip("Normalmente 8080. Troque se outro programa já usa esta porta.")
        self.port.editingFinished.connect(self._port_changed)
        top.addWidget(self.port)
        lay.addLayout(top)

        # ---- link + QR
        card = QFrame()
        card.setObjectName("card")
        cl = QHBoxLayout(card)
        left = QVBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        self.ip = QComboBox()
        self.ip.setToolTip("Se o computador tem mais de uma rede (cabo e Wi-Fi), escolha a mesma do celular")
        self.ip.currentIndexChanged.connect(lambda *_: self._show_link())
        left.addWidget(self.ip)
        self.link = QLabel("")
        self.link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.link.setOpenExternalLinks(False)
        self.link.linkActivated.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
        self.link.setStyleSheet("font-size: 15pt; font-weight: 700;")
        left.addWidget(self.link)
        brow = QHBoxLayout()
        self.copy_btn = QPushButton("Copiar link")
        self.copy_btn.clicked.connect(lambda *_: QGuiApplication.clipboard().setText(self.current_url()))
        brow.addWidget(self.copy_btn)
        self.open_btn = QPushButton("Abrir aqui")
        self.open_btn.setToolTip("Abre a página neste computador para conferir")
        self.open_btn.clicked.connect(lambda *_: QDesktopServices.openUrl(QUrl(self.current_url())))
        brow.addWidget(self.open_btn)
        brow.addStretch(1)
        left.addLayout(brow)
        self.clients = QLabel("")
        self.clients.setObjectName("small")
        self.clients.setWordWrap(True)
        left.addWidget(self.clients)
        left.addStretch(1)
        cl.addLayout(left, 1)
        self.qr = QLabel()
        self.qr.setFixedSize(190, 190)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setToolTip("Aponte a câmera do celular para abrir a tela remota")
        cl.addWidget(self.qr)
        lay.addWidget(card)

        # ---- acesso
        lay.addWidget(self._title("Quem pode entrar e o que vê"))
        self.open_mode = QRadioButton("Sem senha: qualquer aparelho na rede entra e vê as telas marcadas")
        self.login_mode = QRadioButton("Com usuário e senha: cada usuário vê as telas dele")
        (self.login_mode if self.cfg["login"] else self.open_mode).setChecked(True)
        self.open_mode.toggled.connect(self._mode_changed)
        lay.addWidget(self.open_mode)
        self.open_box = QFrame()
        og = QGridLayout(self.open_box)
        og.setContentsMargins(24, 0, 0, 0)
        self.open_checks = {}
        for i, (pid, label) in enumerate(wcfg.PANELS):
            cb = QCheckBox(label)
            cb.setChecked(pid in self.cfg["aberto"])
            cb.toggled.connect(self._open_changed)
            self.open_checks[pid] = cb
            og.addWidget(cb, i // 2, i % 2)
        lay.addWidget(self.open_box)
        lay.addWidget(self.login_mode)
        self.login_box = QFrame()
        ul = QHBoxLayout(self.login_box)
        ul.setContentsMargins(24, 0, 0, 0)
        self.users = QListWidget()
        self.users.setMinimumHeight(110)
        self.users.itemDoubleClicked.connect(lambda *_: self.edit_user())
        ul.addWidget(self.users, 1)
        ub = QVBoxLayout()
        for text, slot in (("Novo usuário", self.new_user), ("Alterar", self.edit_user), ("Remover", self.remove_user)):
            b = QPushButton(text)
            b.clicked.connect(lambda *_, s=slot: s())
            ub.addWidget(b)
        ub.addStretch(1)
        ul.addLayout(ub)
        lay.addWidget(self.login_box)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setObjectName("small")
        lay.addWidget(self.warn)
        tip = QLabel("Na primeira vez o Windows pode perguntar sobre o Firewall: permita em <b>Redes privadas</b>. "
                     "A página funciona só dentro da sua rede (não fica na internet).")
        tip.setWordWrap(True)
        tip.setObjectName("small")
        tip.setStyleSheet(f"color: {C['dim']};")
        lay.addWidget(tip)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(bb)

        self._fill_users()
        self._mode_changed()
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_clients)
        self.timer.start(1000)

    def _title(self, text):
        t = QLabel(text)
        t.setStyleSheet("font-weight: 600; margin-top: 6px;")
        return t

    # ------------------------------------------------------------------ aplicar
    def _apply(self):
        ok = self.remote.set_config(copy.deepcopy(self.cfg))
        if not ok and self.cfg["ligado"]:
            self.cfg["ligado"] = False
            self.remote.cfg["ligado"] = False
            wcfg.save(self.remote.cfg)
            self.on.blockSignals(True)
            self.on.setChecked(False)
            self.on.blockSignals(False)
        self.refresh()
        return ok

    def _toggle(self, on):
        self.cfg["ligado"] = bool(on)
        self.cfg["porta"] = self.port.value()
        self._apply()

    def _port_changed(self):
        if self.port.value() != self.cfg["porta"]:
            self.cfg["porta"] = self.port.value()
            self._apply()

    def _mode_changed(self, *_):
        self.cfg["login"] = self.login_mode.isChecked()
        self.open_box.setEnabled(not self.cfg["login"])
        self.login_box.setEnabled(self.cfg["login"])
        if self.cfg["login"] != self.remote.cfg["login"]:
            self._apply()
        else:
            self.refresh()

    def _open_changed(self, *_):
        self.cfg["aberto"] = [p for p, c in self.open_checks.items() if c.isChecked()]
        self._apply()

    # ------------------------------------------------------------------ usuários
    def _fill_users(self):
        self.users.clear()
        for u in self.cfg["usuarios"]:
            it = QListWidgetItem(f"{u['nome']}  ·  {panels_text(u['telas'])}")
            it.setData(Qt.UserRole, u["nome"])
            self.users.addItem(it)

    def _selected(self):
        it = self.users.currentItem()
        if it is None:
            return None
        return next((u for u in self.cfg["usuarios"] if u["nome"] == it.data(Qt.UserRole)), None)

    def save_user(self, name, password, panels, old_name=None):
        if old_name and old_name.lower() != name.lower():
            if any(u["nome"].lower() == name.lower() for u in self.cfg["usuarios"]):
                raise ValueError("Já existe um usuário com este nome.")
            old = next(u for u in self.cfg["usuarios"] if u["nome"] == old_name)
            old["nome"] = name
        elif old_name is None and any(u["nome"].lower() == name.lower() for u in self.cfg["usuarios"]):
            raise ValueError("Já existe um usuário com este nome.")
        wcfg.set_user(self.cfg, name, password, panels)
        self._fill_users()
        self._apply()

    def new_user(self):
        d = UserDialog(self)
        if d.exec():
            try:
                self.save_user(*d.values())
            except ValueError as exc:
                QMessageBox.warning(self, "Usuário", str(exc))

    def edit_user(self):
        u = self._selected()
        if u is None:
            return
        d = UserDialog(self, u)
        if d.exec():
            try:
                self.save_user(*d.values(), old_name=u["nome"])
            except ValueError as exc:
                QMessageBox.warning(self, "Usuário", str(exc))

    def remove_user(self):
        u = self._selected()
        if u is None:
            return
        if QMessageBox.question(self, "Remover usuário", f"Remover o usuário {u['nome']}?") != QMessageBox.Yes:
            return
        wcfg.remove_user(self.cfg, u["nome"])
        self._fill_users()
        self._apply()

    # ------------------------------------------------------------------ mostrar
    def current_url(self):
        srv = self.remote.server
        ip = self.ip.currentText() or "127.0.0.1"
        return f"http://{ip}:{srv.port or self.cfg['porta']}"

    def refresh(self):
        srv = self.remote.server
        running = srv.running
        if running:
            self.status.setText(f"<span style='color:{C['green']}'>● Ligada</span> · abra no celular:")
        elif srv.error:
            self.status.setText(f"<span style='color:{C['red']}'>● {srv.error}</span>")
        else:
            self.status.setText("● Desligada. Marque <b>Ligar a tela remota</b> para gerar o link.")
        ips = [u.split("//", 1)[1].rsplit(":", 1)[0] for u in srv.urls()] if running else []
        cur = self.ip.currentText()
        self.ip.blockSignals(True)
        self.ip.clear()
        self.ip.addItems(ips)
        if cur in ips:
            self.ip.setCurrentText(cur)
        self.ip.blockSignals(False)
        self.ip.setVisible(len(ips) > 1)
        for w in (self.link, self.copy_btn, self.open_btn, self.qr):
            w.setVisible(running)
        self._show_link()
        warn = []
        if self.cfg["login"] and not self.cfg["usuarios"]:
            warn.append("⚠ Crie pelo menos um usuário, senão ninguém consegue entrar.")
        if not self.cfg["login"]:
            if not self.cfg["aberto"]:
                warn.append("⚠ Nenhuma tela marcada: quem entrar não vê nada.")
            warn.append("Sem senha, qualquer pessoa conectada na mesma rede Wi-Fi pode mexer no som. "
                        "Em rede aberta (de visitantes), prefira usuário e senha.")
        self.warn.setText("\n".join(warn))
        self.warn.setStyleSheet(f"color: {C['yellow']};" if warn and warn[0].startswith("⚠") else f"color: {C['dim']};")
        self._refresh_clients()

    def _show_link(self):
        if not self.remote.server.running:
            self.qr.clear()
            return
        url = self.current_url()
        self.link.setText(f"<a style='color:{C['text']}' href='{url}'>{url}</a>")
        pm = qr_pixmap(url)
        if pm is not None:
            self.qr.setPixmap(pm.scaled(186, 186, Qt.KeepAspectRatio, Qt.FastTransformation))
        else:
            self.qr.setText("(QR indisponível)")

    def _refresh_clients(self):
        srv = self.remote.server
        if not srv.running:
            self.clients.setText("")
            return
        conn = srv.connected()
        self.clients.setText("Nenhum aparelho conectado agora." if not conn else
                             "Conectados: " + ", ".join(f"{n} ({a})" for n, a in conn))

    def done(self, r):
        self.timer.stop()
        super().done(r)
