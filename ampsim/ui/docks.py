"""Subjanelas da janela principal (como os "docks" do OBS): cada parte da tela é um QDockWidget que dá
para arrastar para outra borda, empilhar em abas, redimensionar, destacar como janela própria (até em
outro monitor) e fechar. O menu Exibir mostra/esconde cada uma, trava/destrava todas e volta ao layout
padrão; o layout fica salvo na sessão (state.json, chave ui.janela).

As subjanelas da tela Pad/Piano (Timbre, Pad contínuo, Instrumento / Layer) só aparecem nessa tela: ao
ir para Guitarra/Baixo elas somem e voltam ao voltar, do jeito que o usuário deixou (escondida continua
escondida). A subjanela "Faders" leva os faders da aba Faders / Pads para uma janela própria (ex.: faders
grandes num segundo monitor); fechada, os faders voltam para a aba. Ela abre solta (nunca empurra a janela
principal para fora da tela) e, em geral, mostrar ou encaixar uma subjanela nunca aumenta a janela
sozinha: se não couber, ela entra em abas junto de outra da mesma borda e, se foi o usuário que a mostrou
ou encaixou, volta a ficar solta. Subjanelas que o usuário não soltou nunca são soltas automaticamente;
por isso a largura mínima da janela é a da tela Pad/Piano em todas as abas (estreitar na Guitarra e voltar
à Pad/Piano não tem como faltar espaço).

Numa subjanela o nome já está na barra dela: o título repetido dentro do painel some, e os botões que
ficavam nele (☰ e recolher do Setlist, Parar e EQ do Pad contínuo) passam para a barra da subjanela.
"""
import base64

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QLabel, QMainWindow, QMenu, QStackedWidget, QToolButton, QWidget,
)

from shiboken6 import isValid

from .dock import DOCK_H, DOCK_MIN
from .icons import icon
from .theme import C

# muda quando o conjunto/arrumação das subjanelas mudar: layout salvo de outra versão é ignorado
LAYOUT_VERSION = 2
FEATURES = (QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
# (chave, título, área padrão, só na tela Pad/Piano)
DOCKS = (
    ("setlist", "Setlist", Qt.LeftDockWidgetArea, False),
    ("banco", "Banco de presets", Qt.LeftDockWidgetArea, False),
    ("timbre", "Timbre (preset e camadas)", Qt.TopDockWidgetArea, True),
    ("pad_continuo", "Pad contínuo", Qt.TopDockWidgetArea, True),
    ("instrumento", "Instrumento / Layer", Qt.RightDockWidgetArea, True),
    ("barra", "Pads / Faders / MIDI", Qt.BottomDockWidgetArea, False),
    ("faders", "Faders", Qt.RightDockWidgetArea, False),
)
HIDDEN_BY_DEFAULT = ("faders",)
DEFAULT_LEFT_W = 242                  # largura padrão da coluna da esquerda (Setlist e Banco)
FADERS_SIZE = (700, 420)              # "Faders" na 1ª vez: janela própria deste tamanho, no meio da tela
SETLIST_H = 260                       # altura padrão da subjanela Setlist (aberta)
QWIDGETSIZE_MAX = 16777215


def _b64(data):
    return base64.b64encode(bytes(data)).decode("ascii")


def _unb64(text):
    try:
        return QByteArray(base64.b64decode(text.encode("ascii"), validate=True))
    except (ValueError, AttributeError):
        return None


class DockManager:
    def __init__(self, win: QMainWindow):
        self.win = win
        self.docks = {}
        self.titles = {}
        self.inner_heads = {}
        self.actions = {}
        self.page_docks = tuple(k for k, *_, page in DOCKS if page)
        self.user_visible = {k: k not in HIDDEN_BY_DEFAULT for k, *_ in DOCKS}
        self.locked = False
        self.action_lock = None
        self._no_title = {}
        self.action_restore = None
        self.page = "pads"
        self._guard = False
        self._faders_fresh = True             # ainda não foi aberta: abre solta, no meio da tela da janela
        self._auto = False                    # mexendo nas subjanelas por conta própria (não é o usuário)
        self._just_docked = set()             # encaixadas agora pelo usuário (destacar/encaixar, arrastar)
        self._grown_from = None               # tamanho da janela antes de ela crescer sozinha
        self._fix_pending = False
        self._pads_min = None                 # tamanho mínimo da janela na tela Pad/Piano
        self._setlist_h = SETLIST_H           # altura do Setlist antes de recolher
        pv = win.pad_view
        widgets = {"setlist": win.setlist, "banco": win.bank, "timbre": pv.header_card,
                   "pad_continuo": pv.cont_card, "instrumento": pv.side_panel, "barra": win.dock}
        self._faders_empty = QLabel("Os faders estão na aba Faders / Pads.")
        win.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        # colunas da esquerda/direita vão até em cima; a área de baixo ocupa a largura toda
        win.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        win.setCorner(Qt.TopRightCorner, Qt.RightDockWidgetArea)
        win.setCorner(Qt.BottomLeftCorner, Qt.BottomDockWidgetArea)
        win.setCorner(Qt.BottomRightCorner, Qt.BottomDockWidgetArea)
        for key, title, area, _page in DOCKS:
            d = QDockWidget(title, win)
            d.setObjectName("subjanela_" + key)
            d.setFeatures(FEATURES)
            d.setWidget(widgets.get(key, self._faders_empty))
            self.titles[key] = _TitleBar(d)
            d.setTitleBarWidget(self.titles[key])
            d.toggleViewAction().toggled.connect(lambda on, k=key: self._toggled(k, on))
            d.topLevelChanged.connect(lambda floating, k=key: self._top_level(k, floating))
            d.dockLocationChanged.connect(lambda *_, k=key: self._docked(k))
            self.docks[key] = d
            win.addDockWidget(area, d)
        self._move_headers(win, pv)
        # barra de baixo: ao expandir volta à última altura escolhida no divisor
        win.dock.collapsedChanged.connect(self._bar_collapsed)
        win.setlist.foldedChanged.connect(self._setlist_folded)
        win.tabs.no_floor = pv
        self._watch = _GrowWatch(self)
        win.installEventFilter(self._watch)
        self.default_layout()

    def _move_headers(self, win, pv):
        """Título repetido dentro do painel some (o nome está na barra da subjanela); os botões dele vão
        para a barra. Travada e encaixada (sem barra) o título de dentro volta."""
        self.inner_heads = {"setlist": win.setlist.head_widgets, "banco": win.bank.head_widgets,
                            "instrumento": pv.side_head}
        sl = win.setlist
        sl.more.setFixedSize(26, 20)
        sl.fold.setFixedSize(24, 20)
        self.titles["setlist"].add_extras(sl.more, sl.fold)
        pv.stop_btn.setFixedHeight(20)
        pv.cont_eq_btn.setFixedSize(28, 20)
        self.titles["pad_continuo"].set_label(pv.cont_title)      # "Pad contínuo · segue o acorde"
        self.titles["pad_continuo"].add_extras(pv.stop_btn, pv.cont_eq_btn)
        for ws in self.inner_heads.values():
            for w in ws:
                w.hide()

    def _bar_collapsed(self, on):
        if self.page != "pads":
            self._apply_floor()
        if on:
            return
        bar, d, win = self.win.dock, self.docks["barra"], self.win
        h = max(bar.last_height, bar.minimumHeight())
        if d.isFloating():
            d.resize(d.width(), h + self.titles["barra"].sizeHint().height())
            return
        # já abre na altura escolhida (sem passar pelo mínimo), até onde cabe sem aumentar a janela
        if win.isVisible() and d.isVisible():
            if win.layout() is not None:
                win.layout().invalidate()
            slack = win.height() - win.minimumSizeHint().height()
            bar.hold_height = min(h, bar.minimumHeight() + max(0, slack))
            bar._fit_height()

        def settle():
            if not (isValid(win) and isValid(bar)):
                return
            win.resizeDocks([d], [h + self._title_h(d)], Qt.Vertical)
            bar.hold_height = 0
            bar._fit_height()
        QTimer.singleShot(0, settle)

    def _title_h(self, d):
        t = d.titleBarWidget()
        return t.sizeHint().height() if t is not None else 0

    # ------------------------------------------------------------------ layout padrão
    def default_layout(self):
        """Visual de sempre: Setlist e Banco à esquerda, Timbre e Pad contínuo em cima da tela Pad/Piano,
        Instrumento / Layer à direita e Pads / Faders / MIDI embaixo; Faders separados escondidos."""
        win, d = self.win, self.docks
        self._guard = True
        try:
            for key, _title, area, _page in DOCKS:
                d[key].setFloating(False)
                win.addDockWidget(area, d[key])
            win.splitDockWidget(d["setlist"], d["banco"], Qt.Vertical)
            win.splitDockWidget(d["timbre"], d["pad_continuo"], Qt.Horizontal)
            d["faders"].hide()                       # Faders: janela própria (não aperta a janela)
            d["faders"].setFloating(True)
            self._faders_fresh = True
            self._setlist_h = SETLIST_H
            win.resizeDocks([d["setlist"], d["banco"]], [SETLIST_H, 400], Qt.Vertical)
            win.resizeDocks([d["setlist"]], [DEFAULT_LEFT_W], Qt.Horizontal)
            win.resizeDocks([d["instrumento"]], [280], Qt.Horizontal)
            win.resizeDocks([d["timbre"]], [1], Qt.Vertical)      # em cima: só o necessário
            win.dock.last_height = DOCK_H
            if not win.dock.collapsed:
                win.resizeDocks([d["barra"]], [DOCK_H + self._title_h(d["barra"])], Qt.Vertical)
            for key in self.user_visible:
                self.user_visible[key] = key not in HIDDEN_BY_DEFAULT
            self._just_docked.clear()
        finally:
            self._guard = False
        self.set_page(self.page)
        self._setlist_folded(self.win.setlist.data["recolhido"])
        self._measure_pads()
        self._shrink_back()

    # ------------------------------------------------------------------ mostrar / esconder
    def _toggled(self, key, on):
        """A subjanela apareceu/sumiu (menu, X da subjanela, restoreState)."""
        if key == "faders":
            self._place_faders(on)
        if self._guard or not isValid(self.win):
            return
        if key in self.page_docks and self.page != "pads":
            return                                  # sumiu porque a tela não é a Pad/Piano
        self.user_visible[key] = on
        if key in self.actions:
            self.actions[key].setChecked(on)
        if not on:
            QTimer.singleShot(0, self._shrink_back)    # fechou a que fez a janela crescer: volta
        if self.page == "pads":
            self._measure_pads()
        else:
            self._apply_floor()

    def _top_level(self, key, floating):
        """Soltou/encaixou (botão da barra, duplo clique no título, arrastar)."""
        self._apply_lock()
        if not floating:
            self._docked(key)

    def _docked(self, key):
        if self._guard or self._auto or not isValid(self.win):
            return
        d = self.docks[key]
        if not d.isFloating():
            self._just_docked.add(key)
            self._schedule_fix()

    def _schedule_fix(self):
        if not self._fix_pending:
            self._fix_pending = True
            QTimer.singleShot(0, self._fix_growth)

    def _grew(self, old, new):
        """A janela cresceu: foi o mínimo das subjanelas encaixadas que a empurrou (e não o usuário)?"""
        win = self.win
        if self._auto or not win.isVisible() or old.width() <= 0 or old.height() <= 0:
            return
        if win.isMaximized() or win.isFullScreen():
            return
        mn = win.minimumSize()
        forced = ((new.width() > old.width() and new.width() == mn.width())
                  or (new.height() > old.height() and new.height() == mn.height()))
        if forced:
            if self._grown_from is None:
                self._grown_from = QSize(old)
            self._schedule_fix()
        elif not self._fix_pending:
            self._grown_from = None                  # o usuário redimensionou: esse passa a ser o tamanho

    def _fix_growth(self):
        """Depois de encaixar: a que não coube vai para abas com uma vizinha ou volta a ficar solta, e a
        janela volta ao tamanho de antes."""
        self._fix_pending = False
        if not isValid(self.win):
            return
        keys = [k for k in self._just_docked if self.docks[k].isVisible() and not self.docks[k].isFloating()]
        self._just_docked.clear()
        before = self._grown_from
        if before is None:
            return
        self._keep_size(keys, before, allow_float=True, notify=True)
        self._shrink_back()

    def _shrink_back(self):
        """A janela tinha crescido sozinha e agora cabe de novo no tamanho de antes: volta a ele."""
        win, before = self.win, self._grown_from
        if before is None or not isValid(win):
            return
        if win.isMaximized() or win.isFullScreen():
            self._grown_from = None
            return
        if self._too_big(before):
            return
        self._grown_from = None
        if win.size() != before:
            self._auto = True
            try:
                if win.layout() is not None:
                    win.layout().activate()
                win.resize(before)
            finally:
                self._auto = False

    def _place_faders(self, on):
        bar, fd = self.win.dock, self.docks["faders"]
        # o Python saindo sem fechar a janela apaga os widgets antes dos sinais pararem: não faz nada
        if not (isValid(self.win) and isValid(bar) and isValid(fd) and isValid(bar.faders_box)):
            return
        try:
            if on and not bar.faders_detached:
                fd.setWidget(bar.detach_faders())
                bar.faders_box.show()
            elif not on and bar.faders_detached:
                fd.setWidget(self._faders_empty)
                bar.attach_faders()
            bar.refresh_levels()
        except RuntimeError:                         # algum fader já destruído (saída do programa)
            pass

    def set_visible(self, key, on):
        """Pelo menu Exibir (ou pelo programa): lembra a escolha e mostra/esconde se cabe na tela atual."""
        self.user_visible[key] = bool(on)
        if key in self.actions:
            self.actions[key].setChecked(bool(on))
        if key in self.page_docks and self.page != "pads":
            return
        d = self.docks[key]
        if on and key == "faders" and self._faders_fresh and d.isFloating():
            self._center_floating(d, *FADERS_SIZE)
        before = self.win.size()
        self.release_floor()
        self._guard = True
        try:
            d.setVisible(bool(on))
        finally:
            self._guard = False
        if key == "faders":
            self._place_faders(bool(on))
            self._faders_fresh = False
        if on:
            self._keep_size([key], before, allow_float=True)
        if self.page == "pads":
            self._measure_pads()
        self._apply_floor()

    # ------------------------------------------------------------------ a janela não cresce sozinha
    def _too_big(self, size):
        """O mínimo das subjanelas encaixadas passou de `size` (a janela teria de crescer)."""
        win = self.win
        lay = win.layout()
        if lay is not None:
            lay.invalidate()
        m = win.minimumSizeHint()
        return m.width() > size.width() or m.height() > size.height()

    def _keep_size(self, keys, before, allow_float=False, notify=False):
        """Mostrou/encaixou subjanelas: se a janela teve/teria de crescer além de `before` (o tamanho de
        antes), cada uma entra em abas com outra da mesma borda e, se ainda não couber e foi o usuário
        que pediu (allow_float), fica solta (janela própria no meio da tela da janela); a janela volta ao
        tamanho de antes. Subjanela que o usuário não soltou nunca é solta aqui."""
        win = self.win
        if not win.isVisible():
            return
        self._auto = True
        try:
            for key in keys:
                if not self._too_big(before):
                    break
                d = self.docks[key]
                if d.isFloating() or d.isHidden():
                    continue
                area = win.dockWidgetArea(d)
                sibs = [o for k, o in self.docks.items() if o is not d and k != "barra" and o.isVisible()
                        and not o.isFloating() and win.dockWidgetArea(o) == area]
                bar = self.docks["barra"]
                if key == "faders" and bar.isVisible() and not bar.isFloating():
                    sibs.append(bar)            # os faders cabem na altura da barra de baixo: abas com ela
                for sib in sibs:
                    win.tabifyDockWidget(sib, d)
                    d.raise_()
                    if not self._too_big(before):
                        break
                if allow_float and self._too_big(before):
                    w, h = (FADERS_SIZE if key == "faders" else (d.width(), d.height()))
                    d.setFloating(True)
                    self._center_floating(d, max(w, 320), max(h, 200))
                    if notify:
                        msg = (f"Sem espaço para encaixar “{d.windowTitle()}” aqui: feche ou estreite outra "
                               "subjanela.")
                        if hasattr(win, "notify"):          # balão legível (a linha de status cortava)
                            win.notify(msg)
                        elif hasattr(win, "flash_status"):
                            win.flash_status(msg)
        finally:
            self._auto = False
        if win.size() != before and self._grown_from is None:
            self._grown_from = QSize(before)
        self._shrink_back()

    def _center_floating(self, d, w, h):
        """Subjanela solta com w x h (sem passar da tela), no meio da tela onde a janela está."""
        scr = self.win.screen() or QGuiApplication.primaryScreen()
        if scr is None:
            return
        g = scr.availableGeometry()
        m = d.minimumSizeHint()
        w = min(max(w, m.width()), g.width())
        h = min(max(h, m.height()), g.height())
        d.resize(w, h)
        d.move(QPoint(g.center().x() - w // 2, g.center().y() - h // 2))

    def set_page(self, name):
        """Trocou de aba: as subjanelas da Pad/Piano só aparecem nela (do jeito que o usuário deixou)."""
        if name != "pads" and self.page == "pads" and self.win.tabs.currentWidget() is self.win.pad_view:
            self._measure_pads()                     # saindo da Pad/Piano: guarda a largura mínima dela
        self.page = name
        before = self.win.size()
        self._guard = True
        try:
            for key in self.page_docks:
                self.docks[key].setVisible(self.user_visible[key] and name == "pads")
            for key, d in self.docks.items():
                if key not in self.page_docks and d.isHidden() == self.user_visible[key]:
                    d.setVisible(self.user_visible[key])
        finally:
            self._guard = False
        self._place_faders(self.docks["faders"].isVisible() or self.user_visible["faders"])
        for key, a in self.actions.items():
            a.setChecked(self.user_visible[key])
        if name == "pads":
            self._keep_size(self.page_docks, before)     # só abas (nunca solta sozinha)
            self._measure_pads()
        self._apply_floor()

    # ------------------------------------------------------------------ mínimo igual em todas as abas
    def _win_min(self):
        """Mínimo atual da janela (refazendo os caches dos layouts do centro até a janela)."""
        w = self.win.tabs
        while w is not None:
            w.updateGeometry()
            if w.layout() is not None:
                w.layout().invalidate()
            w = w.parentWidget()
        return self.win.minimumSizeHint()

    def _measure_pads(self):
        """Tamanho mínimo da janela com a tela Pad/Piano (e as subjanelas dela) na frente."""
        win, st = self.win, self.win.tabs
        if self.page != "pads" or not isValid(win):
            return
        cur = st.currentWidget()
        if cur is not win.pad_view:                  # mede sem trocar de verdade (sem sinais)
            st.blockSignals(True)
            QStackedWidget.setCurrentWidget(st, win.pad_view)
        try:
            self._pads_min = QSize(self._win_min())
        finally:
            if cur is not win.pad_view:
                QStackedWidget.setCurrentWidget(st, cur)
                st.blockSignals(False)
                self._win_min()

    def release_floor(self):
        """Tira o mínimo extra do centro (antes de algo que muda o mínimo: barra de baixo, subjanela)."""
        st = self.win.tabs
        if st.floor_w or st.floor_h:
            st.floor_w = st.floor_h = 0
            self._win_min()

    def _apply_floor(self):
        """Fora da Pad/Piano o centro ganha um mínimo para a janela nunca ficar menor do que a Pad/Piano
        precisa: estreitar (ou baixar) na Guitarra e voltar nunca falta espaço nem solta subjanelas."""
        win, st = self.win, self.win.tabs
        self.release_floor()
        if st.currentWidget() is win.pad_view or self._pads_min is None or not isValid(win):
            return
        for _ in range(4):                           # o mínimo da janela não é soma simples: ajusta
            m = self._win_min()
            miss_w = self._pads_min.width() - m.width()
            miss_h = self._pads_min.height() - m.height()
            if miss_w <= 0 and miss_h <= 0:
                break
            cur = st.minimumSizeHint()
            if miss_w > 0:
                st.floor_w = cur.width() + miss_w
            if miss_h > 0:
                st.floor_h = cur.height() + miss_h

    # ------------------------------------------------------------------ travar
    def set_locked(self, on):
        self.locked = bool(on)
        if self.action_lock is not None:
            self.action_lock.setChecked(self.locked)
        self._apply_lock()

    def _apply_lock(self):
        for key, d in self.docks.items():
            title = self.titles[key]
            title.set_buttons(not self.locked)
            if self.locked:
                d.setFeatures(QDockWidget.NoDockWidgetFeatures)
                # encaixada e travada: sem barra de título (como o OBS); solta continua com o nome, e a
                # que tem botões na barra (Setlist, Pad contínuo) fica com ela, só sem destacar/fechar
                keep = d.isFloating() or title.extras
                want = title if keep else self._no_title.setdefault(key, _NoTitle())
            else:
                d.setFeatures(FEATURES)
                want = title
            if d.titleBarWidget() is not want:
                d.setTitleBarWidget(want)
            for w in self.inner_heads.get(key, ()):
                w.setVisible(want is not title)         # sem barra: o título de dentro volta

    # ------------------------------------------------------------------ menu Exibir
    def build_menu(self, menu: QMenu):
        for key, title, _area, page in DOCKS:
            a = QAction(title, menu)
            a.setCheckable(True)
            a.setChecked(self.user_visible[key])
            if page:
                a.setToolTip("Aparece na tela Pad/Piano")
            a.triggered.connect(lambda on, k=key: self.set_visible(k, on))
            menu.addAction(a)
            self.actions[key] = a
        menu.addSeparator()
        lock = QAction("Travar subjanelas", menu)
        lock.setCheckable(True)
        lock.setChecked(self.locked)
        lock.setToolTip("Travadas: não dá para arrastar, destacar nem fechar (os divisores continuam ajustáveis)")
        lock.triggered.connect(self.set_locked)
        menu.addAction(lock)
        self.action_lock = lock
        restore = QAction("Restaurar layout padrão", menu)
        restore.triggered.connect(lambda *_: self.default_layout())
        menu.addAction(restore)
        self.action_restore = restore

    # ------------------------------------------------------------------ salvar / restaurar
    def save(self):
        return {"versao": LAYOUT_VERSION, "geometria": _b64(self.win.saveGeometry()),
                "estado": _b64(self.win.saveState(LAYOUT_VERSION)), "travado": self.locked,
                "visiveis": dict(self.user_visible), "altura_barra": int(self.win.dock.last_height)}

    def restore(self, data):
        """Layout salvo (ignorado se for de outra versão ou estiver estragado). -> True se aplicou."""
        if not isinstance(data, dict) or data.get("versao") != LAYOUT_VERSION:
            return False
        geom, state = _unb64(data.get("geometria", "")), _unb64(data.get("estado", ""))
        if geom is not None:
            self.win.restoreGeometry(geom)
        ok = False
        self._guard = True
        try:
            if state is not None:
                ok = self.win.restoreState(state, LAYOUT_VERSION)
            vis = data.get("visiveis")
            if isinstance(vis, dict):
                for key in self.user_visible:
                    if isinstance(vis.get(key), bool):
                        self.user_visible[key] = vis[key]
        finally:
            self._guard = False
        h = data.get("altura_barra")
        if isinstance(h, int) and not isinstance(h, bool) and DOCK_MIN <= h <= 4000:
            self.win.dock.last_height = h
        self.set_locked(data.get("travado") is True)
        self.bring_back_offscreen()
        self.set_page(self.page)
        self._setlist_folded(self.win.setlist.data["recolhido"])
        self._measure_pads()
        self._apply_floor()
        return ok

    # ------------------------------------------------------------------ Setlist recolhido
    def _setlist_folded(self, on):
        """Recolhido: a subjanela fica só com a barra (☰ e recolher) e o espaço vai para o Banco;
        expandido: volta à altura de antes."""
        win, d, sl = self.win, self.docks["setlist"], self.win.setlist
        if on:
            if d.isVisible() and not d.isFloating() and sl.maximumHeight() != 0:
                self._setlist_h = max(d.height(), 120)
            sl.setMaximumHeight(0)
            if d.isFloating():
                d.resize(d.width(), self._title_h(d) + 4)
        else:
            if sl.maximumHeight() == QWIDGETSIZE_MAX:
                return
            sl.setMaximumHeight(QWIDGETSIZE_MAX)
            h = self._setlist_h
            if d.isFloating():
                d.resize(d.width(), h)
            elif d.isVisible():
                QTimer.singleShot(0, lambda: isValid(win) and win.resizeDocks([d], [h], Qt.Vertical))

    def bring_back_offscreen(self):
        """Subjanela solta numa tela que não existe mais (2º monitor desligado): volta para a principal."""
        screens = QGuiApplication.screens()
        if not screens:
            return
        primary = QGuiApplication.primaryScreen().availableGeometry()
        for d in self.docks.values():
            if not d.isFloating():
                continue
            g = d.frameGeometry()
            if any(s.availableGeometry().intersects(g) for s in screens):
                continue
            w, h = min(g.width(), primary.width()), min(g.height(), primary.height())
            d.resize(w, h)
            d.move(QPoint(primary.center().x() - w // 2, primary.center().y() - h // 2))


class _GrowWatch(QObject):
    """Vê a janela principal crescer (o mínimo das subjanelas encaixadas passou do tamanho dela)."""

    def __init__(self, mgr):
        super().__init__(mgr.win)
        self.mgr = mgr

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize and obj is self.mgr.win:
            self.mgr._grew(ev.oldSize(), ev.size())
        return False


class _TitleBar(QWidget):
    """Barra de título da subjanela: nome, destacar (vira janela própria) e fechar."""

    def __init__(self, dock):
        super().__init__()
        self.dock = dock
        self.setObjectName("docktitle")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 3, 0)
        lay.setSpacing(2)
        self.lay = lay
        self.extras = []
        self.label = QLabel(dock.windowTitle())
        lay.addWidget(self.label, 1)
        self.float_btn = QToolButton()
        self.float_btn.setIcon(icon("upload", C["dim"], 12))
        self.float_btn.setToolTip("Destacar / encaixar (janela própria; dá para levar para outro monitor)")
        self.float_btn.setFocusPolicy(Qt.NoFocus)
        self.float_btn.clicked.connect(lambda *_: dock.setFloating(not dock.isFloating()))
        lay.addWidget(self.float_btn)
        self.close_btn = QToolButton()
        self.close_btn.setIcon(icon("close", C["dim"], 12))
        self.close_btn.setToolTip("Fechar (volta pelo menu Exibir)")
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.clicked.connect(lambda *_: dock.close())
        lay.addWidget(self.close_btn)

    def set_label(self, widget):
        """Usa outro texto como nome (ex.: o do Pad contínuo, que muda: "· segue o acorde")."""
        self.label.hide()
        self.label = widget
        self.lay.insertWidget(0, widget, 1)

    def add_extras(self, *widgets):
        """Botões do painel que passam a ficar na barra (antes do destacar/fechar)."""
        for w in widgets:
            self.lay.insertWidget(self.lay.indexOf(self.float_btn), w)
            self.extras.append(w)
        self.lay.insertSpacing(self.lay.indexOf(self.float_btn), 4)
        self.updateGeometry()

    def set_buttons(self, on):
        self.float_btn.setVisible(on)
        self.close_btn.setVisible(on)

    def _height(self):
        return max([18] + [min(w.maximumHeight(), max(w.minimumHeight(), w.sizeHint().height()))
                           for w in self.extras if not w.isHidden()])

    def sizeHint(self):
        return QSize(80, self._height())

    def minimumSizeHint(self):
        w = 40
        if self.extras:
            w = self.lay.minimumSize().width()
        return QSize(w, self._height())


class _NoTitle(QWidget):
    """Barra de título vazia (subjanela travada)."""

    def sizeHint(self):
        return QSize(0, 0)
