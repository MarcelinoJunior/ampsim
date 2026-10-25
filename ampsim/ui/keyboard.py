"""Teclado do PC como teclado musical (independente do layout: usa scancodes)."""
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QTextEdit

# Scancodes de teclado PC (set 1). Fileira A S D F... = teclas brancas, W E T Y U O P = pretas.
# Funciona igual em ABNT2 e US: no ABNT2 a tecla depois do L é o Ç.
SC_NOTES = {
    0x1E: 0, 0x11: 1, 0x1F: 2, 0x12: 3, 0x20: 4, 0x21: 5, 0x14: 6, 0x22: 7, 0x15: 8,
    0x23: 9, 0x16: 10, 0x24: 11, 0x25: 12, 0x18: 13, 0x26: 14, 0x19: 15, 0x27: 16,
}
SC_OCT_DOWN, SC_OCT_UP = 0x2C, 0x2D        # Z / X
SC_VEL_DOWN, SC_VEL_UP = 0x2E, 0x2F        # C / V

# Fallback por código de tecla (fora do Windows o scancode é diferente)
KEY_NOTES = {
    Qt.Key_A: 0, Qt.Key_W: 1, Qt.Key_S: 2, Qt.Key_E: 3, Qt.Key_D: 4, Qt.Key_F: 5, Qt.Key_T: 6,
    Qt.Key_G: 7, Qt.Key_Y: 8, Qt.Key_H: 9, Qt.Key_U: 10, Qt.Key_J: 11, Qt.Key_K: 12, Qt.Key_O: 13,
    Qt.Key_L: 14, Qt.Key_P: 15, Qt.Key_Semicolon: 16, Qt.Key_Ccedilla: 16,
}
KEY_CTRL = {Qt.Key_Z: "oct-", Qt.Key_X: "oct+", Qt.Key_C: "vel-", Qt.Key_V: "vel+"}
SC_CTRL = {SC_OCT_DOWN: "oct-", SC_OCT_UP: "oct+", SC_VEL_DOWN: "vel-", SC_VEL_UP: "vel+"}


class PcKeyboard(QObject):
    noteOn = Signal(int, int)
    noteOff = Signal(int)
    changed = Signal()          # oitava/velocidade mudaram

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True
        self.octave = 4         # tecla A = C4 (nota 60)
        self.velocity = 100
        self._held = {}         # tecla física -> nota que está soando

    @property
    def base_note(self):
        return 12 * (self.octave + 1)

    def _identify(self, e):
        sc = e.nativeScanCode()
        if sc in SC_NOTES:
            return sc, SC_NOTES[sc], None
        if sc in SC_CTRL:
            return sc, None, SC_CTRL[sc]
        k = e.key()
        if k in KEY_NOTES:
            return ("k", k), KEY_NOTES[k], None
        if k in KEY_CTRL:
            return ("k", k), None, KEY_CTRL[k]
        return None, None, None

    def eventFilter(self, obj, e):
        t = e.type()
        if t not in (QEvent.KeyPress, QEvent.KeyRelease) or not self.enabled:
            return False
        if e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            return False
        app = QApplication.instance()
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return False
        focus = app.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)) and not isinstance(focus.parent(), QAbstractSpinBox):
            return False                  # digitando texto (ex.: busca, nome de preset)
        ident, offset, ctrl = self._identify(e)
        if ident is None:
            return False                  # números/setas seguem para o campo (ex.: BPM)
        if e.isAutoRepeat():
            return True
        if t == QEvent.KeyPress:
            if offset is not None and ident not in self._held:
                note = self.base_note + offset
                if 0 <= note <= 127:
                    self._held[ident] = note
                    self.noteOn.emit(note, self.velocity)
            elif ctrl:
                self._control(ctrl)
        elif ident in self._held:
            self.noteOff.emit(self._held.pop(ident))
        return True

    def _control(self, ctrl):
        if ctrl == "oct-":
            self.octave = max(0, self.octave - 1)
        elif ctrl == "oct+":
            self.octave = min(8, self.octave + 1)
        elif ctrl == "vel-":
            self.velocity = max(10, self.velocity - 15)
        elif ctrl == "vel+":
            self.velocity = min(127, self.velocity + 15)
        self.changed.emit()

    def release_all(self):
        for note in self._held.values():
            self.noteOff.emit(note)
        self._held.clear()
