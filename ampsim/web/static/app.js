// AmpSim remoto: fala com o AmpSim por um WebSocket em /ws (mesma porta da página).
// Toques vão na hora (pointerdown); o AmpSim manda só as telas que mudaram.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const TABS = {
  pads: ["▦", "Pads"], faders: ["≡", "Faders"], setlist: ["♫", "Setlist"], timbre: ["◉", "Timbre"],
  guitarra: ["♪", "Guitarra"], baixo: ["♪", "Baixo"], vocal: ["♪", "Vocal"],
};
const TITLES = {
  pads: "Pads", faders: "Faders e mute", setlist: "Setlist", timbre: "Timbre atual",
  guitarra: "Guitarra", baixo: "Baixo", vocal: "Vocal",
};
// as 4 escolhas do topo: cada uma é uma sessão do AmpSim com as telas dela
const MODES = [
  { id: "piano", nome: "Pad/Piano", telas: ["pads", "faders", "setlist", "timbre"] },
  { id: "guitarra", nome: "Guitarra", telas: ["guitarra"] },
  { id: "baixo", nome: "Baixo", telas: ["baixo"] },
  { id: "vocal", nome: "Vocal", telas: ["vocal"] },
];

let ws = null, retry = 400, telas = [], state = {}, built = {}, tab = null, mode = null, modes = [], pingTimer = null;
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* sem storage */ } },
};

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k);
  return e;
}

// botão que reage no toque (sem esperar o "click", que atrasa no celular)
function tap(e, fn) {
  e.addEventListener("pointerdown", ev => { if (ev.button === 0) { ev.preventDefault(); fn(ev); } });
  e.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(ev); } });
  e.addEventListener("contextmenu", ev => ev.preventDefault());
  return e;
}

function send(msg) {
  if (ws && ws.readyState === 1) { ws.send(JSON.stringify(msg)); return true; }
  return false;
}
const cmd = (c, extra = {}) => send({ t: "cmd", c, ...extra });

// ------------------------------------------------------------------ conexão
function connect() {
  const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
  ws = new WebSocket(url);
  ws.onopen = () => {
    retry = 400;
    $("#offline").hidden = true;
    $("#dot").className = "dot on";
    clearInterval(pingTimer);
    pingTimer = setInterval(() => send({ t: "ping", id: performance.now() }), 2000);
    send({ t: "ping", id: performance.now() });
  };
  ws.onmessage = ev => {
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    onMessage(m);
  };
  ws.onclose = () => {
    clearInterval(pingTimer);
    $("#dot").className = "dot off";
    $("#lat").textContent = "sem conexão";
    if (telas.length) $("#offline").hidden = false;
    setTimeout(connect, retry);
    retry = Math.min(retry * 1.6, 3000);
  };
}

function onMessage(m) {
  if (m.t === "pong") {
    $("#lat").textContent = Math.max(1, Math.round(performance.now() - m.id)) + " ms";
  } else if (m.t === "precisa_login") {
    const tok = store.get("ampsim_token");
    if (tok) send({ t: "token", token: tok }); else showLogin("");
  } else if (m.t === "auth") {
    if (m.ok) {
      if (m.token) store.set("ampsim_token", m.token);
      $("#sair").hidden = !m.login;
      $(".top").classList.toggle("com-sair", !!m.login);
      showApp(m.telas);
    } else {
      store.set("ampsim_token", null);
      showLogin(m.erro || "");
    }
  } else if (m.t === "estado") {
    const touched = new Set();
    for (const [k, v] of Object.entries(m.telas)) {
      state[k] = v;
      touched.add(k.split(".")[0]);
    }
    for (const t of touched) if (built[t] && state[t]) built[t].update(merged(t));
  } else if (m.t === "aviso") {
    toast(m.texto);
  } else if (m.t === "vu") {
    if (built.faders && built.faders.vu) built.faders.vu(+m.m || 0, +m.c || 0);
  }
}

// tela + as partes dela ("pads.sons" vira d.sons)
function merged(t) {
  const d = Object.assign({}, state[t]);
  for (const [k, v] of Object.entries(state)) if (k.startsWith(t + ".")) d[k.slice(t.length + 1)] = v;
  return d;
}

let toastTimer = 0;
function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

// janela que sobe de baixo com uma lista para escolher (timbres, sons dos pads, presets)
function sheet(title, groups, current, onPick) {
  const back = el("div", { class: "sheet-back" });
  const box = el("div", { class: "sheet", role: "dialog", "aria-label": title });
  const close = () => back.remove();
  // aberta segurando um pad: o dedo que solta gera um "click" embaixo dele, que não pode escolher nem fechar.
  // Só vale o que começou (toque/tecla) dentro da lista.
  let armed = false;
  back.addEventListener("pointerdown", () => { armed = true; }, true);
  back.addEventListener("keydown", () => { armed = true; }, true);
  const search = el("input", { type: "search", placeholder: "Buscar…", "aria-label": "Buscar" });
  const list = el("div", { class: "sheet-list" });
  const render = () => {
    const q = search.value.trim().toLowerCase();
    list.textContent = "";
    for (const g of groups) {
      const items = g.sons.filter(s => !q || (s.curto || s.nome).toLowerCase().includes(q) || g.cat.toLowerCase().includes(q));
      if (!items.length) continue;
      const open = !!q || g.sons.some(s => s.nome === current) || groups.length <= 2;
      const det = el("details", open ? { open: true } : {}, el("summary", {}, g.cat + " (" + items.length + ")"));
      const grid = el("div", { class: "opts" });
      for (const s of items) {
        const b = el("button", { class: "opt" + (s.nome === current ? " on" : "") + (s.falta ? " falta" : "") },
          (s.curto || s.nome) + (s.falta ? " ⬇" : ""));
        b.addEventListener("click", () => { if (armed) { onPick(s.nome); close(); } });
        grid.append(b);
      }
      det.append(grid);
      list.append(det);
    }
  };
  search.addEventListener("input", render);
  const x = el("button", { class: "ghost" }, "Fechar");
  x.addEventListener("click", close);
  back.addEventListener("click", ev => { if (armed && ev.target === back) close(); });
  box.append(el("div", { class: "sheet-head" }, el("b", {}, title), x), search, list);
  back.append(box);
  document.body.append(back);
  render();
  const on = list.querySelector(".opt.on");
  if (on) on.scrollIntoView({ block: "center" });
}

function showLogin(erro) {
  telas = [];
  $("#app").hidden = true;
  $("#tabs").hidden = true;
  $("#modos").hidden = true;
  $("#login").hidden = false;
  $("#loginErro").textContent = erro;
  const btn = $("#loginForm button");
  btn.disabled = false;
}

$("#loginForm").addEventListener("submit", ev => {
  ev.preventDefault();
  $("#loginErro").textContent = "";
  $("#loginForm button").disabled = true;
  if (!send({ t: "login", nome: $("#nome").value.trim(), senha: $("#senha").value })) {
    $("#loginErro").textContent = "Sem conexão com o AmpSim";
    $("#loginForm button").disabled = false;
  }
});
$("#sair").addEventListener("click", () => {
  store.set("ampsim_token", null);
  $("#senha").value = "";
  if (ws) ws.close();
  showLogin("");
});

function showApp(list) {
  telas = list.filter(t => BUILD[t]);
  state = {};
  built = {};
  $("#login").hidden = true;
  $("#app").hidden = false;
  const box = $("#panels");
  box.textContent = "";
  for (const t of telas) {
    const sec = el("section", { class: "panel", id: "p-" + t }, el("h2", {}, TITLES[t]));
    box.append(sec);
    built[t] = BUILD[t](sec);
  }
  if (!telas.length) box.append(el("p", { class: "vazio" }, "Este usuário não tem nenhuma tela liberada. Peça para liberar no botão Webserver do AmpSim."));
  // escolhas do topo: só as que têm alguma tela liberada (com uma só, nem aparecem)
  modes = MODES.filter(m => m.telas.some(t => telas.includes(t)));
  const seg = $("#modos");
  seg.textContent = "";
  for (const m of modes) {
    const b = el("button", { "data-m": m.id, role: "tab" }, m.nome);
    tap(b, () => setMode(m.id));
    seg.append(b);
  }
  seg.hidden = modes.length < 2;
  $(".top").classList.toggle("com-modos", modes.length > 1);
  // link direto: http://…:8080/#guitarra, #baixo, #vocal, #piano ou uma aba (#faders)
  const hash = location.hash.slice(1);
  const byTab = modes.find(m => m.telas.includes(hash) && telas.includes(hash));
  if (modes.some(m => m.id === hash)) setMode(hash);
  else if (byTab) setMode(byTab.id, hash);
  else setMode(store.get("ampsim_modo"));
}

function setMode(id, want) {
  const m = modes.find(x => x.id === id) || modes[0];
  const nav = $("#tabs");
  nav.textContent = "";
  if (!m) { nav.hidden = true; document.body.classList.add("notabs"); return; }
  mode = m.id;
  store.set("ampsim_modo", m.id);
  for (const b of $("#modos").children) {
    b.classList.toggle("on", b.dataset.m === m.id);
    b.setAttribute("aria-selected", b.dataset.m === m.id);
  }
  const mine = m.telas.filter(t => telas.includes(t));
  for (const t of mine) {
    const b = el("button", { "data-t": t }, el("b", {}, TABS[t][0]), TABS[t][1]);
    tap(b, () => setTab(t));
    nav.append(b);
  }
  nav.hidden = mine.length < 2;
  document.body.classList.toggle("notabs", mine.length < 2);
  layout();
  for (const s of document.querySelectorAll(".panel")) s.classList.toggle("inmode", mine.includes(s.id.slice(2)));
  const saved = store.get("ampsim_tab_" + m.id);
  setTab(mine.includes(want) ? want : mine.includes(saved) ? saved : mine[0]);
}

// PC (janela a partir de 1240x600): as telas da sessão lado a lado ocupando a altura, sem rolar a página.
// Menor que isso (tablet deitado, notebook 1024x768) fica como no celular: uma tela por vez.
const mqDesk = matchMedia("(min-width: 1240px) and (min-height: 600px)");
function layout() {
  document.body.classList.toggle("fill", mqDesk.matches);
}
if (mqDesk.addEventListener) mqDesk.addEventListener("change", layout); else mqDesk.addListener(layout);

function setTab(t) {
  tab = t;
  store.set("ampsim_tab_" + mode, t);
  for (const s of document.querySelectorAll(".panel")) s.classList.toggle("show", s.id === "p-" + t);
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.t === t);
  $("main").scrollTop = 0;
}

// um fader de mesa de som: nome e valor em cima, cursor no trilho e o mute do lado.
// onVal(v 0..100) / onMute(on): o que ele faz (aba Faders, volume da trilha, parâmetro de pedal...)
// Feito com pointer events: no dedo, arrastar de lado mexe no fader e arrastar para cima/baixo rola a
// lista (touch-action: pan-y); um toque parado não muda nada. No mouse, clicar no trilho pula até lá.
// opts.inv: invertido (0 com o cursor na DIREITA, como o Compressor do PC tem o 0 em cima);
// opts.vu: "level" (nível da saída, acende da esquerda) ou "gr" (redução do compressor, acende da direita)
function faderRow(nome, onVal, onMute, opts = {}) {
  const inv = !!opts.inv;
  const val = el("span", { class: "val" });
  const cap = el("div", { class: "hf-cap" });
  const fill = el("div", { class: "hf-fill" });
  const groove = el("div", { class: "hf-groove" }, fill);
  if (opts.vu) groove.append(el("div", { class: "hf-vu " + opts.vu }));
  const slot = el("div", { class: "hf-slot" + (opts.vu ? " com-vu" : ""), role: "slider", tabindex: 0, "aria-label": nome,
    "aria-valuemin": 0, "aria-valuemax": 100 }, groove, cap);
  const r = { slot, val, mute: null, mudo: false, txt: false, v: 0, drag: false, off: false };
  let raf = 0, rect = null, grab = 0, start = null;
  const pos = v => inv ? 1 - v / 100 : v / 100;                  // posição do cursor 0..1 (esquerda->direita)
  const fromX = x => (inv ? 1 - x : x) * 100;
  r.vu = m => slot.style.setProperty("--m", Math.max(0, Math.min(1, m)));
  r.paint = () => {
    slot.style.setProperty("--p", pos(r.v));
    slot.setAttribute("aria-valuenow", r.v);
    if (!r.txt) val.textContent = r.mudo ? "MUDO · " + r.v + "%" : r.v + "%";
  };
  const set = v => {
    v = Math.max(0, Math.min(100, Math.round(v)));
    if (v === r.v) return;
    r.v = v;
    r.paint();
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; onVal(r.v); });
  };
  const span = () => Math.max(1, rect.width - 22);
  const begin = ev => {
    r.drag = true;
    slot.classList.add("drag");
    try { slot.setPointerCapture(ev.pointerId); } catch (e) { /* ponteiro sintético */ }
  };
  slot.addEventListener("pointerdown", ev => {
    if (ev.button !== 0 || r.off) return;
    rect = slot.getBoundingClientRect();
    if (ev.pointerType === "mouse") {
      ev.preventDefault();
      slot.focus({ preventScroll: true });
      const capX = rect.left + 11 + pos(r.v) * span();
      grab = Math.abs(ev.clientX - capX) <= 14 ? ev.clientX - capX : 0;     // pegou no cursor: não pula
      begin(ev);
      set(fromX((ev.clientX - grab - rect.left - 11) / span()));
    } else {
      start = { x: ev.clientX, y: ev.clientY, v: r.v };                      // dedo: espera a direção
    }
  });
  slot.addEventListener("pointermove", ev => {
    if (r.drag && !start) {
      set(fromX((ev.clientX - grab - rect.left - 11) / span()));
    } else if (r.drag) {
      set(start.v + (inv ? -1 : 1) * (ev.clientX - start.x) / span() * 100);
    } else if (start) {
      const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
      if (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.2) {          // de lado: é o fader
        start = { x: ev.clientX, y: ev.clientY, v: r.v };
        begin(ev);
      } else if (Math.abs(dy) > 8) {
        start = null;                                                         // para cima/baixo: rola
      }
    }
  });
  // (sem "lostpointercapture": no toque o navegador troca a captura implícita pela nossa e avisa)
  const up = () => { r.drag = false; start = null; slot.classList.remove("drag"); };
  for (const t of ["pointerup", "pointercancel"]) slot.addEventListener(t, up);
  slot.addEventListener("keydown", ev => {
    if (r.off) return;
    const d = { ArrowUp: 1, ArrowRight: inv ? -1 : 1, ArrowDown: -1, ArrowLeft: inv ? 1 : -1, PageUp: 10, PageDown: -10 }[ev.key];
    if (d) { ev.preventDefault(); set(r.v + d); }
    else if (ev.key === "Home") { ev.preventDefault(); set(0); }
    else if (ev.key === "End") { ev.preventDefault(); set(100); }
  });
  const ctl = el("div", { class: "ctl" }, slot);
  if (onMute) {
    r.mute = el("button", { class: "mute", "aria-label": "Mute " + nome }, "M");
    tap(r.mute, () => onMute(!r.mudo));
    ctl.append(r.mute);
  }
  r.row = el("div", { class: "fader" }, el("div", { class: "top" }, el("span", { class: "nome" }, nome), val), ctl);
  r.paint();
  return r;
}

// c: {valor 0..100, mudo, ativo, txt (texto do valor de verdade, ex. "380 ms")}
function faderShow(r, c) {
  r.mudo = !!c.mudo;
  r.txt = c.txt != null;
  r.off = c.ativo === false;
  if (!r.drag) r.v = c.valor;
  r.paint();
  if (r.txt) r.val.textContent = c.mudo ? "MUDO · " + c.txt : c.txt;
  r.slot.setAttribute("aria-disabled", r.off);
  r.row.classList.toggle("off", r.off);
  r.row.classList.toggle("mudo", r.mudo);
  if (r.mute) r.mute.classList.toggle("on", r.mudo);
}

// diminui a letra até o texto caber inteiro na caixa dele (sem cortar palavra no meio)
function fitText(t, max, min) {
  let px = max;
  t.style.fontSize = px + "px";
  while (px > min && (t.scrollWidth > t.clientWidth + 1 || t.scrollHeight > t.clientHeight + 1)) {   // +1: arredondamento
    px -= 0.5;
    t.style.fontSize = px + "px";
  }
}

// a maior letra (entre min e max) com que TODOS os textos cabem, igual para todos (pads de bateria)
function fitCommon(box, sel, max, min) {
  const run = () => {
    const ts = [...box.querySelectorAll(sel)];
    if (!ts.length || !ts[0].getClientRects().length) return;
    let px = max;
    const fits = () => ts.every(t => t.scrollWidth <= t.clientWidth + 1 && t.scrollHeight <= t.clientHeight + 1);
    ts.forEach(t => { t.style.fontSize = px + "px"; });
    while (px > min && !fits()) {
      px -= 0.5;
      ts.forEach(t => { t.style.fontSize = px + "px"; });
    }
  };
  if (!box._fitc && window.ResizeObserver) {
    box._fitc = new ResizeObserver(() => requestAnimationFrame(run));
    box._fitc.observe(box);
  }
  run();
}

// refaz o ajuste quando a caixa muda de tamanho (girar o celular, abrir a linha de salvar...)
function fitAll(box, sel, max, min) {
  const run = () => box.querySelectorAll(sel).forEach(t => fitText(t, max, min));
  if (!box._fit && window.ResizeObserver) {
    box._fit = new ResizeObserver(() => requestAnimationFrame(run));
    box._fit.observe(box);
  }
  run();
}

// botão dentro de lista que rola (chips, músicas): vale o "click" (o navegador não manda click
// quando o dedo arrastou para rolar), então passar o dedo pela lista não escolhe nada
function press(e, fn) {
  e.addEventListener("click", fn);
  return e;
}

// fader em pé (como o da mesa): cursor deitado num trilho vertical, valor/nome/mute do lado.
// Feito com pointer events (arrastar com o dedo funciona igual em qualquer navegador).
// stack: valor e nome em cima, M embaixo (coluna estreita, sobra largura para os pads de bateria)
function vFader(nome, curto, onVal, onMute, stack) {
  const cap = el("div", { class: "vf-cap" });
  const fill = el("div", { class: "vf-fill" });
  const slot = el("div", { class: "vf-slot", role: "slider", tabindex: 0, "aria-label": nome,
    "aria-valuemin": 0, "aria-valuemax": 100, "aria-orientation": "vertical" }, el("div", { class: "vf-groove" }, fill), cap);
  const val = el("b", { class: "vf-val" }, "–");
  const mute = el("button", { class: "mute vf-mute", "aria-label": "Mute " + nome }, "M");
  const r = { v: 0, mudo: false, drag: false, slot };
  r.row = el("div", { class: "vf" + (stack ? " stack" : "") }, slot, el("div", { class: "vf-side" }, val, el("small", { class: "vf-nome" }, curto), mute));
  tap(mute, () => onMute(!r.mudo));
  let raf = 0, rect = null, off = 0;
  const paint = () => {
    slot.style.setProperty("--p", r.v / 100);
    slot.setAttribute("aria-valuenow", r.v);
    val.textContent = r.mudo ? "MUDO" : r.v + "%";
  };
  const set = v => {
    v = Math.max(0, Math.min(100, Math.round(v)));
    if (v === r.v) return;
    r.v = v;
    paint();
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; onVal(r.v); });
  };
  const at = y => ((rect.bottom - 11) - (y - off)) / Math.max(1, rect.height - 22) * 100;
  slot.addEventListener("pointerdown", ev => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    slot.focus({ preventScroll: true });
    try { slot.setPointerCapture(ev.pointerId); } catch (e) { /* ponteiro sintético */ }
    rect = slot.getBoundingClientRect();
    const capY = rect.bottom - 11 - r.v / 100 * (rect.height - 22);
    off = Math.abs(ev.clientY - capY) <= 16 ? ev.clientY - capY : 0;   // pegou no cursor: não pula
    r.drag = true;
    slot.classList.add("drag");
    set(at(ev.clientY));
  });
  slot.addEventListener("pointermove", ev => { if (r.drag) set(at(ev.clientY)); });
  const up = () => { r.drag = false; slot.classList.remove("drag"); };
  for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) slot.addEventListener(t, up);
  slot.addEventListener("keydown", ev => {
    const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 10, PageDown: -10 }[ev.key];
    if (d) { ev.preventDefault(); set(r.v + d); }
    else if (ev.key === "Home") { ev.preventDefault(); set(0); }
    else if (ev.key === "End") { ev.preventDefault(); set(100); }
  });
  r.show = c => {
    r.mudo = !!c.mudo;
    if (!r.drag) r.v = c.valor;
    paint();
    r.row.classList.toggle("mudo", r.mudo);
    mute.classList.toggle("on", r.mudo);
  };
  paint();
  return r;
}

// nome como o AmpSim guarda no arquivo (mesma troca do storage._safe), para achar um nome repetido
const safeName = n => n.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").replace(/\s+/g, " ")
  .replace(/[<>:"/\\|?*]/g, "_").trim();

// botão "💾 Salvar…" no título + linha com o nome (aparece ao tocar; nada abre no PC).
// exists(nome): já existe um com esse nome? Então o 1º Salvar avisa e vira "Substituir".
function saveBox(label, title, getName, onSave, exists) {
  const input = el("input", { type: "text", maxlength: 60, "aria-label": title, enterkeyhint: "done",
    autocomplete: "off", autocapitalize: "sentences" });
  const ok = el("button", { type: "submit", class: "btn ok" }, "Salvar");
  const cancel = el("button", { type: "button", class: "btn sq", "aria-label": "Cancelar" }, "✕");
  const row = el("form", { class: "saverow", hidden: true }, input, ok, cancel);
  const chip = el("button", { type: "button", class: "chip save", title }, label);
  let armed = "";
  const disarm = () => { armed = ""; ok.textContent = "Salvar"; ok.classList.remove("perigo"); };
  const close = () => { row.hidden = true; chip.classList.remove("on"); input.blur(); disarm(); };
  input.addEventListener("input", disarm);
  chip.addEventListener("click", () => {
    if (!row.hidden) { close(); return; }
    row.hidden = false;
    chip.classList.add("on");
    input.value = getName() || "";
    input.focus();
    input.select();
  });
  row.addEventListener("submit", ev => {
    ev.preventDefault();
    const n = input.value.trim();
    if (!n) { toast("Digite um nome"); input.focus(); return; }
    const key = safeName(n).toLowerCase();
    if (exists && armed !== key && exists(key)) {
      armed = key;                                   // 2º toque em "Substituir" grava por cima
      ok.textContent = "Substituir";
      ok.classList.add("perigo");
      toast("Já existe “" + safeName(n) + "”: toque Substituir para trocar");
      return;
    }
    onSave(n);
    close();
  });
  cancel.addEventListener("click", close);
  return { chip, row };
}

// mostra o item dentro da lista que rola, sem rolar a página (no PC a página rolaria junto)
function reveal(box, item, horizontal) {
  const r = item.getBoundingClientRect(), b = box.getBoundingClientRect();
  if (horizontal) {
    if (r.left < b.left || r.right > b.right) box.scrollLeft += r.left - b.left - 8;
  } else if (box.scrollHeight > box.clientHeight) {
    if (r.top < b.top) box.scrollTop += r.top - b.top - 4;
    else if (r.bottom > b.bottom) box.scrollTop += r.bottom - b.bottom + 4;
  }
}

// lista que só é refeita quando mudou
function keyed(box, items, make) {
  const sig = JSON.stringify(items);
  if (box._sig === sig) return false;
  box._sig = sig;
  box.textContent = "";
  items.forEach((it, i) => box.append(make(it, i)));
  return true;
}

// duas colunas: no celular em pé viram uma só (display: contents); deitado ficam lado a lado
function cols(sec) {
  const a = el("div", { class: "col col-a" }), b = el("div", { class: "col col-b" });
  sec.append(el("div", { class: "cols" }, a, b));
  return [a, b];
}

// ------------------------------------------------------------------ telas
const BUILD = {
  pads(sec) {
    const extra = el("span", { class: "extra" });
    sec.firstChild.append(extra);
    const [a, b] = cols(sec);
    const keys = el("div", { class: "keys" });
    const parar = tap(el("button", { class: "chip stop" }, "■ Parar"), () => cmd("pad_parar"));
    const chips = el("div", { class: "chips" });
    const chipRow = el("div", { class: "chips-row" }, parar, chips);
    // gravador: REC / PLAY / STOP (o mesmo da aba Faders / Pads do PC)
    const recSel = el("select", { "aria-label": "Gravação para o PLAY" });
    const recb = tap(el("button", { class: "btn rec" }, "● REC"), () => cmd("rec"));
    // PLAY: um toque toca uma vez (na hora); o 2º toque logo em seguida (até 350 ms) faz a mesma
    // gravação, que já está tocando, repetir em loop até o STOP
    let lastPlay = -1e9;
    const play = tap(el("button", { class: "btn play" }, "▶ PLAY"), () => {
      const now = performance.now();
      if (now - lastPlay < 350) {
        lastPlay = -1e9;
        cmd("rec_ouvir", { nome: recSel.value, loop: true });
      } else {
        lastPlay = now;
        cmd("rec_ouvir", { nome: recSel.value });
      }
    });
    const stop = tap(el("button", { class: "btn" }, "■ STOP"), () => cmd("rec_parar"));
    const recInfo = el("small", { class: "dica" });
    const drums = el("div", { class: "drums" });
    // volume do pad contínuo do lado das notas, volume da bateria do lado dos pads (faders em pé)
    const PAD = "Volume pad contínuo", BAT = "Volume bateria";
    const vfPad = vFader("Volume do pad contínuo", "Pad", v => cmd("pad_volume", { id: PAD, valor: v }),
      on => cmd("pad_mute", { id: PAD, on }));
    const vfBat = vFader("Volume dos pads de bateria", "Bateria", v => cmd("pad_volume", { id: BAT, valor: v }),
      on => cmd("pad_mute", { id: BAT, on }), true);
    let catalog = [];
    a.append(el("h3", {}, "Pad contínuo"), el("div", { class: "keyrow" }, keys, vfPad.row),
      el("h3", {}, "Timbre do pad contínuo"), chipRow,
      el("h3", {}, "Gravador ", recInfo), el("div", { class: "recrow" }, recb, play, stop, recSel));
    b.append(el("h3", {}, "Pads de bateria ", el("small", { class: "dica" }, "segure para trocar o som")),
      el("div", { class: "drumrow grow" }, drums, vfBat.row));
    return {
      update(d) {
        keyed(keys, d.tons, k => tap(el("button", { class: "key" + (k.includes("#") ? " sharp" : ""), "data-k": k }, k),
          () => cmd("pad_cont", { tom: k })));
        for (const b of keys.children) b.classList.toggle("on", b.dataset.k === d.tom);
        parar.disabled = !d.tom;
        keyed(chips, d.timbres, x => press(el("button", { class: "chip", "data-n": x.nome }, x.curto),
          () => cmd("pad_timbre", { nome: x.nome })));
        for (const b of chips.children) b.classList.toggle("on", b.dataset.n === d.timbre);
        extra.textContent = d.tom ? "tocando " + d.tom + (d.segue ? " · segue o acorde" : "") : (d.segue ? "segue o acorde" : "");
        const g = d.gravador || { gravacoes: [] };
        recb.classList.toggle("on", !!g.gravando);
        recb.textContent = g.gravando ? "● " + g.segundos.toFixed(1) + " s" : "● REC";
        keyed(recSel, g.gravacoes.length ? g.gravacoes : ["(nenhuma gravação ainda)"], n => el("option", { value: n }, n));
        if (g.atual && recSel._atual !== g.atual) { recSel._atual = g.atual; recSel.value = g.atual; }
        recSel.disabled = play.disabled = !g.gravacoes.length;
        play.classList.toggle("on", !!g.loop);
        play.textContent = g.loop ? "⟳ LOOP" : "▶ PLAY";
        play.title = g.loop ? "Repetindo " + g.loop + " (STOP para parar)" : "Toque 2× para repetir em loop";
        recInfo.textContent = !g.audio ? "ligue o áudio no PC para gravar"
          : g.loop ? "em loop: " + g.loop + " · STOP encerra" : g.gravacoes.length ? "PLAY 2× = loop" : "";
        const vol = {};
        for (const v of d.volumes || []) vol[v.id] = v;
        vfPad.row.hidden = !vol[PAD];
        vfBat.row.hidden = !vol[BAT];
        if (vol[PAD]) vfPad.show(vol[PAD]);
        if (vol[BAT]) vfBat.show(vol[BAT]);
        catalog = d.sons || [];
        const novos = keyed(drums, d.bateria, x => {
          const b = el("button", { class: "drum" }, el("span", { class: "fit" }, x.nome.replace(/\+ /g, "+\u00a0")));
          let hold = 0;
          const pick = () => catalog.length
            ? sheet("Som do Pad " + (x.i + 1), catalog, x.som, nome => cmd("pad_som", { i: x.i, nome }))
            : toast("A lista de sons não chegou: feche e abra o AmpSim no PC");
          b.addEventListener("pointerdown", ev => {
            if (ev.button !== 0) return;
            ev.preventDefault();
            const r = b.getBoundingClientRect();
            // toque mais embaixo do pad = mais forte (como num pad de verdade)
            const y = ev.clientY ? Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height)) : 0.7;
            cmd("pad", { i: x.i, vel: Math.round(70 + y * 57) });
            b.classList.add("hit");
            clearTimeout(b._t);
            b._t = setTimeout(() => b.classList.remove("hit"), 110);
            clearTimeout(hold);
            hold = setTimeout(pick, 550);                    // segurou: escolher o som
          });
          for (const t of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(t, () => clearTimeout(hold));
          b.addEventListener("contextmenu", ev => { ev.preventDefault(); clearTimeout(hold); pick(); });
          return b;
        });
        // nome inteiro, até 3 linhas, mesma letra nos 8 (piso de 9 px; 8 só em celular de 320 px)
        if (novos) fitCommon(drums, ".drum .fit", 14, innerWidth < 340 ? 8 : 9);
      },
    };
  },

  faders(sec) {
    const box = el("div", { class: "faders-box grow" });
    sec.append(box);
    const rows = {};
    // deitado: duas colunas; três só se metade dos faders não couber na altura (ex. 4 camadas em 740x360)
    let nAtivos = 0;
    const colunas = () => {
      const ncol = nAtivos > 10 && Math.ceil(nAtivos / 2) * 46 > box.clientHeight ? 3 : 2;
      box.style.setProperty("--cols", ncol);
      box.style.setProperty("--rows", Math.max(1, Math.ceil(nAtivos / ncol)));
    };
    if (window.ResizeObserver) new ResizeObserver(() => colunas()).observe(box);
    let vuM = 0, vuC = 0, hint = null;          // último medidor recebido (volta a acender se a lista for refeita)
    const showVu = () => {
      if (rows.Master) rows.Master.vu(vuM);
      if (rows.Compressor) rows.Compressor.vu(vuC);
      if (hint) hint.classList.toggle("lit", vuC > 0.02);     // VU laranja aceso: a dica sai da frente
    };
    return {
      // {"t":"vu"}: nível da saída (Master) e redução nos picos (compressor + limitador), 0..1, ~15x/s
      vu(m, c) {
        vuM = m;
        vuC = c;
        showVu();
      },
      update(d) {
        if (keyed(box, d.canais.map(c => [c.id, c.nome, c.pode_mutar]), ([id, nome, pode]) => {
          const opts = id === "Master" ? { vu: "level" } : id === "Compressor" ? { vu: "gr", inv: true } : {};
          rows[id] = faderRow(nome, valor => cmd("fader", { id, valor }), pode ? on => cmd("mute", { id, on }) : null, opts);
          if (id === "Compressor") {
            rows[id].row.title = "Compressor: 0 com o cursor à direita; arraste para a esquerda para comprimir mais. O laranja mostra quanto os picos estão sendo abaixados (compressor + limitador).";
            // dica dentro do trilho enquanto está desligado (o cursor fica na direita)
            hint = el("span", { class: "hf-hint" }, "◀ arraste p/ comprimir");
            rows[id].slot.append(hint);
          }
          return rows[id].row;
        })) showVu();
        for (const c of d.canais) {
          if (!rows[c.id]) continue;
          faderShow(rows[c.id], c.id === "Compressor" ? Object.assign({}, c, { txt: c.valor ? c.valor + "%" : "desligado" }) : c);
        }
        const comp = d.canais.find(c => c.id === "Compressor");
        if (hint && comp) hint.hidden = comp.valor > 0;
        // deitado: duas colunas (três quando são mais de 12 faders, ex. com as 4 camadas)
        nAtivos = d.canais.filter(c => c.ativo !== false).length;
        colunas();
      },
    };
  },

  setlist(sec) {
    const [a, b] = cols(sec);
    const sel = el("select", { "aria-label": "Lista" });
    sel.addEventListener("change", () => cmd("setlist", { nome: sel.value }));
    const songs = el("ul", { class: "songs grow scroll" });
    const prev = tap(el("button", { class: "btn" }, "◀ Anterior"), () => cmd("musica_passo", { d: -1 }));
    const next = tap(el("button", { class: "btn" }, "Próxima ▶"), () => cmd("musica_passo", { d: 1 }));
    const vazio = el("p", { class: "vazio" }, "Nenhuma música nesta lista. Monte a setlist no AmpSim.");
    a.append(sel, el("div", { class: "row setl-nav" }, prev, next));
    b.append(songs, vazio);
    return {
      update(d) {
        keyed(sel, d.listas, n => el("option", { value: n }, n));
        sel.value = d.atual;
        keyed(songs, d.musicas, (s, i) => el("li", {}, press(el("button", { "data-i": i },
          el("span", {}, (i + 1) + ". " + s.nome), el("span", { class: "tom" }, s.tom ? "pad " + s.tom : "")),
          () => cmd("musica", { i }))));
        songs.querySelectorAll("button").forEach(b => b.classList.toggle("on", +b.dataset.i === d.tocando));
        vazio.hidden = d.musicas.length > 0;
        prev.disabled = next.disabled = !d.musicas.length;
        const on = songs.querySelector("button.on");
        if (on && on._seen !== d.tocando) { on._seen = d.tocando; reveal(songs, on); }
      },
    };
  },

  timbre(sec) {
    // 1. camada  →  2. categoria  →  3. timbre (vale na hora, na camada escolhida)
    let last = null;
    const save = saveBox("💾 Salvar setup", "Nome do setup (timbres das camadas, volumes, efeitos)",
      () => last && last.nome_salvar, nome => cmd("timbre_salvar", { nome }),
      key => ((last && last.meus) || []).some(n => n.toLowerCase() === key));
    sec.firstChild.append(el("span", { class: "extra" }, save.chip));
    const [a, b] = cols(sec);
    const nome = el("span", { class: "preset fit2" }, "—");
    const prev = tap(el("button", { class: "btn sq", "aria-label": "Preset anterior" }, "◀"), () => cmd("preset_passo", { d: -1 }));
    const next = tap(el("button", { class: "btn sq", "aria-label": "Próximo preset" }, "▶"), () => cmd("preset_passo", { d: 1 }));
    const seg = el("div", { class: "seg" });
    const cats = el("div", { class: "chips cats" });
    const list = el("div", { class: "opts grow scroll" });
    const hint = el("p", { class: "hint" });
    const passo3 = el("h3", {}, "3 · Timbre");
    let sel = 1, cat = null;
    // ação da camada escolhida: desligar/ligar a L2 (como no PC) ou remover a L3/L4 (toque 2× para confirmar).
    // A confirmação vale só para a camada em que foi armada: trocar de camada (ou a lista mudar) cancela.
    const acao = el("button", { type: "button", class: "chip acao" });
    let pend = null;                                     // {n, som, timer}: remoção esperando o 2º toque
    const cancelRemove = () => {
      if (!pend) return;
      clearTimeout(pend.timer);
      pend = null;
      acao.classList.remove("perigo");
    };
    acao.addEventListener("click", () => {
      const lista = (last && last.lista) || [];
      if (sel === 2) {
        cancelRemove();
        cmd("timbre_l2", { on: !(lista[1] || {}).ligada });
      } else if (sel >= 3 && sel <= lista.length) {
        const som = (lista[sel - 1] || {}).som;
        if (!pend || pend.n !== sel || pend.som !== som) {
          cancelRemove();
          pend = { n: sel, som, timer: setTimeout(() => { pend = null; render(); }, 2500) };
          toast("Toque de novo em “Remover L" + sel + "?” para remover a camada (" + (som || "") + ")");
          render();
          return;
        }
        const n = pend.n;
        cancelRemove();
        cmd("timbre_remover", { camada: n });
        sel = 1;
        render();
      }
    });
    a.append(el("div", { class: "preset-row" }, nome, prev, next), save.row,
      el("h3", { class: "h3-acao" }, el("span", {}, el("span", { class: "lg" }, "1 · Escolha a camada"),
        el("span", { class: "sh" }, "1 · Camada")), acao), seg,
      el("h3", {}, el("span", { class: "lg" }, "2 · Escolha a categoria"), el("span", { class: "sh" }, "2 · Categoria")), cats);
    b.append(passo3, list, hint);

    function render() {
      const d = last;
      if (!d) return;
      const lista = d.lista || (d.camadas || []).map((s, i) => ({ n: i + 1, som: s, ligada: true }));
      const count = lista.length, max = d.max || 4;
      if (sel > Math.min(count + 1, max)) sel = 1;
      // remoção armada para outra camada (trocou a seleção ou a lista mudou): cancela
      if (pend && (pend.n !== sel || (lista[pend.n - 1] || {}).som !== pend.som)) cancelRemove();
      const atual = (lista[sel - 1] || {}).som || "";
      const catalog = d.sons || [];
      // camadas: existentes, "+" para a próxima, as outras esperam
      keyed(seg, Array.from({ length: max }, (_, i) => [i + 1, (lista[i] || {}).som || "", i < count, i === count,
        !!(lista[i] || {}).ligada]),
        ([n, som, existe, nova, ligada]) => {
          // camada que existe mas está desligada (ex. L2 desligada): apagada, com o timbre e "desligada"
          const off = existe && !ligada;
          const b = el("button", { class: "segb" + (existe ? (off ? " desl" : "") : nova ? " nova" : " fora"), "data-n": n,
            title: som || "" }, el("b", {}, (nova ? "+ " : "") + "L" + n),
            el("small", { class: "fit" }, off ? (som ? som + " · desligada" : "desligada") : existe ? som : nova ? "nova" : "—"));
          b.disabled = !existe && !nova;
          tap(b, () => { sel = n; cat = null; render(); });
          return b;
        });
      for (const b of seg.children) b.classList.toggle("on", +b.dataset.n === sel);
      if (seg._fitSig !== seg._sig) { seg._fitSig = seg._sig; fitAll(seg, ".fit", 10.5, 7.5); }
      if (!catalog.some(g => g.cat === cat)) {
        const g = catalog.find(g => g.sons.some(s => s.nome === atual));
        cat = g ? g.cat : (catalog[0] || {}).cat;
      }
      keyed(cats, catalog.map(g => g.cat), c => tap(el("button", { class: "chip", "data-c": c }, c), () => { cat = c; render(); }));
      for (const b of cats.children) {
        b.classList.toggle("on", b.dataset.c === cat);
      }
      const sons = (catalog.find(g => g.cat === cat) || { sons: [] }).sons;
      if (keyed(list, sons.map(s => [s.nome, !!s.falta]), ([s, falta]) => {
        const b = el("button", { class: "opt" + (falta ? " falta" : ""), "data-s": s }, s + (falta ? " ⬇" : ""));
        b.addEventListener("click", () => cmd("timbre_camada", { camada: sel, nome: s }));
        return b;
      })) list.scrollTop = 0;
      for (const b of list.children) b.classList.toggle("on", b.dataset.s === atual);
      // categoria escolhida logo acima da lista (todas as categorias aparecem, sem arrastar)
      passo3.textContent = "";
      passo3.append("3 · " + (cat || "Timbres") + " · " + sons.length + (sons.length === 1 ? " timbre" : " timbres"),
        el("small", { class: "dica passo" }, sel <= count ? "toque para a L" + sel : "toque para criar a L" + sel));
      // quantas camadas estão soando: um som em camadas fica óbvio
      const tocando = lista.filter(x => x.ligada && x.som).map(x => x.som);
      const selOff = sel <= count && !(lista[sel - 1] || {}).ligada;
      hint.textContent = "Tocando " + tocando.length + (tocando.length === 1 ? " camada: " : " camadas: ") + tocando.join(" + ") + ". "
        + (sel > count ? "O timbre que você tocar cria a L" + sel + "."
          : selOff ? "A L" + sel + " está desligada: escolher um timbre liga ela." : "O timbre que você tocar entra na L" + sel + ".");
      acao.hidden = !(sel >= 2 && sel <= count);
      acao.classList.toggle("perigo", !!pend);
      acao.textContent = pend ? "Remover L" + pend.n + "?"
        : sel === 2 ? (selOff ? "Ligar L2" : "Desligar L2") : "Remover L" + sel;
      if (!catalog.length) {
        hint.textContent = "A lista de timbres não chegou: feche e abra o AmpSim no PC (ele está numa versão anterior à desta página).";
      }
      if (!d.audio) hint.textContent += " (Áudio do AmpSim parado.)";
    }

    return {
      update(d) {
        if (nome.textContent !== (d.preset || "—")) { nome.textContent = d.preset || "—"; fitAll(nome.parentElement, ".fit2", 17, 11); }
        last = d;
        render();
      },
    };
  },

  guitarra(sec) { return trackPanel(sec, "guitar", "da guitarra"); },
  baixo(sec) { return trackPanel(sec, "bass", "do baixo"); },
  vocal(sec) { return trackPanel(sec, "vocal", "do vocal"); },
};

// Guitarra / Baixo / Vocal: preset, volume da trilha, pedais (liga/desliga) e os ajustes do pedal escolhido.
// de: "da guitarra" / "do baixo" / "do vocal" (para os textos). Na Vocal o primeiro pedal é o "Mic" (liga
// e desliga o microfone) e o M do volume é o mudo da voz (o microfone continua ligado).
function trackPanel(sec, trilha, de) {
  const vocal = trilha === "vocal";
  let last = null, fxSel = store.get("ampsim_fx_" + trilha) || (vocal ? "comp" : "amp");
  const tc = (c, extra = {}) => cmd(c, { trilha, ...extra });
  const save = saveBox("💾 Salvar preset", "Nome do preset (" + (vocal ? "efeitos " : "amp e pedais ") + de + ")",
    () => last && last.nome_salvar, nome => tc("trilha_salvar", { nome }),
    key => ((last && last.presets) || []).some(g => g.sons.some(x => x.nome.startsWith("user:")
      && x.nome.slice(5).toLowerCase() === key)));
  const status = el("span", { class: "dica uma-linha" });
  sec.firstChild.append(status, el("span", { class: "extra" }, save.chip));
  const [a, b] = cols(sec);
  // o nome do preset é o botão da lista (★ de fábrica e os seus); ◀ ▶ passam um por um
  const nome = el("span", { class: "preset fit2" }, "—");
  const lista = el("button", { class: "btn lista", "aria-label": "Escolher preset" }, nome, el("span", { class: "seta" }, "▾"));
  const prev = tap(el("button", { class: "btn sq", "aria-label": "Preset anterior" }, "◀"), () => tc("trilha_preset_passo", { d: -1 }));
  const next = tap(el("button", { class: "btn sq", "aria-label": "Próximo preset" }, "▶"), () => tc("trilha_preset_passo", { d: 1 }));
  lista.addEventListener("click", () => {
    const groups = last && last.presets;
    if (!groups || !groups.length) { toast("A lista de presets não chegou"); return; }
    sheet("Presets " + de, groups, last.atual, v => {
      const i = v.indexOf(":");
      tc("trilha_preset", { tipo: v.slice(0, i), nome: v.slice(i + 1) });
    });
  });
  const vol = faderRow("Volume " + de, valor => tc("trilha_volume", { valor }),
    vocal ? on => tc("trilha_mute", { on }) : on => tc("trilha_on", { on: !on }));
  vol.mute.setAttribute("aria-label", vocal ? "Mudo da voz" : "Desligar a trilha " + de);
  const stomps = el("div", { class: "stomps" });
  const fxPick = el("select", { class: "fxpick", "aria-label": "Pedal para ajustar" });
  fxPick.addEventListener("change", () => choose(fxPick.value));
  const params = el("div", { class: "params grow scroll" });
  a.append(el("div", { class: "preset-row" }, lista, prev, next), save.row, vol.row,
    el("h3", {}, "Pedais ", el("small", { class: "dica" }, "toque liga/desliga · segure para ajustar")), stomps);
  b.append(el("div", { class: "fxhead" }, el("h3", {}, "Ajustar"), fxPick), params);
  const rows = {};

  function choose(k) {
    fxSel = k;
    store.set("ampsim_fx_" + trilha, k);
    render();
  }

  function stomp(fx) {
    const btn = el("button", { class: "stomp", "data-k": fx.k, title: fx.nome }, el("i", { class: "led" }),
      el("span", { class: "fit" }, fx.curto));
    let hold = 0, held = false, down = false;
    btn.addEventListener("pointerdown", ev => {
      if (ev.button !== 0) return;
      ev.preventDefault();
      down = true;
      held = false;
      clearTimeout(hold);
      hold = setTimeout(() => { held = true; choose(fx.k); if (navigator.vibrate) navigator.vibrate(15); }, 450);
    });
    btn.addEventListener("pointerup", () => {
      clearTimeout(hold);
      if (down && !held) {                            // toque curto: liga/desliga
        const cur = (last.efeitos.find(e => e.k === fx.k) || {}).on;
        tc("efeito_on", { efeito: fx.k, on: !cur });
      }
      down = false;
    });
    for (const t of ["pointerleave", "pointercancel"]) btn.addEventListener(t, () => { clearTimeout(hold); down = false; });
    btn.addEventListener("contextmenu", ev => { ev.preventDefault(); clearTimeout(hold); down = false; choose(fx.k); });
    btn.addEventListener("keydown", ev => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        const cur = (last.efeitos.find(e => e.k === fx.k) || {}).on;
        tc("efeito_on", { efeito: fx.k, on: !cur });
      }
    });
    return btn;
  }

  function namStomp(title) {
    const b = el("button", { type: "button", class: "stomp on ro", "data-k": "nam", title, "aria-disabled": "true" },
      el("i", { class: "led" }), el("span", { class: "fit" }, "NAM"));
    b.addEventListener("click", () => toast(title + " (escolhida no PC; com o Amp ligado os dois somam)"));
    return b;
  }

  function micStomp() {
    const b = el("button", { type: "button", class: "stomp mic", "data-k": "mic", title: "Microfone: liga/desliga a trilha Vocal" },
      el("i", { class: "led" }), el("span", { class: "fit" }, "Mic"));
    tap(b, () => tc("trilha_on", { on: !(last && last.on) }));
    return b;
  }

  function render() {
    const d = last;
    if (!d) return;
    const fxs = d.efeitos || [];
    if (!fxs.some(f => f.k === fxSel)) fxSel = (fxs[0] || {}).k;
    // captura NAM escolhida no PC: um pedal aceso só para ver (Amp ligado junto soma os dois amplificadores)
    const items = (vocal ? [["mic", "Mic", "Microfone"]] : []).concat(d.nam ? [["nam", "NAM", "Captura NAM: " + d.nam]] : [])
      .concat(fxs.map(f => [f.k, f.curto, f.nome]));
    if (keyed(stomps, items, ([k, curto, n]) => k === "mic" ? micStomp() : k === "nam" ? namStomp(n) : stomp({ k, curto, nome: n }))) {
      stomps.style.setProperty("--n", Math.ceil(items.length / 2));
      fitAll(stomps, ".fit", 12, 8);
    }
    for (const s of stomps.children) {
      if (s.dataset.k === "mic") {
        s.classList.toggle("on", !!d.on);
        s.setAttribute("aria-pressed", !!d.on);
        continue;
      }
      if (s.dataset.k === "nam") continue;
      const f = fxs.find(x => x.k === s.dataset.k) || {};
      s.classList.toggle("on", !!f.on);
      s.classList.toggle("sel", s.dataset.k === fxSel);
      s.setAttribute("aria-pressed", !!f.on);
    }
    keyed(fxPick, fxs.map(f => [f.k, f.nome]), ([k, n]) => el("option", { value: k }, n));
    if (document.activeElement !== fxPick) fxPick.value = fxSel;
    const fx = fxs.find(f => f.k === fxSel);
    if (!fx) return;
    // parâmetros do pedal escolhido: números viram faders, escolhas viram uma lista
    keyed(params, [[fx.k, fx.params.map(p => [p.k, p.nome, p.opcoes || null])]], ([ek, ps]) => {
      const box = el("div", { class: "params-in" });
      for (const k in rows) delete rows[k];
      box.append(el("p", { class: "hint fxoff" }, "Pedal desligado: toque nele para ligar."));
      for (const [pk, pn, opts] of ps) {
        if (opts) {
          const s = el("select", { "aria-label": pn });
          opts.forEach((o, i) => s.append(el("option", { value: i }, o)));
          s.addEventListener("change", () => tc("efeito_param", { efeito: ek, param: pk, valor: +s.value }));
          rows[pk] = { sel: s };
          box.append(el("label", { class: "fxsel" }, el("span", {}, pn), s));
        } else {
          rows[pk] = faderRow(pn, valor => tc("efeito_param", { efeito: ek, param: pk, valor }), null);
          box.append(rows[pk].row);
        }
      }
      return box;
    });
    params.querySelector(".fxoff").hidden = !!fx.on;
    for (const p of fx.params) {
      const r = rows[p.k];
      if (!r) continue;
      if (r.sel) { if (document.activeElement !== r.sel) r.sel.value = p.i; }
      else faderShow(r, { valor: p.valor, txt: p.txt });
    }
  }

  return {
    update(d) {
      last = d;
      if (nome.textContent !== (d.preset || "—")) { nome.textContent = d.preset || "—"; fitAll(lista, ".fit2", 16, 11); }
      faderShow(vol, { valor: d.volume, txt: d.txt, mudo: vocal ? !!d.mudo : !d.on });
      vol.val.textContent = !d.on ? "DESLIGADA · " + d.txt : vocal && d.mudo ? "MUDO · " + d.txt : d.txt;
      vol.row.classList.toggle("off-trilha", vocal && !d.on);
      status.textContent = !d.on ? (vocal ? "microfone desligado" : "trilha desligada")
        : d.audio === false ? "áudio parado no PC" : (d.aviso || "");
      status.title = status.textContent;
      render();
    },
  };
}

connect();
