"""Menu Arquivo: cenas e presets para salvar, abrir e compartilhar (arquivo .ampsim ou código de texto)."""
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QPlainTextEdit, QVBoxLayout,
)

from .. import sharing, storage
from ..audio.engine import TRACKS
from ..sharing import EXTENSION, KIND_TITLES, ShareError

FILTER = f"AmpSim (*{EXTENSION} *.json)"


class FileMenu(QMenu):
    def __init__(self, win):
        super().__init__("Arquivo", win)
        self.win = win
        self.engine = win.engine
        self._author = ""

        def act(text, slot, shortcut=None, tip=""):
            a = self.addAction(text, slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.ApplicationShortcut)
                win.addAction(a)
            a.setToolTip(tip)
            return a

        act("Abrir cena ou preset…", self.open_file, "Ctrl+O")
        act("Colar código recebido (WhatsApp, redes)…", self.paste_code, "Ctrl+Shift+V")
        self.addSeparator()
        act("Salvar cena…", self.save_scene, "Ctrl+S")
        exp = self.addMenu("Exportar preset")
        self.export_menu = exp
        exp.aboutToShow.connect(self._fill_export)
        self.addSeparator()
        share = self.addMenu("Copiar código para compartilhar")
        share.addAction("Cena inteira", lambda: self.copy_code("cena"))
        share.addAction("Preset da aba aberta", lambda: self.copy_code(self._current_kind()))
        share.addAction("Timbres do teclado (Pad/Piano)", lambda: self.copy_code("teclas"))
        self.addSeparator()
        act("Abrir a pasta de cenas e presets", self.open_folder)
        self.addAction("Sobre o AmpSim e licenças…", self.about)

    # ------------------------------------------------------------------ montar documentos
    def _current_kind(self):
        page = self.win.tabs.currentWidget()
        for name, p in self.win.pages.items():
            if p is page:
                return name
        return "guitar"

    def _fill_export(self):
        m = self.export_menu
        m.clear()
        for kind in ("guitar", "bass", "pads", "teclas"):
            m.addAction(KIND_TITLES[kind] + "…", lambda k=kind: self.export_preset(k))

    def _track_data(self, kind):
        data = self.engine.tracks[kind].get_state()
        data["values"].pop("track", None)               # volume/pan ficam com quem recebe
        if kind == "pads":
            data["synth"] = self.engine.synth.get_state()
        return data

    def _doc(self, kind, name):
        e = self.engine
        if kind == "cena":
            st = self.win.scene_state()
            return sharing.make_doc("cena", st, name, self._author)
        if kind == "teclas":
            data = sharing.sound_state(e.instruments.get_state())
        else:
            data = self._track_data(kind)
        return sharing.make_doc("preset", data, name, self._author, trilha=kind)

    def _ask_name(self, title, default):
        dlg = QDialog(self.win)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Nome:"))
        name = QLineEdit(default)
        lay.addWidget(name)
        lay.addWidget(QLabel("Seu nome ou do ministério/banda (opcional, aparece para quem receber):"))
        author = QLineEdit(self._author)
        lay.addWidget(author)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted or not name.text().strip():
            return None
        self._author = author.text().strip()[:80]
        return name.text().strip()[:80]

    def _save_dialog(self, doc, default_name):
        storage.SHARE_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self.win, "Salvar", str(storage.SHARE_DIR / (
            storage._safe(default_name) + EXTENSION)), FILTER)
        if not path:
            return
        if not path.lower().endswith((EXTENSION, ".json")):
            path += EXTENSION
        try:
            sharing.save_file(path, doc)
        except OSError as exc:
            QMessageBox.warning(self.win, "Salvar", f"Não foi possível salvar:\n{exc}")
            return
        self.win.flash_status(f"Salvo em {path} — é só enviar o arquivo para quem quiser.")

    # ------------------------------------------------------------------ ações
    def save_scene(self):
        name = self._ask_name("Salvar cena", "Minha cena")
        if name:
            self._save_dialog(self._doc("cena", name), name)

    def export_preset(self, kind):
        name = self._ask_name(f"Exportar preset — {KIND_TITLES[kind]}", "Meu timbre")
        if name:
            self._save_dialog(self._doc(kind, name), name)

    def copy_code(self, kind):
        name = self._ask_name("Código para compartilhar", "Meu timbre" if kind != "cena" else "Minha cena")
        if not name:
            return
        text = sharing.to_text(self._doc(kind, name))
        QGuiApplication.clipboard().setText(text)
        what = "Cena" if kind == "cena" else KIND_TITLES[kind]
        QMessageBox.information(
            self.win, "Código copiado",
            f"{what} “{name}” copiado ({len(text)} caracteres).\n\n"
            "Cole numa mensagem, grupo ou legenda. Quem receber copia o texto inteiro e usa\n"
            "Arquivo → Colar código recebido.")

    def open_file(self):
        storage.SHARE_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self.win, "Abrir cena ou preset", str(storage.SHARE_DIR), FILTER)
        if path:
            try:
                self.apply_doc(sharing.load_file(path))
            except ShareError as exc:
                QMessageBox.warning(self.win, "Abrir", str(exc))

    def paste_code(self):
        dlg = QDialog(self.win)
        dlg.setWindowTitle("Colar código recebido")
        dlg.resize(520, 260)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Cole aqui o código inteiro (começa com AMPSIM1:)"))
        edit = QPlainTextEdit()
        clip = QGuiApplication.clipboard().text()
        if sharing.TEXT_PREFIX in clip:
            edit.setPlainText(clip)
        lay.addWidget(edit, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self.apply_doc(sharing.from_text(edit.toPlainText()))
        except ShareError as exc:
            QMessageBox.warning(self.win, "Código", str(exc))

    def apply_doc(self, doc):
        """Mostra de quem é e o que é, pede confirmação e aplica (sempre limpo por sharing.sanitize_*)."""
        e = self.engine
        who = f"\nAutor: {doc['autor']}" if doc.get("autor") else ""
        if doc["tipo"] == "cena":
            msg = (f"Abrir a cena “{doc['nome'] or 'sem nome'}”?{who}\n\n"
                   "Substitui amps, efeitos, timbres e pads de todas as abas.\n"
                   "Dispositivo de áudio e mapeamento do controlador continuam os seus.")
        else:
            msg = (f"Importar o preset “{doc['nome'] or 'sem nome'}” para {KIND_TITLES[doc['trilha']]}?{who}")
        if QMessageBox.question(self.win, "Abrir", msg) != QMessageBox.Yes:
            return
        d = doc["dados"]
        inst_now = e.instruments.get_state()
        if doc["tipo"] == "cena":
            self.win.apply_scene(sharing.sanitize_scene(d, inst_now))
            self.win.flash_status(f"Cena “{doc['nome']}” aberta.")
            return
        kind = doc["trilha"]
        name = doc["nome"] or "Importado"
        if doc.get("autor"):
            name += f" ({doc['autor']})"
        if kind == "teclas":
            clean = sharing.sanitize_instruments(d, inst_now)
            storage.save_user_preset("teclas", name, clean)      # fica em "Meus timbres"
            self.win.load_from_bank("keys_user", storage._safe(name))
            self.win._rebuild_ready_combo()
        else:
            data = sharing.sanitize_track(d)
            if kind == "pads":
                data["synth"] = sharing.sanitize_synth(d.get("synth"))
            storage.save_user_preset(kind, name, data)
            page = self.win.track_pages[kind]
            page.apply_preset_data(data)
            page.reload_presets(select=("user", storage._safe(name)))
            if kind == "pads":
                self.win.tabs.setCurrentWidget(self.win.pad_view)
                self.win.pad_view.show_view(2)
            else:
                self.win.tabs.setCurrentWidget(page)
        self.win.bank.reload()
        missing = self._missing_capture(kind, d)
        self.win.flash_status(f"Preset “{doc['nome']}” importado." + missing)

    def _missing_capture(self, kind, d):
        if kind not in TRACKS:
            return ""
        from ..dsp.nam import list_captures

        nam = (d.get("values") or {}).get("nam") or {}
        f = nam.get("file") if isinstance(nam, dict) else None
        if isinstance(f, str) and f and nam.get("on") and f not in list_captures():
            return f" Atenção: a captura NAM “{f}” não está neste computador."
        return ""

    def open_folder(self):
        storage.SHARE_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(storage.SHARE_DIR)))

    def about(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        QMessageBox.about(
            self.win, "Sobre o AmpSim",
            "<b>AmpSim</b> — simulador de amp, pads e piano para quem tem pouco orçamento.<br><br>"
            "Software livre sob a licença <b>GNU GPL-3.0</b>: pode usar, copiar, estudar, modificar e "
            "distribuir, desde que mantenha a mesma licença e o código aberto.<br><br>"
            "Os nomes e desenhos de amplificadores e teclados são homenagens; as marcas pertencem aos "
            "seus donos e o AmpSim não é afiliado a eles. Os timbres são exemplos criados pelo AmpSim "
            "ou vindos de bancos gratuitos — não são cópias do som dos equipamentos originais.<br><br>"
            f"Créditos e licenças de terceiros: CREDITS.md na pasta do programa<br>({root})")
