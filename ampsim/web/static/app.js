// AmpSim remoto: fala com o AmpSim por um WebSocket em /ws (mesma porta da página).
// Toques vão na hora (pointerdown); o AmpSim manda só as telas que mudaram.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const TABS = {
  pads: ["▦", "Pads"], faders: ["≡", "Faders"], setlist: ["♫", "Setlist"],
  tempo: ["♩", "Tempo"], emergencia: ["⏻", "Mute"], timbre: ["◉", "Timbre"],
};
const TITLES = {
  pads: "Pads", faders: "Faders e mute", setlist: "Setlist", tempo: "BPM e click",
  emergencia: "Emergência", timbre: "Timbre atual",
};

let ws = null, retry = 400, telas = [], state = {}, built = {}, tab = null, pingTimer = null;
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
      showApp(m.telas);
    } else {
      store.set("ampsim_token", null);
      showLogin(m.erro || "");
    }
  } else if (m.t === "estado") {
    for (const [k, v] of Object.entries(m.telas)) {
      state[k] = v;
      if (built[k]) built[k].update(v);
    }
  }
}

function showLogin(erro) {
  telas = [];
  $("#app").hidden = true;
  $("#tabs").hidden = true;
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
  const nav = $("#tabs");
  nav.textContent = "";
  for (const t of telas) {
    const b = el("button", { "data-t": t }, el("b", {}, TABS[t][0]), TABS[t][1]);
    tap(b, () => setTab(t));
    nav.append(b);
  }
  nav.hidden = telas.length < 2;
  document.documentElement.style.setProperty("--tabs-h", telas.length < 2 ? "0px" : "");
  const saved = store.get("ampsim_tab");
  setTab(telas.includes(saved) ? saved : telas[0]);
}

function setTab(t) {
  tab = t;
  store.set("ampsim_tab", t);
  for (const s of document.querySelectorAll(".panel")) s.classList.toggle("show", s.id === "p-" + t);
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.t === t);
  $("main").scrollTop = 0;
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

// ------------------------------------------------------------------ telas
const BUILD = {
  pads(sec) {
    const extra = el("span", { class: "extra" });
    sec.firstChild.append(extra);
    sec.append(el("h3", {}, "Pad contínuo"));
    const keys = el("div", { class: "keys" });
    const parar = tap(el("button", { class: "btn red" }, "Parar pad"), () => cmd("pad_parar"));
    const chips = el("div", { class: "chips" });
    const drums = el("div", { class: "drums" });
    sec.append(keys, el("div", { class: "row", style: "margin-top:8px" }, parar), el("h3", {}, "Timbre do pad"),
      chips, el("h3", {}, "Pads de bateria"), drums);
    return {
      update(d) {
        keyed(keys, d.tons, k => tap(el("button", { class: "key" + (k.includes("#") ? " sharp" : ""), "data-k": k }, k),
          () => cmd("pad_cont", { tom: k })));
        for (const b of keys.children) b.classList.toggle("on", b.dataset.k === d.tom);
        parar.disabled = !d.tom;
        keyed(chips, d.timbres, x => tap(el("button", { class: "chip", "data-n": x.nome }, x.curto),
          () => cmd("pad_timbre", { nome: x.nome })));
        for (const b of chips.children) b.classList.toggle("on", b.dataset.n === d.timbre);
        extra.textContent = d.tom ? "tocando " + d.tom + (d.segue ? " · segue o acorde" : "") : (d.segue ? "segue o acorde" : "");
        keyed(drums, d.bateria, x => {
          const b = el("button", { class: "drum" }, el("span", {}, x.nome));
          tap(b, ev => {
            const r = b.getBoundingClientRect();
            // toque mais embaixo do pad = mais forte (como num pad de verdade)
            const y = ev.clientY ? Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height)) : 0.7;
            cmd("pad", { i: x.i, vel: Math.round(70 + y * 57) });
            b.classList.add("hit");
            clearTimeout(b._t);
            b._t = setTimeout(() => b.classList.remove("hit"), 110);
          });
          return b;
        });
      },
    };
  },

  faders(sec) {
    const box = el("div");
    sec.append(box);
    const rows = {};
    return {
      update(d) {
        if (keyed(box, d.canais.map(c => [c.id, c.nome, c.pode_mutar]), ([id, nome, pode]) => {
          const val = el("span", { class: "val" });
          const range = el("input", { type: "range", min: 0, max: 100, step: 1, "aria-label": nome });
          let pend = null, raf = 0;
          range.addEventListener("input", () => {
            val.textContent = range.value + "%";
            pend = +range.value;
            if (!raf) raf = requestAnimationFrame(() => { raf = 0; cmd("fader", { id, valor: pend }); });
          });
          range.addEventListener("pointerdown", () => { range._drag = true; });
          const up = () => { range._drag = false; };
          range.addEventListener("pointerup", up);
          range.addEventListener("pointercancel", up);
          range.addEventListener("change", up);
          const mute = el("button", { class: "mute" }, "MUTE");
          if (pode) tap(mute, () => cmd("mute", { id, on: !rows[id].mudo }));
          else mute.style.visibility = "hidden";
          const row = el("div", { class: "fader" }, el("span", { class: "nome" }, nome), range, val, mute);
          rows[id] = { row, range, val, mute, mudo: false };
          return row;
        })) { /* linhas novas */ }
        for (const c of d.canais) {
          const r = rows[c.id];
          if (!r) continue;
          r.mudo = c.mudo;
          if (!r.range._drag && document.activeElement !== r.range) {
            r.range.value = c.valor;
            r.val.textContent = c.valor + "%";
          }
          r.range.disabled = !c.ativo;
          r.row.classList.toggle("off", !c.ativo);
          r.row.classList.toggle("mudo", c.mudo);
          r.mute.classList.toggle("on", c.mudo);
          r.mute.textContent = c.mudo ? "MUDO" : "MUTE";
        }
      },
    };
  },

  setlist(sec) {
    const sel = el("select", { "aria-label": "Lista" });
    sel.addEventListener("change", () => cmd("setlist", { nome: sel.value }));
    const songs = el("ul", { class: "songs" });
    const prev = tap(el("button", { class: "btn" }, "◀ Anterior"), () => cmd("musica_passo", { d: -1 }));
    const next = tap(el("button", { class: "btn" }, "Próxima ▶"), () => cmd("musica_passo", { d: 1 }));
    const vazio = el("p", { class: "vazio" }, "Nenhuma música nesta lista. Monte a setlist no AmpSim.");
    sec.append(sel, songs, vazio, el("div", { class: "row" }, prev, next));
    return {
      update(d) {
        keyed(sel, d.listas, n => el("option", { value: n }, n));
        sel.value = d.atual;
        keyed(songs, d.musicas, (s, i) => el("li", {}, tap(el("button", { "data-i": i },
          el("span", {}, (i + 1) + ". " + s.nome), el("span", { class: "tom" }, s.tom ? "pad " + s.tom : "")),
          () => cmd("musica", { i }))));
        songs.querySelectorAll("button").forEach(b => b.classList.toggle("on", +b.dataset.i === d.tocando));
        vazio.hidden = d.musicas.length > 0;
        prev.disabled = next.disabled = !d.musicas.length;
        const on = songs.querySelector("button.on");
        if (on && on._seen !== d.tocando) { on._seen = d.tocando; on.scrollIntoView({ block: "nearest" }); }
      },
    };
  },

  tempo(sec) {
    const beat = el("span", { class: "beat" });
    sec.firstChild.append(el("span", { class: "extra" }, beat));
    const num = el("div", { class: "num" }, "—");
    let bpm = 120;
    const step = d => cmd("bpm", { valor: Math.max(30, Math.min(300, Math.round(bpm) + d)) });
    const minus = tap(el("button", { class: "btn big" }, "−"), () => step(-1));
    const plus = tap(el("button", { class: "btn big" }, "+"), () => step(1));
    const tapb = tap(el("button", { class: "btn big", style: "width:100%;margin-top:10px;min-height:76px" }, "TAP"),
      () => { cmd("tap"); tapb.classList.add("on"); setTimeout(() => tapb.classList.remove("on"), 90); });
    const click = el("button", { class: "btn big", style: "width:100%;margin-top:10px" }, "Click");
    let clickOn = false;
    tap(click, () => cmd("click", { on: !clickOn }));
    const aviso = el("p", { class: "aviso" });
    sec.append(el("div", { class: "bpm" }, minus, num, plus), tapb, click, aviso);
    let last = 0;
    return {
      update(d) {
        bpm = d.bpm;
        num.textContent = "";
        num.append(String(Math.round(d.bpm)), el("small", {}, "BPM" + (d.compasso ? " · " + d.compasso + "/4" : "")));
        clickOn = d.click;
        click.classList.toggle("on", d.click);
        click.textContent = d.click ? "Click ligado" : "Click desligado";
        aviso.textContent = d.click && !d.click_saida ? "O click está sem saída de áudio (veja Áudio no AmpSim)." : "";
        if (d.batida && d.batida !== last) {
          beat.classList.add("flash");
          setTimeout(() => beat.classList.remove("flash"), 90);
        }
        last = d.batida;
      },
    };
  },

  emergencia(sec) {
    const mute = el("button", { class: "btn red huge" }, "MUTE GERAL");
    let mudo = false;
    tap(mute, () => cmd("mute_geral", { on: !mudo }));
    const panico = tap(el("button", { class: "btn huge" }, "PÂNICO · parar todas as notas"), () => {
      cmd("panico");
      panico.classList.add("on");
      setTimeout(() => panico.classList.remove("on"), 200);
    });
    const info = el("p", { class: "vazio" });
    sec.append(mute, panico, info);
    return {
      update(d) {
        mudo = d.mudo;
        mute.classList.toggle("on", d.mudo);
        mute.textContent = d.mudo ? "MUDO · toque para voltar o som" : "MUTE GERAL";
        info.textContent = d.audio ? "" : "O áudio do AmpSim está parado ou com falha.";
      },
    };
  },

  timbre(sec) {
    const nome = el("p", { class: "preset" }, "—");
    const camadas = el("p", { class: "camadas" });
    const prev = tap(el("button", { class: "btn" }, "◀ Preset anterior"), () => cmd("preset_passo", { d: -1 }));
    const next = tap(el("button", { class: "btn" }, "Próximo preset ▶"), () => cmd("preset_passo", { d: 1 }));
    const info = el("p", { class: "aviso" });
    sec.append(nome, camadas, el("div", { class: "row" }, prev, next), info);
    return {
      update(d) {
        nome.textContent = d.preset || "—";
        camadas.textContent = d.camadas.map((c, i) => "L" + (i + 1) + ": " + c).join(" · ");
        info.textContent = d.audio ? "" : "O áudio do AmpSim está parado ou com falha.";
      },
    };
  },
};

connect();
