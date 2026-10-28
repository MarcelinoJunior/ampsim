"""Hospedagem de plugins VST3 (via pedalboard, da Spotify).

API (para quem for usar plugins numa parte nova do AmpSim, ex.: uma trilha nova):
 - PluginChain(fs, max_block, label): cadeia de até 4 plugins em série (o "FX" de uma camada, do Master,
   da Guitarra/Baixo). No áudio: chain.process(KB, n) com KB [n, 2] float64 intercalado, ou
   chain.process_lr(L, R, n) com dois arrays float64; chain.active diz se vale a pena chamar.
   Na interface: add/remove/move/clear, to_list()/apply(lista) para salvar/abrir (formato: lista de
   {"path", "state", "on", "mix"}; clean_chain aceita também o formato antigo de 1 slot),
   add_listener(fn) para saber quando algo mudou (fn é chamado em qualquer thread) e summary().
   A janela e o botão prontos estão em ui/plugin_slot.py (FxButton, FxChainWindow).
 - PluginSlot: um plugin (escolher, liga/desliga, Mix, painel). É o elemento da cadeia. Parâmetros internos
   (controlador MIDI, midi_map.py): param_list() e set_param(nome, 0..1), com coalescência.
 - VstSlot: o plugin no lugar do amp das trilhas Guitarra/Baixo (mono, entre o amp e o gabinete).

Threads (decisão importante). O JUCE, dentro do pedalboard, só aceita carregar, resetar e abrir o
painel de um plugin na "thread de mensagens", que é a primeira thread que carregou um plugin
(testado: carregar numa thread e abrir o painel em outra dá "Plugin UI windows can only be shown from
the main thread"). Por isso TODO contato com o JUCE (carregar, resetar, trocar a taxa, abrir o painel,
ler o estado, destruir) passa por uma única thread própria, a PluginHost. Resultado:
 - carregar um plugin lento não congela a interface (vai para a fila da thread dos plugins);
 - o painel do plugin roda o laço de mensagens dessa thread: o AmpSim continua usável com ele aberto;
 - a thread de áudio só chama process(reset=False), que o pedalboard aceita de qualquer thread.
Um painel aberto ocupa a thread dos plugins: carregar/trocar outro plugin fecha o painel antes.

Caminhos: nos arquivos salvos, um plugin das pastas padrão de VST3 vai como "vst3:Nome.vst3" (relativo
à pasta; procurado na pasta do usuário e na do sistema), para o preset abrir em outro PC que tenha o
mesmo plugin. Plugin de outra pasta vai pelo caminho completo e só abre neste PC.
"""
import base64
import binascii
import json
import os
import queue
import re
import threading
import traceback
from collections import deque
from time import perf_counter, sleep

import numpy as np
from numba import njit

try:
    import pedalboard
except ImportError:          # dependência opcional
    pedalboard = None


def _patch_pedalboard():
    """Ao criar um plugin, o pedalboard monta o cache de parâmetros num objeto Python provisório que fica
    num ciclo de referências segurando o plugin (C++) até o coletor de lixo passar: dezenas de MB presos a
    cada troca de plugin (medido: 131 -> 311 MB em 200 trocas). Sem valores iniciais (é o caso do AmpSim)
    não há o que aplicar: pula, e o cache só é montado no objeto de verdade, que é desfeito em _unlink."""
    try:
        mixin = pedalboard._pedalboard._PythonExternalPluginMixin
        orig = mixin.__set_initial_parameter_values__
    except AttributeError:
        return
    if getattr(orig, "_ampsim", False):
        return

    def set_initial(self, parameter_values):
        if not parameter_values:
            return None
        return orig(self, parameter_values)
    set_initial._ampsim = True
    mixin.__set_initial_parameter_values__ = set_initial


if pedalboard is not None:
    _patch_pedalboard()

JIT = dict(cache=True, fastmath=True, nogil=False, error_model="numpy")   # ver kernels.JIT
SYSTEM_VST3_DIR = os.path.join(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files"), "VST3")
MAX_STATE = 4_000_000          # estado salvo (base64) maior que isso não é guardado
SLOW_BLOCKS = 16               # blocos seguidos acima do prazo para desligar um plugin pesado demais
HUNG_S = 0.5                   # um bloco que demora isso desliga o plugin na hora
RETIRE_S = 0.5                 # plugins trocados esperam isso antes de serem destruídos (na thread deles)
IDLE_S = 0.25                  # sem bloco de áudio há esse tempo: o slot está parado (dá para "descarregar")
REF_PREFIX = "vst3:"           # plugin das pastas padrão salvo pelo caminho relativo
MAX_CHAIN = 4                  # plugins numa cadeia FX
NOT_A_PLUGIN = "Este arquivo não é um plugin de efeito VST3 que o AmpSim consiga abrir."


class PluginError(RuntimeError):
    """Mensagem para o usuário; `detail` guarda o erro técnico (mostrado só na dica)."""

    def __init__(self, msg, detail=""):
        super().__init__(msg)
        self.detail = detail


def available():
    return pedalboard is not None


# ------------------------------------------------------------------ pastas e lista de plugins
def user_vst3_dir():
    """Pasta de VST3 do usuário (gravável sem administrador): onde a tela de downloads instala."""
    base = os.environ.get("AMPSIM_USER_VST3_DIR")
    if base:
        return base
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Programs", "Common", "VST3")


def plugin_dirs():
    return [SYSTEM_VST3_DIR, user_vst3_dir()]


def display_name(path):
    """Nome para mostrar: "DragonflyRoomReverb.vst3" -> "Dragonfly Room Reverb"."""
    p = path or ""
    if p.startswith(REF_PREFIX):
        p = p[len(REF_PREFIX):]
    stem = os.path.splitext(os.path.basename(os.path.normpath(p.replace("/", os.sep))))[0] if p else ""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)


def find_plugins():
    """Plugins .vst3 instalados nas pastas padrão (do sistema e do usuário), incluindo uma subpasta
    por fabricante (VST3\\Fabricante\\Plugin.vst3), ordenados pelo nome."""
    seen, out = set(), []
    for root in plugin_dirs():
        if not os.path.isdir(root):
            continue
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            continue
        for f in entries:
            p = os.path.join(root, f)
            if f.startswith("."):
                continue                       # pasta temporária da tela de downloads
            if f.lower().endswith(".vst3"):
                cands = [p]
            elif os.path.isdir(p):
                try:
                    cands = [os.path.join(p, g) for g in sorted(os.listdir(p)) if g.lower().endswith(".vst3")]
                except OSError:
                    cands = []
            else:
                cands = []
            for c in cands:
                key = os.path.normcase(os.path.realpath(c))
                if key not in seen:
                    seen.add(key)
                    out.append(c)
    return sorted(out, key=lambda p: display_name(p).lower())


def bundle_of(path):
    """O binário de dentro de um pacote (X.vst3/Contents/x86_64-win/X.vst3) -> o pacote (X.vst3)."""
    p = os.path.normpath(path or "")
    parts = p.split(os.sep)
    if len(parts) >= 4 and parts[-2].lower() == "x86_64-win" and parts[-3].lower() == "contents" \
            and parts[-4].lower().endswith(".vst3"):
        return os.sep.join(parts[:-3])
    return path


def resolve_binary(path):
    """Um .vst3 no Windows costuma ser uma pasta (pacote); o pedalboard às vezes só consegue
    ler o binário de dentro dela (Contents/x86_64-win/*.vst3)."""
    if os.path.isdir(path):
        inner = os.path.join(path, "Contents", "x86_64-win")
        if os.path.isdir(inner):
            for f in sorted(os.listdir(inner)):
                if f.lower().endswith(".vst3"):
                    return os.path.join(inner, f)
    return path


# ------------------------------------------------------------------ caminho relativo às pastas padrão
def _norm(path):
    return os.path.normcase(os.path.realpath(path))


def _std_root(path):
    real = _norm(path)
    for r in (user_vst3_dir(), SYSTEM_VST3_DIR):
        if r and real.startswith(_norm(r) + os.sep):
            return r
    return None


def in_standard_dir(path):
    return bool(path) and not str(path).startswith(REF_PREFIX) and _std_root(path) is not None


def portable_ref(path):
    """Caminho para salvar: "vst3:Nome.vst3" se o plugin está numa pasta padrão; senão o caminho completo."""
    if not path or path.startswith(REF_PREFIX):
        return path or ""
    root = _std_root(path)
    if root is None:
        return path
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    return REF_PREFIX + rel.replace(os.sep, "/")


_STD_MARKERS = (os.sep + "common files" + os.sep + "vst3" + os.sep, os.sep + "common" + os.sep + "vst3" + os.sep)


def _safe_rel(rel):
    parts = [p for p in rel.replace("\\", "/").split("/")]
    if not parts or any(p in ("", ".", "..") or ":" in p for p in parts) or not parts[-1].lower().endswith(".vst3"):
        return None
    return parts


def resolve_ref(ref):
    """Caminho salvo -> caminho deste PC. "vst3:X.vst3" é procurado na pasta do usuário e na do sistema;
    caminho completo de outro PC numa pasta padrão (…\\Common\\VST3\\X.vst3) também. Não achou: devolve
    "vst3:…" (o slot mostra "não encontrado") ou o caminho como veio."""
    if not ref or not isinstance(ref, str):
        return ""
    if ref.startswith(REF_PREFIX):
        rel = ref[len(REF_PREFIX):]
    else:
        if os.path.exists(ref):
            return ref
        low = os.path.normcase(os.path.normpath(ref))
        i = max(low.rfind(m) for m in _STD_MARKERS)
        if i < 0:
            return ref
        mark = next(m for m in _STD_MARKERS if low.rfind(m) == i)
        rel = os.path.normpath(ref)[i + len(mark):]
    parts = _safe_rel(rel)
    if parts is None:
        return ref
    for root in (user_vst3_dir(), SYSTEM_VST3_DIR):
        p = os.path.join(root, *parts)
        if os.path.exists(p):
            return p
    return REF_PREFIX + "/".join(parts)


# ------------------------------------------------------------------ plugins escolhidos neste PC
def _app_file(name):
    from .. import storage
    return storage.APP_DIR / name


def _trusted_file():
    return _app_file("plugins_escolhidos.json")


def trusted_plugins():
    try:
        data = json.loads(_trusted_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []


def trust_plugin(path):
    """Lembra um plugin escolhido pelo usuário em "Procurar arquivo…" fora das pastas padrão: presets
    deste PC que usam esse plugin continuam abrindo com ele (ver is_local). Só depois de abrir."""
    if not path or path.startswith(REF_PREFIX) or in_standard_dir(path):
        return
    cur = trusted_plugins()
    if _norm(path) in {_norm(p) for p in cur}:
        return
    f = _trusted_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps((cur + [path])[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def is_local(path):
    """Plugin que existe neste PC numa pasta padrão de VST3 ou que o usuário já escolheu aqui.
    Presets compartilhados só trazem plugins assim (um caminho de outro PC nunca é carregado)."""
    path = resolve_ref(path) if isinstance(path, str) else ""
    if not path or path.startswith(REF_PREFIX) or not os.path.exists(path):
        return False
    if in_standard_dir(path):
        return True
    real = _norm(path)
    return any(_norm(p) == real for p in trusted_plugins())


# ------------------------------------------------------------------ plugins que não abrem (lembrados)
_bad_cache = None


def _bad_file():
    return _app_file("plugins_que_nao_abrem.json")


def _mtime(path):
    try:
        return os.path.getmtime(resolve_binary(path))
    except OSError:
        return 0.0


def _bad():
    global _bad_cache
    if _bad_cache is None:
        try:
            data = json.loads(_bad_file().read_text(encoding="utf-8"))
            _bad_cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _bad_cache = {}
    return _bad_cache


_RUN = f"{os.getpid()}-{perf_counter():.6f}"      # esta abertura do AmpSim


def bad_info(path):
    """(motivo, nesta_abertura): por que esse plugin não abriu e se foi nesta abertura do AmpSim ou numa
    anterior. ("", False) = não há registro, ou o arquivo mudou desde então. A lista de plugins mostra
    "(não abre)" para a falha de agora e "(não abriu da última vez)" para a de outra abertura: escolher o
    plugin sempre tenta abrir de novo (abrindo, a marca some)."""
    if not path:
        return "", False
    v = _bad().get(os.path.normcase(os.path.realpath(path)))
    if isinstance(v, list) and len(v) in (2, 3) and v[0] == _mtime(path):
        return str(v[1]), len(v) == 3 and v[2] == _RUN
    return "", False


def bad_reason(path):
    """Por que esse plugin não abriu da última vez ("" = não há registro, ou o arquivo mudou desde então)."""
    return bad_info(path)[0]


def forget_bad():
    """"Tentar de novo": esquece todos os plugins que não abriram (a lista volta a mostrá-los normais)."""
    d = _bad()
    if not d:
        return
    d.clear()
    try:
        _bad_file().write_text("{}", encoding="utf-8")
    except OSError:
        pass


def _set_bad(path, reason):
    d = _bad()
    key = os.path.normcase(os.path.realpath(path))
    if reason:
        d[key] = [_mtime(path), reason, _RUN]
    elif key in d:
        del d[key]
    else:
        return
    try:
        f = _bad_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def reset_caches():
    """Testes: esquece o cache dos plugins que não abrem (ele fica em storage.APP_DIR)."""
    global _bad_cache
    _bad_cache = None


# ------------------------------------------------------------------ carregar (thread dos plugins)
def _load_plugin(path):
    """pedalboard.load_plugin aceitando o pacote (pasta) ou o binário de dentro. Trocado nos testes.

    Tenta primeiro o binário de dentro do pacote: com o pacote, o pedalboard às vezes cria o plugin, falha
    ("scan failure") e deixa essa instância presa num ciclo (cache de parâmetros) até o coletor de lixo
    passar, com dezenas de MB a cada troca."""
    if pedalboard is None:
        raise PluginError("O módulo de plugins (pedalboard) não está instalado.", "pip install pedalboard")
    binary = resolve_binary(path)
    tries = [binary, path] if binary != path else [path]
    err = None
    for p in tries:
        try:
            return pedalboard.load_plugin(p)
        except ImportError as exc:
            # o pedalboard guarda os erros numa lista dentro do próprio quadro: limpa os quadros, senão o
            # ciclo segura objetos até o coletor de lixo passar
            traceback.clear_frames(exc.__traceback__)
            err = exc
    raise err


def load_effect(path):
    """Carrega um plugin de EFEITO. Recusa instrumentos (VSTi) com uma mensagem clara."""
    if not path or path.startswith(REF_PREFIX) or not os.path.exists(path):
        raise PluginError(f"plugin não encontrado: {display_name(path) or '?'}")
    detail = ""
    try:
        plugin = _load_plugin(path)
    except PluginError:
        raise
    except Exception as exc:  # noqa: BLE001 - ImportError/RuntimeError do pedalboard
        traceback.clear_frames(exc.__traceback__)
        lines = str(exc).strip().splitlines()
        detail = lines[-1].strip() if lines else exc.__class__.__name__
    if detail:
        raise PluginError(NOT_A_PLUGIN, detail)
    if getattr(plugin, "is_instrument", False) or not getattr(plugin, "is_effect", True):
        name = getattr(plugin, "name", "") or display_name(path)
        raise PluginError(f"“{name}” é um instrumento virtual (VSTi). Por enquanto o AmpSim só usa "
                          "plugins de efeito (reverb, delay, EQ, compressor…).")
    return plugin


def _accepts(plugin, ch, fs, max_block):
    try:
        plugin.process(np.zeros((ch, 64), np.float32), fs, buffer_size=max_block, reset=True)
        return True
    except Exception:  # noqa: BLE001 - erros vêm do plugin
        return False


def _unlink(plugin):
    """O pedalboard guarda no plugin um cache de parâmetros que apontam de volta para o plugin (ciclo):
    sem isto, cada plugin trocado (com dezenas de milhares de objetos) só sai da memória quando o coletor
    de lixo passa. Desfaz o ciclo para o plugin ser destruído na hora (na thread dos plugins)."""
    d = getattr(plugin, "__dict__", None)
    if isinstance(d, dict):
        for key in ("__python_parameter_cache__", "__python_to_cpp_names__", "_parameter_weakrefs"):
            d.pop(key, None)


class PluginHost:
    """A thread única que fala com o JUCE. Os trabalhos rodam em ordem; `call` espera o resultado."""

    def __init__(self):
        self._q = queue.SimpleQueue()
        self._thread = None
        self._lock = threading.Lock()
        self._retired = deque()
        self._editor = None              # threading.Event do painel aberto (set() fecha)
        self.editor_owner = None         # quem abriu o painel (PluginSlot/VstSlot)
        self.busy = False                # rodando um trabalho (carregar pode demorar)

    def _ensure(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="AmpSim-plugins", daemon=True)
                self._thread.start()

    def in_host(self):
        return threading.current_thread() is self._thread

    def post(self, fn):
        self._ensure()
        self._q.put(fn)

    def call(self, fn, timeout=30.0, close_editor=True):
        """Roda fn na thread dos plugins e devolve o resultado (fecha o painel aberto, que ocupa a thread)."""
        if self.in_host():
            return fn()
        if close_editor:
            self.close_editor()
        done = threading.Event()
        box = {}

        def job():
            try:
                box["v"] = fn()
            except BaseException as exc:  # noqa: BLE001 - devolvido para quem chamou
                box["e"] = exc
            finally:
                done.set()
        self.post(job)
        if not done.wait(timeout):
            raise PluginError(f"o plugin não respondeu em {timeout:.0f} s")
        if "e" in box:
            raise box.pop("e")
        return box.get("v")

    def retire(self, obj):
        """Guarda um plugin que saiu de uso para destruí-lo depois, na thread dos plugins (a thread de
        áudio pode estar terminando um bloco com ele). Pode ser chamado de qualquer thread."""
        if obj is not None:
            self._retired.append((perf_counter(), obj))

    def _sweep(self, force=False):
        now = perf_counter()
        while self._retired and (force or now - self._retired[0][0] >= RETIRE_S):
            _, obj = self._retired.popleft()
            _unlink(obj)
            obj = None


    def _run(self):
        while True:
            try:
                fn = self._q.get(timeout=0.25)
            except queue.Empty:
                fn = None
            if fn is not None:
                self.busy = True
                try:
                    fn()
                except Exception:  # noqa: BLE001 - um trabalho com erro não para a thread
                    traceback.print_exc()
                finally:
                    self.busy = False
                fn = None
            self._sweep()

    # ------------------------------------------------------------------ painel do plugin
    @property
    def editor_open(self):
        return self._editor is not None

    def open_editor(self, plugin, owner=None, on_closed=None):
        """Abre o painel (janela própria do plugin) sem travar o AmpSim. on_closed(erro) é chamado na
        thread dos plugins quando o painel fecha."""
        self.close_editor()
        ev = threading.Event()

        def job():
            self._editor, self.editor_owner = ev, owner
            err = ""
            try:
                if not ev.is_set():
                    plugin.show_editor(ev)
            except Exception as exc:  # noqa: BLE001
                err = str(exc) or exc.__class__.__name__
            finally:
                if self._editor is ev:
                    self._editor, self.editor_owner = None, None
            if on_closed is not None:
                on_closed(err)
        self.post(job)

    def close_editor(self):
        ev = self._editor
        if ev is not None:
            ev.set()

    def shutdown(self):
        """Fecha o painel e destrói os plugins aposentados (ao fechar o AmpSim)."""
        self.close_editor()
        if self._thread is not None and self._thread.is_alive():
            try:
                self.call(lambda: self._sweep(force=True), timeout=5.0)
            except PluginError:
                pass


_HOST = PluginHost()


def host():
    return _HOST


# ------------------------------------------------------------------ kernels (thread de áudio, sem alocar)
@njit(**JIT)
def _to_planar(KB, buf, n):
    """KB [n, 2] (float64, intercalado) -> buf [2, n] (float32, um canal por linha)."""
    for i in range(n):
        buf[0, i] = KB[i, 0]
        buf[1, i] = KB[i, 1]


@njit(**JIT)
def _lr_to_planar(L, R, buf, n):
    for i in range(n):
        buf[0, i] = L[i]
        buf[1, i] = R[i]


@njit(**JIT)
def _mix_back(KB, wl, wr, n, mix):
    """Seco/molhado no lugar: KB = KB*(1-mix) + saída*mix. Se o plugin devolveu menos amostras (latência
    no começo), a saída fica alinhada ao fim do bloco. -> False se veio NaN/inf (amostra zerada)."""
    dry = 1.0 - mix
    ml = min(wl.shape[0], n)
    mr = min(wr.shape[0], n)
    ok = True
    for i in range(n):
        jl = i - (n - ml)
        jr = i - (n - mr)
        a = wl[jl] if jl >= 0 else 0.0
        b = wr[jr] if jr >= 0 else 0.0
        if not (abs(a) < 1e6 and abs(b) < 1e6):
            ok = False
            a = 0.0
            b = 0.0
        KB[i, 0] = KB[i, 0] * dry + a * mix
        KB[i, 1] = KB[i, 1] * dry + b * mix
    return ok


@njit(**JIT)
def _mix_back_lr(L, R, wl, wr, n, mix):
    dry = 1.0 - mix
    ml = min(wl.shape[0], n)
    mr = min(wr.shape[0], n)
    ok = True
    for i in range(n):
        jl = i - (n - ml)
        jr = i - (n - mr)
        a = wl[jl] if jl >= 0 else 0.0
        b = wr[jr] if jr >= 0 else 0.0
        if not (abs(a) < 1e6 and abs(b) < 1e6):
            ok = False
            a = 0.0
            b = 0.0
        L[i] = L[i] * dry + a * mix
        R[i] = R[i] * dry + b * mix
    return ok


@njit(**JIT)
def _mix_back_mono(x, w, n, mix):
    dry = 1.0 - mix
    m = min(w.shape[0], n)
    ok = True
    for i in range(n):
        j = i - (n - m)
        a = w[j] if j >= 0 else 0.0
        if not abs(a) < 1e6:
            ok = False
            a = 0.0
        x[i] = x[i] * dry + a * mix
    return ok


@njit(**JIT)
def mono_to_stereo(src, KB, n):
    """src [n, 1] (float32) -> KB [n, 2] com o mesmo sinal nos dois lados."""
    for i in range(n):
        v = src[i, 0]
        KB[i, 0] = v
        KB[i, 1] = v


@njit(**JIT)
def stereo_to_mono(KB, dst, n, add):
    """KB [n, 2] -> dst [n, 1]: média dos dois lados (o caminho de destino é mono). add: soma em dst."""
    for i in range(n):
        v = (KB[i, 0] + KB[i, 1]) * 0.5
        if add:
            dst[i, 0] += v
        else:
            dst[i, 0] = v


def warmup():
    kb = np.zeros((8, 2))
    buf = np.zeros((2, 8), np.float32)
    _to_planar(kb, buf, 8)
    _lr_to_planar(np.zeros(8), np.zeros(8), buf, 8)
    _mix_back(kb, buf[0], buf[1], 8, 0.5)
    _mix_back_lr(np.zeros(8), np.zeros(8), buf[0], buf[1], 8, 0.5)
    _mix_back_mono(np.zeros(8), buf[0], 8, 0.5)
    so = np.zeros((8, 1), np.float32)
    mono_to_stereo(so, kb, 8)
    stereo_to_mono(kb, so, 8, True)
    stereo_to_mono(kb, so, 8, False)


def _b64_state(plugin):
    try:
        return base64.b64encode(plugin.raw_state).decode("ascii")
    except Exception:  # noqa: BLE001
        return ""


def _set_b64_state(plugin, b64):
    if b64:
        plugin.raw_state = base64.b64decode(b64)


def valid_state(s, limit=MAX_STATE):
    """Estado de plugin vindo de arquivo: texto base64 de tamanho razoável."""
    if not isinstance(s, str) or len(s) > limit:
        return False
    try:
        base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        return False
    return True


# ------------------------------------------------------------------ slot mono (trilhas Guitarra/Baixo)
# ------------------------------------------------------------------ parâmetros internos do plugin
try:                                             # "MIDI CC 0|1", "Program"... que o VST3 do JUCE expõe à toa
    from pedalboard._pedalboard import PARAMETER_NAME_REGEXES_TO_IGNORE as _IGNORE_PARAMS
except Exception:  # noqa: BLE001
    _IGNORE_PARAMS = ()


def _plugin_params(plugin):
    """Parâmetros (objetos com .name e .raw_value 0..1) de um plugin. Usa a lista crua do pedalboard
    (`_parameters`, rápida): o dicionário `parameters` dele mede a faixa de cada parâmetro (1000 passos
    de texto cada) e demora segundos num plugin grande."""
    ps = getattr(plugin, "_parameters", None)
    if ps is None:
        d = getattr(plugin, "parameters", None)
        ps = list(d.values()) if isinstance(d, dict) or hasattr(d, "values") else []
    out = []
    for p in ps:
        name = str(getattr(p, "name", "") or "")
        if not name or any(r.match(name) for r in _IGNORE_PARAMS):
            continue
        out.append(p)
    return out


def _param_index(inst, plugin):
    """{nome: parâmetro} de uma instância carregada (guardado no _Loaded)."""
    cache = inst.__dict__.setdefault("_pcache", {})
    key = id(plugin)
    if key not in cache:
        cache[key] = {str(p.name): p for p in _plugin_params(plugin)}
    return cache[key]


def _read_params(plugin):
    out = []
    for p in _plugin_params(plugin):
        try:
            raw = float(p.raw_value)
        except Exception:  # noqa: BLE001
            continue
        text = ""
        try:
            text = str(p.get_text_for_raw_value(raw)) if hasattr(p, "get_text_for_raw_value") else ""
        except Exception:  # noqa: BLE001
            text = ""
        label = str(getattr(p, "label", "") or "")
        out.append(dict(name=str(p.name), raw=raw, text=text.strip(), label=label))
    return out


class VstSlot:
    """Plugin no lugar do amp de uma trilha (sinal mono). Carregado na thread dos plugins (espera)."""

    def __init__(self, path, fs, max_block):
        path = resolve_ref(path)
        self.path = path
        self.fs = float(fs)
        self.max_block = int(max_block)
        self.error = None

        def make():
            plugin = load_effect(path)
            # mono se o plugin aceitar; senão manda o sinal duplicado em estéreo
            ch = 1 if _accepts(plugin, 1, self.fs, self.max_block) else 2
            if ch == 2 and not _accepts(plugin, 2, self.fs, self.max_block):
                raise PluginError(NOT_A_PLUGIN, "o plugin não aceita áudio mono nem estéreo")
            return plugin, ch
        self.plugin, self.channels = host().call(make)
        self.name = getattr(self.plugin, "name", "") or display_name(path)
        self.buf = np.zeros((self.channels, self.max_block), np.float32)

    def __del__(self):
        try:
            host().retire(self.plugin)
        except Exception:  # noqa: BLE001 - fechando o programa
            pass

    def process(self, x, n, mix):
        """Thread de áudio. Em caso de erro, desativa o slot em vez de derrubar o stream."""
        if self.error:
            return
        b = self.buf[:, :n]
        b[:] = x[:n]
        try:
            out = self.plugin.process(b, self.fs, buffer_size=self.max_block, reset=False)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc) or exc.__class__.__name__
            return
        # plugin só estéreo: média dos dois lados de volta para o caminho mono da trilha
        y = out[0] if out.shape[0] == 1 else out.mean(axis=0)
        if not _mix_back_mono(x, y, n, mix):
            self.error = "o plugin gerou som inválido"

    def reset(self):
        """Zera o plugin (stream parado). Na thread dos plugins."""
        self.error = None
        try:
            host().call(self.plugin.reset, timeout=5.0)
        except Exception:  # noqa: BLE001
            pass

    def get_state(self):
        return _b64_state(self.plugin)

    def set_state(self, b64):
        _set_b64_state(self.plugin, b64)

    def show_editor(self, on_closed=None):
        """Abre o painel do plugin sem travar o AmpSim (o áudio continua)."""
        host().open_editor(self.plugin, self, on_closed)


# ------------------------------------------------------------------ slot estéreo (elemento da cadeia)
class _Loaded:
    """Instância(s) carregada(s) de um plugin: uma (estéreo) ou duas (plugin mono: uma por lado)."""

    def __init__(self, path, fs, max_block):
        first = load_effect(path)
        self.path = path
        self.name = getattr(first, "name", "") or display_name(path)
        if _accepts(first, 2, fs, max_block):
            self.plugins = (first,)
        elif _accepts(first, 1, fs, max_block):
            second = load_effect(path)          # mono: uma cópia por lado, sem somar L+R
            if not _accepts(second, 1, fs, max_block):
                raise PluginError(NOT_A_PLUGIN, "plugin mono: não deu para abrir a cópia do lado direito")
            self.plugins = (first, second)
        else:
            raise PluginError(NOT_A_PLUGIN, "o plugin não aceita áudio estéreo nem mono")

    @property
    def stereo(self):
        return len(self.plugins) == 1

    def get_state(self):
        return _b64_state(self.plugins[0])

    def set_state(self, b64):
        for p in self.plugins:
            _set_b64_state(p, b64)

    def prepare(self, fs, max_block):
        ch = 2 if self.stereo else 1
        for p in self.plugins:
            p.process(np.zeros((ch, 64), np.float32), fs, buffer_size=max_block, reset=True)

    def flush(self, fs, max_block):
        """Um bloco curto de silêncio sem resetar: o pedalboard só passa ao plugin os parâmetros mexidos
        (no painel) quando processa, e só então o estado salvo (raw_state) muda."""
        ch = 2 if self.stereo else 1
        for p in self.plugins:
            p.process(np.zeros((ch, 32), np.float32), fs, buffer_size=max_block, reset=False)

    def reset(self):
        for p in self.plugins:
            p.reset()

    def __del__(self):
        try:
            for p in getattr(self, "plugins", ()):
                host().retire(p)
        except Exception:  # noqa: BLE001
            pass


EMPTY_PLUGIN = dict(path="", state="", on=False, mix=100)


def clean_plugin(d, state_limit=MAX_STATE):
    """Configuração de slot vinda de arquivo (sessão, preset): só chaves e tipos conhecidos."""
    out = dict(EMPTY_PLUGIN)
    if not isinstance(d, dict):
        return out
    if isinstance(d.get("path"), str) and len(d["path"]) <= 1024:
        out["path"] = d["path"]
    if valid_state(d.get("state", ""), state_limit):
        out["state"] = d.get("state", "")
    if isinstance(d.get("on"), bool):
        out["on"] = d["on"]
    m = d.get("mix")
    if isinstance(m, (int, float)) and not isinstance(m, bool) and m == m:
        out["mix"] = max(0.0, min(100.0, float(m)))
        if out["mix"] == int(out["mix"]):
            out["mix"] = int(out["mix"])
    if not out["path"]:
        out["state"] = ""
    return out


def clean_chain(v, state_limit=MAX_STATE):
    """Cadeia vinda de arquivo: lista de slots (sem os vazios), até MAX_CHAIN. Aceita também o formato
    antigo de um slot só (um dicionário)."""
    if isinstance(v, dict):
        v = [v]
    if not isinstance(v, list):
        return []
    out = [clean_plugin(d, state_limit) for d in v[:MAX_CHAIN] if isinstance(d, dict)]
    return [d for d in out if d["path"]]


class PluginSlot:
    """Um plugin: escolher, liga/desliga, Mix e painel. Elemento de uma PluginChain.

    Desejado (o que a interface mostra e o que é salvo): path, state, on, mix. A thread de áudio só lê
    `inst` (trocado de uma vez, na thread dos plugins) e `_live`. Erro no plugin desliga só este slot
    (`run_error`); erro ao carregar (não encontrado, VSTi, arquivo que não é plugin) fica em `load_error`
    (detalhe técnico em `load_detail`)."""

    def __init__(self, fs, max_block, label=""):
        self.fs = float(fs)
        self.max_block = int(max_block)
        self.label = label
        self.path = ""                 # caminho neste PC (ou "vst3:…" quando não foi encontrado)
        self.state = ""                # último estado conhecido (base64), mesmo sem o plugin carregado
        self.on = False
        self.mix = 1.0
        self.inst = None               # _Loaded em uso
        self.load_error = ""
        self.load_detail = ""
        self.missing = False           # o arquivo do plugin sumiu do disco (ou não existe neste PC)
        self.run_error = ""
        self.loading = False
        self._live = False             # a thread de áudio processa (on e carregado e sem erro)
        self._hold = False             # a thread dos plugins está usando o plugin: o áudio pula este slot
        self._in_proc = False          # a thread de áudio está dentro do plugin
        self._last_proc = 0.0          # último bloco processado pelo áudio (perf_counter)
        self._gen = 0
        self._slow = 0
        self._buf = np.zeros((2, self.max_block), np.float32)
        self._idle = threading.Event()
        self._idle.set()
        self._plock = threading.Lock()
        self._pparams = {}             # parâmetros internos esperando a thread dos plugins (nome -> 0..1)
        self._pposted = False
        self.on_change = lambda: None  # chamado na thread dos plugins ou na da interface

    # ------------------------------------------------------------------ estado
    @property
    def name(self):
        return self.inst.name if self.inst is not None else display_name(self.path)

    @property
    def active(self):
        """Vai processar no próximo bloco (para o motor decidir o caminho do som)."""
        return self.inst is not None and self._live and self.mix > 0.0

    def status(self):
        """Texto curto para a interface."""
        if not self.path:
            return "Nenhum plugin"
        if self.loading:
            return f"Carregando “{self.name}”…"
        if self.missing:
            return f"Plugin não encontrado: {self.name} (instale de novo ou escolha outro)"
        if self.load_error:
            return self.load_error
        if self.run_error:
            return f"Plugin desligado após erro: {self.run_error} (ligue de novo para tentar)"
        if self.inst is None:
            return self.name
        kind = "estéreo" if self.inst.stereo else "mono (uma cópia por lado)"
        return f"{self.name} · {kind}" + ("" if self.on else " · desligado")

    @property
    def ok(self):
        return self.inst is not None and not (self.load_error or self.run_error or self.loading)

    @property
    def failed(self):
        return bool(self.path) and bool(self.load_error or self.run_error or self.missing)

    def _read_state(self, inst):
        """Na thread dos plugins: estado atual do plugin. Se o áudio não está passando por ele (parado,
        slot desligado, Mix 0), processa antes um bloco curto de silêncio para o plugin receber o que foi
        mexido no painel (o áudio pula o slot nesse instante; nada é processado ao mesmo tempo)."""
        if perf_counter() - self._last_proc > IDLE_S:
            self._hold = True
            try:
                t0 = perf_counter()
                while self._in_proc and perf_counter() - t0 < 1.0:
                    sleep(0.0005)
                inst.flush(self.fs, self.max_block)
            except Exception:  # noqa: BLE001 - plugin que não aceita: fica o estado de antes
                pass
            finally:
                self._hold = False
        return inst.get_state()

    def to_dict(self):
        inst = self.inst
        if inst is not None and inst.path == self.path:
            h = host()
            if h.in_host():
                st = self._read_state(inst)
            elif h.editor_open or h.busy or self.loading:
                st = inst.get_state()            # thread dos plugins ocupada (painel aberto, carregando)
            else:
                try:
                    st = h.call(lambda: self._read_state(inst), timeout=1.0, close_editor=False)
                except Exception:  # noqa: BLE001 - plugin travado: fica o último estado conhecido
                    st = ""
            if st:
                self.state = st
        mix = round(self.mix * 100.0, 1)
        return dict(path=portable_ref(self.path), state=self.state if self.path else "", on=self.on,
                    mix=int(mix) if mix == int(mix) else mix)

    def apply(self, d, wait=False):
        """Aplica uma configuração salva (limpa por clean_plugin). Não recarrega o mesmo plugin."""
        d = clean_plugin(d)
        path = resolve_ref(d["path"])
        self.set_mix(d["mix"])
        same = path == self.path and (self.inst is not None or self.loading)
        self.on = d["on"]
        if same:
            if d["state"] and d["state"] != self.to_dict()["state"]:
                self.load(path, d["state"], wait=wait)
            else:
                self.set_on(d["on"], wait=wait)
            return
        self.load(path, d["state"], wait=wait)

    def clear(self):
        self.load("")
        self.on = False
        self.mix = 1.0

    def set_mix(self, value, wait=False):
        """Mix 0-100 (0 = sem efeito, 100 = só o plugin). Saindo do 0 o plugin é zerado antes: a cauda
        parada desde que o Mix foi a 0 não toca."""
        new = max(0.0, min(1.0, float(value) / 100.0))
        if self.mix <= 0.0 < new and self.inst is not None and self._live:
            self._live = False
            self.mix = new
            self._restart(wait)
            return
        self.mix = new

    def set_on(self, on, wait=False):
        self.on = bool(on)
        if not self.on:
            self._live = False
            self.on_change()
            return
        if self.inst is None:
            self.on_change()
            return
        self._restart(wait)

    def _restart(self, wait=False):
        """Zera o plugin na thread dos plugins e volta a processar (religar, sair do Mix 0, após erro)."""
        gen = self._gen
        inst = self.inst

        def job():
            if gen != self._gen or self.inst is not inst or not self.on:
                return
            self._live = False
            try:
                inst.reset()                    # sem a cauda antiga presa no plugin
            except Exception:  # noqa: BLE001
                pass
            self.run_error = ""
            self._slow = 0
            self._live = self.on and not self.load_error
            self.on_change()
        self._run(job, wait)

    # ------------------------------------------------------------------ carregar / trocar
    def load(self, path, state="", wait=False, trust=False):
        """Escolhe o plugin ("" tira). Carrega na thread dos plugins; a troca é atômica. trust: escolhido
        em "Procurar arquivo…" (lembrado só se abrir)."""
        path = resolve_ref(path or "")
        self._gen += 1
        gen = self._gen
        self.path = path
        self.state = state or ""
        self.run_error = ""
        self.load_error = ""
        self.load_detail = ""
        self.missing = False
        self._slow = 0
        if not path or path.startswith(REF_PREFIX) or not os.path.exists(path):
            if host().editor_owner is self:
                host().close_editor()       # o painel aberto era do plugin que saiu
            old, self.inst, self._live = self.inst, None, False
            host().retire(old)
            old = None
            self.loading = False
            if path:
                self.missing = True
            self.on_change()
            return
        self.loading = True
        self._live = False
        host().close_editor()            # o painel aberto ocupa a thread dos plugins

        def job():
            if gen != self._gen:
                return
            cur = self.inst
            new = None
            try:
                if cur is not None and cur.path == path:
                    new = cur                  # mesmo plugin: só troca o estado
                else:
                    new = _Loaded(path, self.fs, self.max_block)
                if state:
                    try:
                        new.set_state(state)
                    except Exception:  # noqa: BLE001 - estado de outra versão do plugin
                        pass
                new.prepare(self.fs, self.max_block)
            except Exception as exc:  # noqa: BLE001
                traceback.clear_frames(exc.__traceback__)
                if gen == self._gen:
                    old, self.inst, self._live = self.inst, None, False
                    host().retire(old)
                    if isinstance(exc, PluginError):
                        self.load_error, self.load_detail = str(exc), exc.detail
                    else:
                        self.load_error, self.load_detail = NOT_A_PLUGIN, str(exc) or exc.__class__.__name__
                    if not str(exc).startswith("plugin não encontrado"):
                        _set_bad(path, self.load_error)
                    self.loading = False
                    self.on_change()
                return
            if gen != self._gen:
                if new is not cur:
                    host().retire(new)
                return
            self.inst = new
            if cur is not new:
                host().retire(cur)
            cur = new = None
            if bad_reason(path):
                _set_bad(path, "")
            if trust:
                trust_plugin(path)
            self.loading = False
            self._live = self.on
            self.on_change()
        self._run(job, wait)

    def set_fs(self, fs):
        """Nova taxa de amostragem (stream parado): prepara o plugin na thread dele e espera."""
        self.fs = float(fs)
        inst = self.inst
        if inst is None:
            return
        try:
            host().call(lambda: inst.prepare(self.fs, self.max_block), timeout=10.0)
        except Exception as exc:  # noqa: BLE001
            self.run_error = str(exc) or exc.__class__.__name__
            self._live = False

    def _run(self, job, wait):
        self._idle.clear()

        def wrapped():
            try:
                job()
            finally:
                self._idle.set()
        if wait:
            host().call(wrapped)
        else:
            host().post(wrapped)

    def wait(self, timeout=30.0):
        """Espera os trabalhos pendentes deste slot (testes)."""
        host().call(lambda: None, timeout=timeout)
        return self._idle.wait(timeout)

    # ------------------------------------------------------------------ painel do plugin
    def show_editor(self, on_closed=None):
        """Abre o painel do plugin numa janela própria; o AmpSim continua usável (ver o topo do arquivo).
        -> False se não há plugin carregado."""
        inst = self.inst
        if inst is None:
            return False

        def closed(err):
            try:
                st = self._read_state(inst)       # guarda o que foi mexido no painel
                if st and self.inst is inst:
                    self.state = st
                if len(inst.plugins) > 1 and st:  # plugin mono: o lado direito copia o painel
                    _set_b64_state(inst.plugins[1], st)
            except Exception:  # noqa: BLE001
                pass
            if on_closed is not None:
                on_closed(err)
            self.on_change()
        host().open_editor(inst.plugins[0], self, closed)
        return True

    @property
    def editor_open(self):
        return host().editor_owner is self

    # ------------------------------------------------------------------ parâmetros internos (controlador MIDI)
    def param_list(self, timeout=2.0):
        """Parâmetros do plugin carregado: [dict(name, raw (0..1), text, label)] ou [] (sem plugin).
        Lidos na thread dos plugins; com o painel aberto (ela fica ocupada) ou se ela não responder, lê
        direto (só leituras)."""
        inst = self.inst
        if inst is None:
            return []
        h = host()
        if h.in_host() or h.editor_open or h.busy:
            return _read_params(inst.plugins[0])
        try:
            return h.call(lambda: _read_params(inst.plugins[0]), timeout=timeout, close_editor=False)
        except Exception:  # noqa: BLE001 - plugin travado: lista vazia (a tela avisa)
            return []

    def set_param(self, name, raw):
        """Muda um parâmetro interno do plugin (raw 0..1), ex.: girando um knob mapeado do controlador.
        Vai para a thread dos plugins com coalescência (um knob girando não enche a fila: só o último valor
        de cada parâmetro é aplicado). Com o painel do plugin aberto a thread dos plugins está presa no laço
        do painel: aí aplica direto — no VST3 do JUCE o setValue do parâmetro só grava um valor atômico e
        avisa o painel pela fila de mensagens dele (é o caminho de automação, feito para qualquer thread).
        -> False se não há plugin carregado (mapeamento inativo)."""
        if self.inst is None or self.loading:
            return False
        with self._plock:
            self._pparams[str(name)] = min(max(float(raw), 0.0), 1.0)
            posted, self._pposted = self._pposted, True
        h = host()
        if h.in_host() or h.editor_open:
            self._flush_params()
        elif not posted:
            h.post(self._flush_params)
        return True

    def _flush_params(self):
        with self._plock:
            items, self._pparams = self._pparams, {}
            self._pposted = False
        inst = self.inst
        if inst is None or not items:
            return
        for p in inst.plugins:                       # plugin mono: as duas cópias recebem o valor
            cache = _param_index(inst, p)
            for name, raw in items.items():
                par = cache.get(name)
                if par is not None:
                    try:
                        par.raw_value = raw
                    except Exception:  # noqa: BLE001 - parâmetro que o plugin recusa: ignora
                        pass

    def param_value(self, name):
        """Valor atual (0..1) de um parâmetro interno, ou None (leitura direta, para a tela)."""
        inst = self.inst
        if inst is None:
            return None
        par = _param_index(inst, inst.plugins[0]).get(name)
        try:
            return float(par.raw_value) if par is not None else None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ áudio (tempo real)
    def _plugin_out(self, inst, n):
        """Thread de áudio: roda o plugin sobre self._buf[:, :n]. -> (saída L, saída R) ou None (erro)."""
        fs = self.fs
        buf = self._buf
        t0 = perf_counter()
        self._last_proc = t0
        try:
            ps = inst.plugins
            if len(ps) == 1:
                out = ps[0].process(buf[:, :n], fs, buffer_size=self.max_block, reset=False)
                wl = out[0]
                wr = out[1] if out.shape[0] > 1 else out[0]
            else:
                wl = ps[0].process(buf[0:1, :n], fs, buffer_size=self.max_block, reset=False)[0]
                wr = ps[1].process(buf[1:2, :n], fs, buffer_size=self.max_block, reset=False)[0]
        except Exception as exc:  # noqa: BLE001 - erro do plugin: desliga só este slot
            self._live = False
            self.run_error = str(exc) or exc.__class__.__name__
            return None
        dt = perf_counter() - t0               # só o plugin (sem a cópia/mistura)
        if dt > HUNG_S:
            self._live = False
            self.run_error = f"o plugin travou o áudio ({dt * 1000:.0f} ms num bloco)"
        elif dt > n / fs:
            self._slow += 1
            if self._slow >= SLOW_BLOCKS:
                self._live = False
                self.run_error = "o plugin está pesado demais para este buffer (desligado para não picotar)"
        else:
            self._slow = 0
        return wl, wr

    def process(self, KB, n):
        """Thread de áudio: processa KB [n, 2] (float64) no lugar. Nada de carregar ou de esperar aqui;
        o pedalboard devolve um array novo por bloco (alocação pequena dele, inevitável)."""
        inst = self.inst
        if inst is None or not self._live or self.mix <= 0.0:
            return
        self._in_proc = True
        try:
            if self._hold:
                return
            _to_planar(KB, self._buf, n)
            w = self._plugin_out(inst, n)
            if w is not None and not _mix_back(KB, w[0], w[1], n, self.mix):
                self._live = False
                self.run_error = "o plugin gerou som inválido"
        finally:
            self._in_proc = False

    def process_lr(self, L, R, n):
        """Como process, com os dois lados em arrays separados (fim da cadeia de uma trilha)."""
        inst = self.inst
        if inst is None or not self._live or self.mix <= 0.0:
            return
        self._in_proc = True
        try:
            if self._hold:
                return
            _lr_to_planar(L, R, self._buf, n)
            w = self._plugin_out(inst, n)
            if w is not None and not _mix_back_lr(L, R, w[0], w[1], n, self.mix):
                self._live = False
                self.run_error = "o plugin gerou som inválido"
        finally:
            self._in_proc = False


# ------------------------------------------------------------------ cadeia (o "FX")
class PluginChain:
    """Até MAX_CHAIN plugins em série. `slots` é uma tupla trocada de uma vez (a thread de áudio só lê)."""

    def __init__(self, fs, max_block, label=""):
        self.fs = float(fs)
        self.max_block = int(max_block)
        self.label = label
        self.slots = ()
        self._listeners = []

    # ------------------------------------------------------------------ avisos
    def add_listener(self, fn):
        if fn not in self._listeners:
            self._listeners.append(fn)

    def remove_listener(self, fn):
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _notify(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:  # noqa: BLE001 - um aviso quebrado não para os outros
                traceback.print_exc()

    # ------------------------------------------------------------------ montar a cadeia
    def _new_slot(self):
        s = PluginSlot(self.fs, self.max_block, self.label)
        s.on_change = self._notify
        return s

    def add(self, path="", state="", on=True, mix=100, wait=False, trust=False):
        """Novo plugin no fim da cadeia (path "" = slot vazio para escolher). -> o slot ou None (cheia)."""
        if len(self.slots) >= MAX_CHAIN:
            return None
        s = self._new_slot()
        s.on = bool(on)
        s.set_mix(mix)
        self.slots = self.slots + (s,)
        if path:
            s.load(path, state, wait=wait, trust=trust)
        self._notify()
        return s

    def remove(self, i):
        if not 0 <= i < len(self.slots):
            return
        gone = self.slots[i]
        self.slots = self.slots[:i] + self.slots[i + 1:]
        gone.clear()
        self._notify()

    def move(self, i, delta):
        j = i + delta
        if not (0 <= i < len(self.slots) and 0 <= j < len(self.slots)):
            return
        s = list(self.slots)
        s.insert(j, s.pop(i))               # leva o plugin i para a posição j
        self.slots = tuple(s)
        self._notify()

    def clear(self):
        old, self.slots = self.slots, ()
        for s in old:
            s.clear()
        if old:
            self._notify()

    def apply(self, data, wait=False):
        """Abre uma cadeia salva (lista de slots; também o formato antigo de 1 slot). Reaproveita os
        plugins já carregados na mesma posição."""
        items = clean_chain(data)
        cur = list(self.slots)
        new = []
        for i, d in enumerate(items):
            s = cur[i] if i < len(cur) else self._new_slot()
            s.apply(d, wait=wait)
            new.append(s)
        extra = cur[len(items):]
        self.slots = tuple(new)
        for s in extra:
            s.clear()
        self._notify()

    def to_list(self):
        return [s.to_dict() for s in self.slots if s.path]

    def set_fs(self, fs):
        self.fs = float(fs)
        for s in self.slots:
            s.set_fs(fs)

    def wait(self, timeout=30.0):
        host().call(lambda: None, timeout=timeout)
        return all(s._idle.wait(timeout) for s in self.slots)

    # ------------------------------------------------------------------ resumo para a interface
    @property
    def active(self):
        return any(s.active for s in self.slots)

    def summary(self):
        """(texto curto, estado): estado "err" (algum com erro/não encontrado), "loading", "on" (algum
        ligado e funcionando) ou "off"."""
        used = [s for s in self.slots if s.path]
        if not used:
            return "Nenhum plugin", "off"
        names = []
        for s in used:
            mark = "✓" if (s.ok and s.on) else "⚠" if s.failed else "…" if s.loading else "–"
            names.append(f"{s.name} {mark}")
        if any(s.failed for s in used):
            state = "err"
        elif any(s.loading for s in used):
            state = "loading"
        elif any(s.ok and s.on for s in used):
            state = "on"
        else:
            state = "off"
        return ", ".join(names), state

    # ------------------------------------------------------------------ áudio (tempo real)
    def process(self, KB, n):
        for s in self.slots:
            if s.inst is not None:
                s.process(KB, n)

    def process_lr(self, L, R, n):
        for s in self.slots:
            if s.inst is not None:
                s.process_lr(L, R, n)
