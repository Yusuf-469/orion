// ORION interface: talks to the Python backend through pywebview (window.pywebview.api).
(() => {
  const $ = s => document.querySelector(s);
  const api = () => window.pywebview && window.pywebview.api;
  let state = {}, t0 = 0, timer = null, planDone = 0;

  // ---- starfield -----------------------------------------------------------------------
  const cv = $("#stars"), cx = cv.getContext("2d");
  let stars = [];
  const resize = () => {
    cv.width = innerWidth * devicePixelRatio; cv.height = innerHeight * devicePixelRatio;
    stars = Array.from({length: Math.round(innerWidth * innerHeight / 5200)}, () => ({
      x: Math.random() * cv.width, y: Math.random() * cv.height, r: Math.random() * 1.3 + .2,
      a: Math.random(), s: Math.random() * .015 + .003, v: Math.random() * .08 + .01}));
  };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const draw = () => {
    cx.clearRect(0, 0, cv.width, cv.height);
    const busy = ["thinking", "acting"].includes(document.body.dataset.state);
    for (const s of stars) {
      s.a += s.s; const tw = .45 + .55 * Math.abs(Math.sin(s.a));
      s.y -= busy ? s.v * 6 : s.v; if (s.y < 0) s.y = cv.height;
      cx.globalAlpha = tw; cx.fillStyle = s.r > 1.1 ? "#9fc4ff" : "#dfe6ff";
      cx.beginPath(); cx.arc(s.x, s.y, s.r * devicePixelRatio, 0, 7); cx.fill();
    }
    if (!reduce) requestAnimationFrame(draw);
  };
  addEventListener("resize", resize); resize(); draw();

  // ---- helpers -------------------------------------------------------------------------
  const setState = (s, text) => { document.body.dataset.state = s; if (text) $("#status-text").textContent = text; };
  const esc = s => String(s).replace(/[&<>]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));
  const toast = (msg, bad) => {
    const d = document.createElement("div"); d.className = "toast" + (bad ? " bad" : ""); d.textContent = msg;
    $("#toasts").appendChild(d); setTimeout(() => d.remove(), 6000);
  };
  const greet = () => {
    const h = new Date().getHours();
    const part = h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
    const name = (state.profile && state.profile.name || "").split(" ")[0];
    $("#greeting").textContent = name ? `${part}, ${name}` : part;
    $("#me-name").textContent = state.profile && state.profile.name || "Set your name in Memory";
    $("#avatar").textContent = name ? name[0].toUpperCase() : "?";
  };
  const addStep = (text, cls) => {
    const li = document.createElement("li"); if (cls) li.className = cls; li.textContent = text;
    $("#steps").appendChild(li); li.scrollIntoView({block: "nearest"});
  };

  // ---- navigation ----------------------------------------------------------------------
  document.querySelectorAll(".nav").forEach(b => b.onclick = () => {
    document.querySelectorAll(".nav").forEach(x => x.classList.toggle("on", x === b));
    document.querySelectorAll(".view").forEach(v => v.classList.toggle("on", v.id === "view-" + b.dataset.view));
    if (b.dataset.view === "activity") loadState();
  });

  // ---- running goals -------------------------------------------------------------------
  const run = async goal => {
    goal = (goal || "").trim(); if (!goal || !api()) return;
    $("#goal").value = "";
    const id = await api().run(goal);
    if (!id) return;
  };
  $("#composer").onsubmit = e => { e.preventDefault(); run($("#goal").value); };
  document.querySelectorAll(".chip").forEach(c => c.onclick = () => { $("#goal").value = c.dataset.goal; $("#goal").focus(); });
  $("#stop").onclick = () => api() && api().stop();

  // ---- voice: click to start, click again to send (no holding needed) ------------------
  let listening = false;
  const toggleMic = async () => {
    if (!api()) return;
    if (!listening) {
      listening = true; $("#mic").classList.add("on"); setState("listening", "Listening... click again when done");
      try { await api().mic_start(); } catch (e) { listening = false; $("#mic").classList.remove("on"); toast("Microphone not available", true); setState("idle", "Ready"); }
    } else {
      listening = false; $("#mic").classList.remove("on"); setState("thinking", "Understanding...");
      const text = await api().mic_stop();
      if (modal.wid) { voiceAnswer(text); return; }
      if (text) { $("#goal").value = text; run(text); } else { setState("idle", "Ready"); toast("I didn't catch that. Try again."); }
    }
  };
  $("#mic").onclick = toggleMic;
  addEventListener("keydown", e => { if (e.key === "F9") { e.preventDefault(); toggleMic(); } });

  // Spoken answers to an open dialog, so ORION can be used without a mouse.
  const voiceAnswer = text => {
    const t = (text || "").toLowerCase().trim();
    if (!t) { toast("I didn't catch that. Click the mic and try again."); return; }
    if (modal.kind === "ask") { answer(text); return; }
    if (modal.kind === "confirm") {
      if (/\b(no|nope|don't|do not|cancel|stop|deny|reject|wait)\b/.test(t)) return answer(false);
      if (/\b(yes|yeah|yep|approve|approved|go ahead|do it|confirm|sure|okay|ok|send it|submit)\b/.test(t)) return answer(true);
      toast(`Heard "${text}". Say "yes" to approve or "no" to cancel.`); return;
    }
    if (modal.kind === "choose") {
      if (/\b(neither|none|cancel|no)\b/.test(t)) return answer(null);
      const opts = [...$("#modal-actions").children].slice(1).map(b => b.textContent.toLowerCase());
      const ord = ["first", "second", "third", "fourth"].findIndex(w => t.includes(w));
      let i = ord >= 0 && ord < opts.length ? ord : opts.findIndex(o => o.split(/\W+/).some(w => w.length > 3 && t.includes(w)));
      if (i >= 0) return answer(i);
      toast(`Heard "${text}". Say an option, "the first one", or "neither".`);
    }
  };

  // ---- dialogs: approvals, questions, choices ------------------------------------------
  const modal = {wid: null, kind: null};
  const openModal = (kind, wid, title, body, buttons, input) => {
    modal.wid = wid; modal.kind = kind;
    $("#modal-title").textContent = title; $("#modal-body").textContent = body || "";
    $("#modal-body").hidden = !body; $("#modal-input").hidden = !input; $("#modal-text").value = "";
    const acts = $("#modal-actions"); acts.innerHTML = "";
    for (const [label, cls, value] of buttons) {
      const b = document.createElement("button"); b.textContent = label; if (cls) b.className = cls;
      b.onclick = () => answer(value === "__text__" ? $("#modal-text").value : value); acts.appendChild(b);
    }
    $("#modal").hidden = false; setState("waiting", "Waiting for you");
    (input ? $("#modal-text") : acts.lastChild).focus();
  };
  const answer = v => { if (!modal.wid) return; api().answer(modal.wid, v); closeModal(); setState("acting", "Working"); };
  const closeModal = () => { $("#modal").hidden = true; modal.wid = null; };
  $("#modal-text").addEventListener("keydown", e => { if (e.key === "Enter") answer($("#modal-text").value); });

  // ---- events from the backend ---------------------------------------------------------
  const onEvent = e => {
    switch (e.kind) {
      case "task_start":
        $("#live").hidden = false; $("#plan").innerHTML = ""; $("#steps").innerHTML = ""; $("#result").hidden = true;
        $("#liveview").hidden = true;
        $("#thought").textContent = ""; $("#task-title").textContent = e.goal.length > 80 ? e.goal.slice(0, 77) + "..." : e.goal;
        planDone = 0; t0 = Date.now(); clearInterval(timer);
        timer = setInterval(() => $("#task-time").textContent = Math.round((Date.now() - t0) / 1000) + " s", 500);
        setState("thinking", "Planning"); break;
      case "plan":
        $("#plan-src").textContent = e.source;
        $("#plan").innerHTML = e.plan.map(p => `<li>${esc(p)}</li>`).join(""); setState("acting", "Working"); break;
      case "thinking":
        $("#thought").textContent = e.thought ? "› " + e.thought : "";
        setState("acting", `Step ${e.n}: ${e.tool}`); break;
      case "step": {
        addStep(e.text, e.ok ? "" : "bad");
        const items = $("#plan").children;
        if (e.ok && planDone < items.length - 1) items[planDone++].classList.add("done");
        break; }
      case "confirm":
        openModal("confirm", e.id, e.action, e.consequence, [["Don't do it", "no", false], ["Approve", "yes", true]]); break;
      case "choose":
        openModal("choose", e.id, e.action, e.consequence,
                  [["Neither", "no", null], ...e.options.map((o, i) => [o, "", i])]); break;
      case "ask":
        openModal("ask", e.id, e.question, "", [["Skip", "no", ""], ["Answer", "yes", "__text__"]], true); break;
      case "dialog_closed": if (modal.wid === e.id) closeModal(); break;
      case "listening": break;
      case "heard": if (e.text) toast("Heard: " + e.text); break;
      case "stopping": closeModal(); setState("error", "Stopping..."); break;
      case "task_end": {
        clearInterval(timer);
        const ok = e.status === "done";
        if (ok) [...$("#plan").children].forEach(li => li.classList.add("done"));
        const r = $("#result"); r.hidden = false; r.className = "result" + (ok ? "" : " bad");
        r.textContent = (ok ? "" : ({cancelled: "Stopped. ", stopped: "Paused: ", failed: "Not finished: "}[e.status] || "")) + e.summary;
        $("#thought").textContent = ""; $("#task-time").textContent = e.seconds + " s";
        setState(ok ? "success" : "error", ok ? "Done" : "Needs attention");
        setTimeout(() => { if (["success", "error"].includes(document.body.dataset.state)) setState("idle", "Ready"); }, 9000);
        break; }
      case "live":
        $("#liveview").hidden = false; $("#lv-img").src = "data:image/jpeg;base64," + e.jpeg;
        $("#lv-title").textContent = e.title.length > 60 ? e.title.slice(0, 57) + "..." : e.title; break;
      case "hotkey": $("#hotkey-hint").textContent = e.ok ? "Ctrl+Alt+End stops everything" : "Hotkey unavailable: use STOP"; break;
      case "error": toast(e.message, true); break;
    }
  };
  window.orion = {onEvent};

  // ---- memory, settings, activity ------------------------------------------------------
  const loadState = async () => {
    if (!api()) return;
    state = await api().get_state(); greet();
    $("#m-name").value = state.profile.name || ""; $("#m-facts").value = state.profile.facts || "";
    $("#v-on").checked = state.settings.voice; $("#s-ask").checked = state.settings.ask_every_change;
    $("#v-rate").value = state.settings.voice_rate; $("#v-rate-val").textContent = Number(state.settings.voice_rate).toFixed(2) + "×";
    $("#s-model").value = state.settings.model;
    $("#history").innerHTML = state.history.length ? state.history.map(h =>
      `<div class="hist"><div><span class="g">${esc(h.goal)}</span><span class="badge ${esc(h.status)}">${esc(h.status)}</span>
       <span class="dim small"> ${esc(h.when)} &middot; ${esc(h.seconds)} s</span></div><div class="s">${esc(h.summary)}</div></div>`).join("")
      : `<p class="dim">Nothing yet. Ask ORION to do something on the Home screen.</p>`;
  };
  $("#m-save").onclick = async () => { await api().save_profile($("#m-name").value, $("#m-facts").value); $("#m-saved").textContent = "Saved"; loadState(); setTimeout(() => $("#m-saved").textContent = "", 2500); };
  // ---- voice picker --------------------------------------------------------------------
  let voices = [];
  const renderVoices = () => {
    const fam = $("#v-family").value, acc = $("#v-accent").value, gen = $("#v-gender").value;
    const list = voices.filter(v => (!fam || v.family === fam) && (!acc || v.accent === acc) && (!gen || v.gender === gen));
    $("#voices").innerHTML = list.length ? list.map(v => `
      <div class="vcard ${v.id === state.settings.voice_id ? "on" : ""}" data-id="${esc(v.id)}" title="Use this voice">
        <button class="play" data-id="${esc(v.id)}" title="Preview">&#9654;</button>
        <div><div class="vn">${esc(v.name)}</div><div class="vm">${esc([v.accent, v.gender].filter(Boolean).join(" · "))}</div></div>
        <span class="tag">${esc(v.family)}</span></div>`).join("") : `<p class="dim">No voices match.</p>`;
  };
  const loadVoices = async () => {
    if (voices.length || !api()) return renderVoices();
    voices = await api().list_voices();
    const accents = [...new Set(voices.map(v => v.accent).filter(Boolean))];
    $("#v-accent").innerHTML = `<option value="">Any accent</option>` + accents.map(a => `<option>${esc(a)}</option>`).join("");
    renderVoices();
  };
  $("#voices").addEventListener("click", async e => {
    const play = e.target.closest(".play"), card = e.target.closest(".vcard");
    if (play) { e.stopPropagation(); api().preview_voice(play.dataset.id, Number($("#v-rate").value)); return; }
    if (card) {
      state.settings = await api().set_setting("voice_id", card.dataset.id);
      renderVoices(); api().preview_voice(card.dataset.id, Number($("#v-rate").value));
      toast("Voice set to " + card.querySelector(".vn").textContent);
    }
  });
  ["#v-family", "#v-accent", "#v-gender"].forEach(s => $(s).onchange = renderVoices);
  $("#v-rate").oninput = e => $("#v-rate-val").textContent = Number(e.target.value).toFixed(2) + "×";
  $("#v-rate").onchange = async e => { state.settings = await api().set_setting("voice_rate", Number(e.target.value)); };
  $("#v-on").onchange = e => api().set_setting("voice", e.target.checked);
  document.querySelector('.nav[data-view="voice"]').addEventListener("click", loadVoices);
  $("#s-ask").onchange = e => api().set_setting("ask_every_change", e.target.checked);
  $("#s-model").onchange = e => api().set_setting("model", e.target.value.trim());
  $("#s-workspace").onclick = () => api().open_workspace();
  addEventListener("pywebviewready", loadState);
  if (api()) loadState();
  greet();
})();
