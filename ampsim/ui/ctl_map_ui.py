"""Botão direito → "Mapear controle físico…" nas abas Guitarra, Baixo e Vocal e nas janelas FX dos plugins.

O motor está em midi_map.py (ids "guitar/delay/mix", "fx/master/1/param:Wet"…); aqui ficam o menu, o
diálogo de aprender (o mesmo MidiLearnDialog do Pad/Piano), o aviso de controle já usado e a marca dos
controles mapeados (ponto verde no knob e a dica com o controle físico).
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from .. import midi_map as MM
from ..audio import vst
from ..instruments import note_name
from .midi_learn import MidiLearnDialog, key_text
from .theme import C

TIP_KEY = "ctl_base_tip"


def short_key(k):
    """"CC21" / "N60" / "PC3" (etiqueta curta)."""
    if not k:
        return ""
    return {"cc": "CC", "note": "N", "pc": "PC"}.get(k[0], "?") + str(k[2])


# ------------------------------------------------------------------ ligar um controle da tela
def install(w, tid):
    """Dá o id ao controle e o botão direito "Mapear controle físico…"."""
    w.setProperty("ctrl_id", tid)
    w.setContextMenuPolicy(Qt.CustomContextMenu)
    w.customContextMenuRequested.connect(lambda pos, w=w: popup(w, pos))
    return w


def find_win(w):
    """A janela principal (de dentro de uma aba ou de uma janela FX)."""
    obj = w
    while obj is not None:
        top = obj.window()
        if hasattr(top, "inst") and hasattr(top, "inst_bridge"):
            return top
        obj = top.parentWidget()
    return None


def popup(w, pos):
    win = find_win(w)
    tid = w.property("ctrl_id")
    if win is None or not tid:
        return
    m = menu(win, tid, w)
    if m is not None:
        m.exec(w.mapToGlobal(pos))


def menu(win, tid, parent=None):
    """Menu do botão direito num controle mapeável (separado para dar para testar)."""
    info = MM.target_info(tid)
    if info is None:
        return None
    inst = win.inst
    entry = inst.ctl_map.get(tid)
    cur = entry["key"] if entry else None
    m = QMenu(parent)
    title = m.addAction(label_for(win, tid))       # o que este controle é (o título de seção não aparece no tema)
    title.setEnabled(False)
    m.addSeparator()
    m.addAction(f"Mapear controle físico…   (atual: {key_text(cur)})", lambda: learn(win, tid, parent))
    a = m.addAction(f"Remover mapeamento ({key_text(cur)})" if cur else "Remover mapeamento",
                    lambda: unmap(win, tid))
    a.setEnabled(bool(cur))
    if entry and MM.latchable(tid, cur):
        b = m.addAction(LATCH_TEXT)
        b.setCheckable(True)
        b.setChecked(bool(entry.get("latch")))
        b.setToolTip(LATCH_TIP)
        b.triggered.connect(lambda on: set_latch(win, tid, on))
    if entry and not inst.ctl.active(tid, entry):
        m.addAction("Plugin mapeado não está nesta cadeia: mapeamento inativo").setEnabled(False)
    return m


LATCH_TEXT = "Botão que trava (liga num toque, desliga no outro)"
LATCH_TIP = ("Desmarcado: o botão manda um valor ao apertar e 0 ao soltar; só o apertar alterna (segure o quanto "
             "quiser). Marque se o seu botão fica aceso/travado e só manda 0 no toque seguinte.")


def set_latch(win, tid, on):
    """Troca o tipo do botão físico mapeado: momentâneo (padrão) ou que trava."""
    e = win.inst.ctl_map.get(tid)
    if e is None:
        return
    if on and MM.latchable(tid, e["key"]):
        e["latch"] = True
    else:
        e.pop("latch", None)
    win.inst.on_learn()


def _slot(win, tid):
    info = MM.target_info(tid)
    if info is None or info["group"] != "Plugins":
        return None
    chain = win.inst.ctl.chain(info["chain"])
    slots = tuple(chain.slots) if chain is not None else ()
    return slots[info["slot"]] if 0 <= info["slot"] < len(slots) else None


def label_for(win, tid):
    """Nome do mapeamento para mostrar: o de midi_map, com o nome do plugin nos de plugin."""
    info = MM.target_info(tid)
    if info is None:
        return tid
    if info["group"] != "Plugins":
        return info["label"]
    slot = _slot(win, tid)
    name = slot.name if slot is not None and slot.path else ""
    what = {"on": "liga/desliga", "mix": "Mix"}.get(info["what"]) or info.get("name", "")
    where = f"Plugins {MM.CHAIN_NAMES[info['chain']]} › {info['slot'] + 1}" + (f". {name}" if name else "")
    return f"{where} › {what}"


# ------------------------------------------------------------------ aprender / remover
def learn(win, tid, parent=None):
    """Abre o medidor ao vivo e mapeia o controle escolhido. -> True se mapeou/removeu."""
    info = MM.target_info(tid)
    if info is None:
        return False
    inst = win.inst
    if info["group"] == "Plugins":
        slot = _slot(win, tid)
        if slot is None or not slot.path:
            QMessageBox.information(parent or win, "Mapear controle físico",
                                    "Escolha um plugin neste lugar antes de mapear.")
            return False
    label = label_for(win, tid)
    entry = inst.ctl_map.get(tid)
    want = "gire o knob ou mova o fader" if info["kind"] == "knob" else "aperte o botão ou pad (ou gire um knob)"
    if info["kind"] == "choice":
        want = "gire um knob (escolhe a opção) ou aperte um botão (passa para a próxima)"
    switch = info["kind"] in ("switch", "button")
    dlg = MidiLearnDialog(inst, win.inst_bridge, label, parent or win, kinds=MM.kinds_for(tid),
                          current=entry["key"] if entry else None, want=want,
                          latch=bool(entry and entry.get("latch")) if switch else None)
    if not dlg.exec() or dlg.choice is None:
        return False
    if not dlg.choice:
        unmap(win, tid)
        return True
    return assign(win, tid, dlg.choice, parent, latch=bool(getattr(dlg, "latch", False)))


def assign(win, tid, key, parent=None, ask=True, latch=False):
    """Liga `tid` ao controle físico `key`. Se ele já faz outra coisa (aqui, no Pad/Piano, ou é uma tecla
    que toca som), pergunta antes e tira de lá. -> True se mapeou."""
    inst = win.inst
    key = list(key)
    info = MM.target_info(tid)
    if info is None or not MM.valid_key(key) or key[0] not in MM.kinds_for(tid):
        return False
    conf = [c for c in MM.conflicts(inst, key, tid)]
    lines = [d for d, _ in conf]
    plain = MM.is_plain_key(inst, key)
    if plain:
        lines.append(f"A nota {note_name(key[2])} é uma tecla do teclado: enquanto estiver mapeada ela não toca som.")
    if lines and ask:
        txt = (f"{key_text(key)} já está em uso:\n\n• " + "\n• ".join(lines)
               + f"\n\nUsar este controle para “{label_for(win, tid)}”"
               + (" e tirar de lá?" if conf else "?"))
        if QMessageBox.question(parent or win, "Controle já usado", txt) != QMessageBox.Yes:
            return False
    for _, remove in conf:
        remove()
    plugin = ""
    if info["group"] == "Plugins":
        slot = _slot(win, tid)
        if slot is None or not slot.path:
            return False
        plugin = vst.portable_ref(slot.path)
    inst.ctl_map[tid] = MM.make_entry(tid, key, label_for(win, tid), plugin, latch=latch)
    inst.on_learn()
    refresh_tags(win)
    return True


def unmap(win, tid):
    win.inst.ctl_map.pop(tid, None)
    win.inst.on_learn()
    refresh_tags(win)


# ------------------------------------------------------------------ marca nos controles mapeados
def mappable_widgets(win):
    """{id: widget} de todas as abas com controles mapeáveis."""
    out = {}
    for name in MM.TRACKS:
        page = win.pages.get(name)
        out.update(getattr(page, "controls_by_id", {}) or {})
    return out


def refresh_tags(win):
    """Ponto verde nos knobs mapeados e a dica com o controle físico (todas as abas)."""
    cmap = win.inst.ctl_map
    for tid, w in mappable_widgets(win).items():
        tag_widget(w, cmap.get(tid))


def tag_widget(w, entry):
    base = w.property(TIP_KEY)
    if base is None:
        base = w.toolTip() or ""
        w.setProperty(TIP_KEY, base)
    k = entry["key"] if entry else None
    extra = (f"Controlador: {key_text(k)} (botão direito: mapear ou remover)" if k
             else "Botão direito: mapear controle físico")
    w.setToolTip((base + "\n" if base else "") + extra)
    if hasattr(w, "midi_tag"):
        tag = short_key(k)
        if tag != w.midi_tag:
            w.midi_tag = tag
            w.update()


def sync_widgets(win, tids):
    """O controlador mexeu nesses ids: a tela acompanha (knob na posição nova, LED, chave)."""
    pages = set()
    for tid in tids:
        info = MM.target_info(tid)
        if info is None or info["group"] == "Plugins":
            continue
        track, effect, key = info["track"], info["effect"], info["key"]
        page = win.pages.get(track)
        if page is None:
            continue
        if info["kind"] == "knob":
            w = getattr(page, "controls_by_id", {}).get(tid)
            v = win.engine.tracks[track].values.get(effect, {}).get(key)
            if w is not None and v is not None and hasattr(w, "setValue"):
                w.setValue(v)
                if effect == "track":
                    page._update_mute_label()
        elif info["kind"] != "button":
            pages.add(track)
        if effect == "track":
            win.dock.refresh_levels()
    for track in pages:
        win.pages[track].refresh()
        if track == "vocal":
            win.dock.refresh_levels()


# ------------------------------------------------------------------ parâmetros internos de um plugin
class PluginParamsDialog(QDialog):
    """"Parâmetros do plugin": lista os parâmetros internos (nome, valor, controle físico) para mapear."""

    def __init__(self, win, chain_id, index, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.chain_id = chain_id
        self.index = index
        self.setWindowTitle("Parâmetros do plugin")
        self.resize(520, 460)
        lay = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        tip = QLabel("Escolha um parâmetro e clique em “Mapear controle físico…” (ou dê dois cliques). O knob do "
                     "controlador passa a mexer nele em qualquer aba; o valor fica salvo no estado do plugin.")
        tip.setWordWrap(True)
        tip.setObjectName("small")
        tip.setStyleSheet(f"color: {C['dim']};")
        lay.addWidget(tip)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Parâmetro", "Valor", "Controle físico"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 110)
        self.tree.itemDoubleClicked.connect(lambda *_: self.map_current())
        self.tree.currentItemChanged.connect(lambda *_: self._buttons())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.map_btn = QPushButton("Mapear controle físico…")
        self.map_btn.setObjectName("primary")
        self.map_btn.clicked.connect(self.map_current)
        row.addWidget(self.map_btn)
        self.rm_btn = QPushButton("Remover mapeamento")
        self.rm_btn.clicked.connect(self.unmap_current)
        row.addWidget(self.rm_btn)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.fill()
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._values)
        self.timer.start()

    def slot(self):
        chain = self.win.inst.ctl.chain(self.chain_id)
        slots = tuple(chain.slots) if chain is not None else ()
        return slots[self.index] if 0 <= self.index < len(slots) else None

    def tid(self, name):
        return f"fx/{self.chain_id}/{self.index + 1}/param:{name}"

    def fill(self):
        slot = self.slot()
        self.tree.clear()
        self._items = {}
        if slot is None or slot.inst is None:
            self.head.setText("Nenhum plugin carregado neste lugar.")
            self._buttons()
            return
        params = slot.param_list()
        self.head.setText(f"<b>{slot.name}</b> · Plugins {MM.CHAIN_NAMES[self.chain_id]} · lugar {self.index + 1}"
                          + ("" if params else "<br>Este plugin não mostra parâmetros para o AmpSim."))
        cmap = self.win.inst.ctl_map
        for p in params:
            e = cmap.get(self.tid(p["name"]))
            val = (p["text"] + (" " + p["label"] if p["label"] and p["label"] not in p["text"] else "")).strip()
            it = QTreeWidgetItem([p["name"], val or f"{p['raw'] * 100:.0f}%", key_text(e["key"]) if e else ""])
            it.setData(0, Qt.UserRole, p["name"])
            it.setData(1, Qt.UserRole, p["raw"])
            if e:
                it.setForeground(2, QColor(C["green"]))
            self.tree.addTopLevelItem(it)
            self._items[p["name"]] = it
        self._buttons()

    def _values(self):
        """Valores ao vivo (o controlador mexendo): a coluna Valor acompanha."""
        slot = self.slot()
        if slot is None or slot.inst is None or not self.isVisible():
            return
        for name, it in self._items.items():
            raw = slot.param_value(name)
            if raw is not None and abs(raw - (it.data(1, Qt.UserRole) or 0.0)) > 1e-4:
                it.setData(1, Qt.UserRole, raw)
                it.setText(1, f"{raw * 100:.0f}%")

    def _buttons(self):
        it = self.tree.currentItem()
        name = it.data(0, Qt.UserRole) if it is not None else None
        self.map_btn.setEnabled(bool(name))
        self.rm_btn.setEnabled(bool(name) and self.tid(name) in self.win.inst.ctl_map)

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None:
            return
        self.tree.setCurrentItem(it)
        m = menu(self.win, self.tid(it.data(0, Qt.UserRole)), self)
        if m is not None:
            m.exec(self.tree.viewport().mapToGlobal(pos))
            self.fill()

    def map_current(self):
        it = self.tree.currentItem()
        if it is None:
            return
        learn(self.win, self.tid(it.data(0, Qt.UserRole)), self)
        name = it.data(0, Qt.UserRole)
        self.fill()
        if name in self._items:
            self.tree.setCurrentItem(self._items[name])

    def unmap_current(self):
        it = self.tree.currentItem()
        if it is None:
            return
        unmap(self.win, self.tid(it.data(0, Qt.UserRole)))
        self.fill()
