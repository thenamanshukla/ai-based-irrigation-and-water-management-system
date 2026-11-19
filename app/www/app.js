// Irrigation phone app. Talks only to the hub API on the Pi; shows nothing it did not receive.
(function () {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const Cap = window.Capacitor;
  const Plugins = (Cap && Cap.Plugins) || {};
  const isNative = !!(Cap && Cap.isNativePlatform && Cap.isNativePlatform());

  // ---------------------------------------------------------------- settings kept on the phone
  const store = {
    get(k, d) { try { const v = localStorage.getItem("irr_" + k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("irr_" + k, v); } catch (e) { /* storage off: keep in memory only */ } },
  };
  const S = {
    hub: store.get("hub", "http://192.168.4.1:8080"),
    lang: store.get("lang", "en"),
    pin: store.get("pin", ""),
    notify: store.get("notify", "1") === "1",
    lastAlertTs: store.get("last_alert_ts", ""),
  };

  let tab = "home";
  let status = null;          // last /api/status
  let reachable = null;       // true, false or null (not tried yet)
  let pollTimer = null;
  let pendingAction = null;   // action waiting for the PIN sheet

  // ---------------------------------------------------------------- text
  const T = (k) => (I18N[S.lang] && I18N[S.lang][k]) || I18N.en[k] || k;
  function reasonText(r) {
    const map = I18N[S.lang].reasons;
    for (const key of Object.keys(map)) {
      if (r.indexOf(key) !== -1) {
        const pct = r.match(/(\d+)%/);
        return map[key] + (pct ? " (" + pct[1] + "%)" : "");
      }
    }
    return r;                 // unknown reason: show the hub's own words
  }
  const alertText = (a) => I18N[S.lang].alert_kinds[a.kind] || a.message;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 0) => (v === null || v === undefined || isNaN(v) ? "–" : Number(v).toLocaleString(S.lang === "hi" ? "hi-IN" : "en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const parseTs = (ts) => { const m = /^(\d+)-(\d+)-(\d+) (\d+):(\d+):(\d+)$/.exec(ts || ""); return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : null; };
  function when(ts) {
    const d = parseTs(ts);
    if (!d) return ts || "";
    return d.toLocaleString(S.lang === "hi" ? "hi-IN" : "en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  }
  function ago(min) {
    if (min === undefined || min === null) return "";
    return min < 1 ? T("just_now") : fmt(min) + " " + T("min_ago");
  }

  function applyText() {
    document.documentElement.lang = S.lang;
    $$("[data-t]").forEach((el) => { el.textContent = T(el.dataset.t); });
    $$("#langSeg button").forEach((b) => b.classList.toggle("on", b.dataset.lang === S.lang));
    setLink();
  }

  // ---------------------------------------------------------------- network
  async function api(path, opts = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), opts.timeout || 8000);
    try {
      const res = await fetch(S.hub.replace(/\/+$/, "") + path, {
        method: opts.body ? "POST" : "GET",
        headers: opts.body ? { "Content-Type": "application/json" } : undefined,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
        signal: ctrl.signal, cache: "no-store",
      });
      let data = {};
      try { data = await res.json(); } catch (e) { /* empty body */ }
      return { code: res.status, data };
    } finally { clearTimeout(timer); }
  }

  function setLink() {
    const el = $("#linkState");
    const live = !!(status && status.field_online && status.field && status.field.age_min < 30);
    el.classList.toggle("ok", reachable === true && live);
    el.classList.toggle("bad", reachable === false || !!(status && status.field && !live));
    let txt = "";
    if (reachable === false) txt = T("offline_title");
    else if (status && status.field) {
      txt = (live ? T("field_online") : T("field_offline")) + ", " + T("updated") + " " + ago(status.field.age_min);
    } else if (status) txt = T("no_data");
    $("#linkText").textContent = txt;
  }

  async function refresh() {
    try {
      const r = await api("/api/status");
      if (r.code !== 200) throw new Error("status " + r.code);
      status = r.data;
      reachable = true;
      if (status.farm_name) $("#farmName").textContent = status.farm_name;
      notifyNewAlerts(status.alerts || []);
    } catch (e) {
      reachable = false;
    }
    setLink();
    if (tab === "home") renderHome();
    if (tab === "trends") renderTrends();
    if (tab === "water") renderWaterMeta();
  }

  function startPolling() {
    stopPolling();
    refresh();
    pollTimer = setInterval(refresh, 20000);
  }
  function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

  // ---------------------------------------------------------------- home
  function offlineCard() {
    return `<div class="card empty">
      <h2>${T("offline_title")}</h2><p class="sub">${T("offline_sub")}</p>
      <div class="row"><button class="secondary" data-go="settings">${T("setup")}</button>
      <button class="primary small" data-retry>${T("retry")}</button></div>
      <p class="meta">${esc(S.hub)}</p></div>`;
  }

  function planCard(d) {
    if (!d) {
      return `<div class="card plan"><div class="label">${T("today")}</div>
        <div class="verb" style="color:var(--ink-soft)">${T("plan_pending")}</div>
        <p class="meta">${T("plan_pending_sub")}</p></div>`;
    }
    const verb = { water: T("act_water"), wait: T("act_wait"), blocked: T("act_blocked") }[d.action] || d.action;
    const mins = d.action === "water" ? `<small>${fmt(d.minutes)} ${T("minutes")}</small>` : "";
    const reasons = (d.reasons || []).map((r) => `<li>${esc(reasonText(r))}</li>`).join("");
    const litres = d.action === "water" && d.litres ? `<p class="meta">≈ ${fmt(d.litres)} ${T("litres")}</p>` : "";
    return `<div class="card plan ${esc(d.action)}"><div class="label">${T("today")}</div>
      <div class="verb">${esc(verb)}${mins}</div>${litres}
      ${reasons ? `<ul class="reasons" aria-label="${T("why")}">${reasons}</ul>` : ""}</div>`;
  }

  function storageCard(f, d, cap) {
    const pct = cap ? Math.max(0, Math.min(100, (100 * f.tank_l) / cap)) : 0;
    const ticks = Array.from({ length: 9 }, (_, i) => `<i style="bottom:${(i + 1) * 10}%"></i>`).join("");
    const days = d && d.days_left !== undefined && d.days_left !== null && isFinite(d.days_left)
      ? `<div class="big">${fmt(d.days_left, d.days_left < 10 ? 1 : 0)}<small>${T("days_left")}</small></div>`
      : `<div class="fig"><div class="v" style="color:var(--ink-soft)">${T("days_unknown")}</div></div>`;
    return `<div class="card"><div class="storage">
      <div class="vessel" role="img" aria-label="${T("tank")} ${fmt(pct)}%">
        <div class="fill ${pct < 20 ? "low" : ""}" style="height:${pct}%"></div>
        <div class="scale">${ticks}</div>
        <span class="pct ${pct < 12 ? "dark" : ""}">${fmt(pct)}%</span></div>
      <div class="figs">
        ${days}
        <div class="fig"><div class="label">${T("tank")}</div><div class="v">${fmt(f.tank_l)} / ${fmt(cap)} ${T("litres")}</div></div>
        <div class="fig"><div class="label">${T("pond")}</div><div class="v">${fmt(f.pond_l)} ${T("litres")}</div></div>
      </div></div></div>`;
  }

  function soilCard(f, h) {
    const fc = h ? h.field_capacity_pct : null, trig = h ? h.trigger_pct : null;
    const lo = 0, hi = Math.max(50, (fc || 0) + 10);
    const pos = (v) => Math.max(0, Math.min(100, (100 * (v - lo)) / (hi - lo)));
    const marks = (trig !== null ? `<div class="mark lo" style="left:${pos(trig)}%"><span>${T("trigger")} ${fmt(trig)}%</span></div>` : "") +
      (fc !== null ? `<div class="mark" style="left:${pos(fc)}%"><span>${T("full")} ${fmt(fc)}%</span></div>` : "");
    const m = f.soil_moisture_pct;
    return `<div class="card"><h2>${T("soil")}</h2>
      <div class="gauge">${marks}${m !== null ? `<div class="now" style="left:${pos(m)}%"><b>${fmt(m, 1)}%</b></div>` : ""}</div>
      <div class="chips">
        <div class="chip"><div class="label">${T("air")}</div><div class="v">${fmt(f.air_temp_c, 1)}°C</div></div>
        <div class="chip"><div class="label">${T("rain")}</div><div class="v">${f.raining ? T("raining") : T("dry")}</div></div>
        <div class="chip"><div class="label">${T("valve")}</div><div class="v">${f.valve === "open" ? T("open") : T("closed")}</div></div>
      </div></div>`;
  }

  function pipeCard(p) {
    const map = { normal: ["good", T("pipe_normal")], leak: ["bad", T("pipe_leak")], clog: ["warn", T("pipe_clog")] };
    const [cls, txt] = map[p] || ["", T("pipe_unknown")];
    return `<div class="card"><div class="label">${T("pipes")}</div><p class="state ${cls}">${esc(txt)}</p></div>`;
  }

  function alertsCard(list) {
    const kindClass = (k) => (k === "leak" || k === "field_offline" || k === "command_failed" ? "bad" : k === "field_online" ? "good" : "");
    const items = list.map((a) => `<li class="${kindClass(a.kind)}">${esc(alertText(a))}<time>${esc(when(a.ts))}</time></li>`).join("");
    return `<div class="card"><h2>${T("alerts")}</h2>
      ${items ? `<ul class="alerts">${items}</ul>` : `<p class="sub" style="margin:0">${T("no_alerts")}</p>`}</div>`;
  }

  let histCache = null;     // thresholds for the soil gauge, refreshed with trends
  async function loadThresholds() {
    if (histCache) return histCache;
    try { const r = await api("/api/history?hours=1"); if (r.code === 200) histCache = r.data; } catch (e) { /* ignore */ }
    return histCache;
  }

  async function renderHome() {
    const body = $("#homeBody");
    if (reachable === false) { body.innerHTML = offlineCard(); return; }
    if (!status) { body.innerHTML = ""; return; }
    const f = status.field;
    let html = planCard(status.today);
    if (!f) {
      html += `<div class="card empty"><h2>${T("no_data")}</h2><p class="sub">${T("no_data_sub")}</p></div>`;
    } else {
      const h = await loadThresholds();
      html += storageCard(f, status.today, status.tank_capacity_l) + soilCard(f, h) + pipeCard(status.pipe_status);
    }
    html += alertsCard(status.alerts || []);
    body.innerHTML = html;
  }

  // ---------------------------------------------------------------- trends
  function lineChart(points, key, opts) {
    const W = 340, H = 170, L = 34, R = 8, Tp = 10, B = 22;
    const pts = points.filter((p) => p[key] !== null && p[key] !== undefined);
    if (pts.length < 2) return `<p class="sub">${T("trends_empty")}</p>`;
    const t0 = parseTs(pts[0].ts).getTime(), t1 = parseTs(pts[pts.length - 1].ts).getTime() || t0 + 1;
    const vals = pts.map((p) => p[key]);
    let lo = Math.min(...vals, ...(opts.extra || [])), hi = Math.max(...vals, ...(opts.extra || []));
    if (opts.zero) lo = 0;
    if (hi - lo < 1) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.08; lo = opts.zero ? 0 : lo - pad; hi += pad;
    const x = (ts) => L + ((parseTs(ts).getTime() - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => Tp + (1 - (v - lo) / (hi - lo)) * (H - Tp - B);
    let g = "";
    for (let i = 0; i <= 3; i++) {
      const v = lo + ((hi - lo) * i) / 3, yy = y(v);
      g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}"/><text class="ax" x="${L - 4}" y="${yy + 3}" text-anchor="end">${fmt(v)}</text>`;
    }
    g += `<text class="ax" x="${L}" y="${H - 6}">${esc(when(pts[0].ts))}</text>`;
    g += `<text class="ax" x="${W - R}" y="${H - 6}" text-anchor="end">${esc(when(pts[pts.length - 1].ts))}</text>`;
    let band = "";
    if (opts.band) {
      const [a, b] = opts.band;
      band = `<rect class="band" x="${L}" width="${W - L - R}" y="${y(b)}" height="${Math.max(0, y(a) - y(b))}"/>`;
    }
    let valve = "";
    if (opts.valve) {
      pts.forEach((p, i) => {
        if (p.valve && pts[i + 1]) valve += `<rect class="valve" x="${x(p.ts)}" width="${Math.max(1, x(pts[i + 1].ts) - x(p.ts))}" y="${Tp}" height="${H - Tp - B}"/>`;
      });
    }
    const d = pts.map((p, i) => (i ? "L" : "M") + x(p.ts).toFixed(1) + " " + y(p[key]).toFixed(1)).join(" ");
    const area = opts.area ? `<path class="lineT" d="${d} L${x(pts[pts.length - 1].ts).toFixed(1)} ${y(lo)} L${L} ${y(lo)} Z" style="stroke:none"/>` : "";
    const line = `<path class="${opts.area ? "lineT" : "lineM"}" style="fill:none" d="${d}"/>`;
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">${band}${valve}${g}${area}${line}</svg>`;
  }

  async function renderTrends() {
    const body = $("#trendsBody");
    if (reachable === false) { body.innerHTML = offlineCard(); return; }
    let h, dec;
    try {
      const [a, b] = await Promise.all([api("/api/history?hours=48"), api("/api/decisions?days=14")]);
      h = a.data; dec = b.data.decisions || [];
      histCache = h;
    } catch (e) { reachable = false; setLink(); body.innerHTML = offlineCard(); return; }
    const pts = h.points || [];
    const days = dec.map((d) => {
      const verb = { water: T("act_water"), wait: T("act_wait"), blocked: T("act_blocked") }[d.action] || d.action;
      const dt = new Date(d.date + "T00:00:00").toLocaleDateString(S.lang === "hi" ? "hi-IN" : "en-IN", { day: "numeric", month: "short" });
      const first = (d.reasons || [])[0];
      return `<li><span class="d">${esc(dt)}</span><span>${first ? esc(reasonText(first)) : ""}</span>
        <span class="pill ${esc(d.action)}">${esc(verb)}${d.action === "water" ? " " + fmt(d.minutes) + "′" : ""}</span></li>`;
    }).join("");
    body.innerHTML = `
      <div class="card"><h2>${T("trends_moisture")}</h2>
        ${lineChart(pts, "moisture", { band: [h.trigger_pct, h.field_capacity_pct], extra: [h.trigger_pct, h.field_capacity_pct], valve: true })}</div>
      <div class="card"><h2>${T("trends_tank")}</h2>
        ${lineChart(pts, "tank_l", { zero: true, area: true, extra: status && status.tank_capacity_l ? [status.tank_capacity_l] : [] })}</div>
      <div class="card"><h2>${T("trends_days")}</h2>
        ${days ? `<ul class="days">${days}</ul>` : `<p class="sub" style="margin:0">${T("plan_pending_sub")}</p>`}</div>`;
  }

  // ---------------------------------------------------------------- water
  let minutes = 15;
  function renderWaterMeta() {
    $("#minVal").textContent = fmt(minutes);
    const lw = status && status.last_watering;
    $("#lastWatering").textContent = lw
      ? `${T("last_watering")}: ${when(lw.ts)}, ${fmt(lw.minutes)} ${T("minutes")}, ${lw.source === "manual" ? T("by_hand") : T("by_plan")}`
      : "";
    if (status && status.manual_pending && !$("#waterMsg").textContent) setMsg("#waterMsg", T("water_pending"), "ok");
  }
  function setMsg(sel, text, kind) {
    const el = $(sel); el.textContent = text || ""; el.className = "msg" + (kind ? " " + kind : "");
  }

  function errText(r) {
    const e = r && r.data && r.data.error;
    if (e === "minutes_range" || e === "minutes_required") return T("err_minutes");
    if (e === "litres_range" || e === "litres_required") return T("err_litres");
    return T("err_generic") + (r && r.code ? " (" + r.code + ")" : "");
  }

  async function guarded(path, body, msgSel, okText) {
    let r;
    try { r = await api(path, { body: Object.assign({}, body, { pin: S.pin }) }); }
    catch (e) { setMsg(msgSel, T("conn_fail") + " " + S.hub, "err"); return; }
    if (r.code === 403) {
      pendingAction = () => guarded(path, body, msgSel, okText);
      openPin(S.pin ? T("pin_wrong") : "");
      return;
    }
    if (r.code === 200 && r.data.ok) { setMsg(msgSel, okText, "ok"); refresh(); }
    else setMsg(msgSel, errText(r), "err");
  }

  // ---------------------------------------------------------------- ask (Llama on the hub)
  function renderAsk() {
    $("#askSugg").innerHTML = T("ask_examples").map((q) => `<button data-q="${esc(q)}">${esc(q)}</button>`).join("");
  }

  async function ask() {
    const q = $("#askInput").value.trim();
    if (!q) return setMsg("#askMsg", T("ask_empty"), "err");
    const btn = $("#askBtn");
    btn.disabled = true;
    setMsg("#askMsg", T("ask_wait"));
    let r;
    try { r = await api("/api/ask", { body: { question: q, lang: S.lang }, timeout: 200000 }); }
    catch (e) { btn.disabled = false; return setMsg("#askMsg", T("conn_fail") + " " + S.hub, "err"); }
    btn.disabled = false;
    if (r.code === 503) return setMsg("#askMsg", T("ask_missing"), "err");
    if (r.code !== 200 || !r.data.ok) return setMsg("#askMsg", errText(r), "err");
    setMsg("#askMsg", "");
    $("#askAnswer").textContent = r.data.answer;
    const sp = r.data.speed;
    $("#askMeta").textContent = `${T("ask_meta")} ${fmt(r.data.seconds, 1)} s` + (sp ? `, ${fmt(sp.decode, 1)} ${T("ask_speed")}` : "");
    $("#askOut").hidden = false;
  }

  // ---------------------------------------------------------------- PIN sheet
  function openPin(msg) {
    $("#pinAsk").value = "";
    setMsg("#pinAskMsg", msg, msg ? "err" : "");
    $("#pinSheet").hidden = false;
    setTimeout(() => $("#pinAsk").focus(), 50);
  }
  function closePin() { $("#pinSheet").hidden = true; pendingAction = null; }

  // ---------------------------------------------------------------- notifications
  async function notifyNewAlerts(list) {
    if (!list.length) return;
    const newest = list[0].ts;
    const fresh = S.lastAlertTs ? list.filter((a) => a.ts > S.lastAlertTs) : [];
    S.lastAlertTs = newest; store.set("last_alert_ts", newest);
    if (!S.notify || !fresh.length || !Plugins.LocalNotifications) return;
    try {
      await Plugins.LocalNotifications.schedule({
        notifications: fresh.slice(0, 3).map((a, i) => ({
          id: Math.floor(Date.now() / 1000) % 100000 + i, title: status && status.farm_name || "Irrigation", body: alertText(a),
        })),
      });
    } catch (e) { /* permission refused: stay silent */ }
  }
  async function askNotifyPermission() {
    if (!Plugins.LocalNotifications) return true;
    try { const p = await Plugins.LocalNotifications.requestPermissions(); return p.display === "granted"; }
    catch (e) { return false; }
  }

  // ---------------------------------------------------------------- tabs and events
  function show(name) {
    tab = name;
    $$(".view").forEach((v) => { v.hidden = v.dataset.view !== name; });
    $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
    window.scrollTo(0, 0);
    if (name === "home") renderHome();
    if (name === "trends") renderTrends();
    if (name === "water") renderWaterMeta();
    if (name === "ask") renderAsk();
    if (name === "settings") { $("#hubInput").value = S.hub; $("#pinInput").value = S.pin; $("#notifyToggle").checked = S.notify; }
  }

  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("button");
    if (!t) return;
    if (t.dataset.tab) return show(t.dataset.tab);
    if (t.dataset.go) return show(t.dataset.go);
    if (t.dataset.q) { $("#askInput").value = t.dataset.q; return ask(); }
    if (t.hasAttribute("data-retry")) { $("#homeBody").innerHTML = ""; return refresh(); }
    if (t.dataset.step) {
      minutes = Math.max(5, Math.min(90, minutes + Number(t.dataset.step)));
      return renderWaterMeta();
    }
    if (t.dataset.lang) { S.lang = t.dataset.lang; store.set("lang", S.lang); applyText(); return show(tab); }
  });

  $("#waterBtn").addEventListener("click", () => {
    if (!(minutes >= 1 && minutes <= 90)) return setMsg("#waterMsg", T("err_minutes"), "err");
    guarded("/api/water", { minutes }, "#waterMsg", T("water_sent"));
  });
  $("#askBtn").addEventListener("click", ask);
  $("#pondBtn").addEventListener("click", () => {
    const v = parseFloat($("#pondInput").value);
    if (!(v >= 0)) return setMsg("#pondMsg", T("err_litres"), "err");
    guarded("/api/pond", { litres: v }, "#pondMsg", T("pond_saved"));
  });

  $("#testBtn").addEventListener("click", async () => {
    const addr = normaliseHub($("#hubInput").value);
    setMsg("#hubMsg", T("checking"));
    const old = S.hub; S.hub = addr;
    try {
      const r = await api("/api/health", { timeout: 5000 });
      if (r.code === 200 && r.data.ok) setMsg("#hubMsg", `${T("conn_ok")} ${r.data.name}`, "ok");
      else throw new Error();
    } catch (e) { setMsg("#hubMsg", `${T("conn_fail")} ${addr}`, "err"); }
    S.hub = old;
  });
  $("#saveHubBtn").addEventListener("click", () => {
    S.hub = normaliseHub($("#hubInput").value); $("#hubInput").value = S.hub;
    store.set("hub", S.hub); histCache = null; status = null; reachable = null;
    setMsg("#hubMsg", T("saved"), "ok");
    refresh();
  });
  function normaliseHub(v) {
    v = (v || "").trim().replace(/\/+$/, "");
    if (!v) return S.hub;
    if (!/^https?:\/\//i.test(v)) v = "http://" + v;
    if (!/:\d+$/.test(v.replace(/^https?:\/\//i, ""))) v += ":8080";
    return v;
  }
  $("#savePinBtn").addEventListener("click", () => { S.pin = $("#pinInput").value.trim(); store.set("pin", S.pin); });
  $("#notifyToggle").addEventListener("change", async (e) => {
    let on = e.target.checked;
    if (on) on = await askNotifyPermission();
    e.target.checked = on; S.notify = on; store.set("notify", on ? "1" : "0");
  });

  $("#pinCancel").addEventListener("click", closePin);
  $("#pinOk").addEventListener("click", () => {
    S.pin = $("#pinAsk").value.trim(); store.set("pin", S.pin);
    const act = pendingAction; $("#pinSheet").hidden = true; pendingAction = null;
    if (act) act();
  });
  $("#pinAsk").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#pinOk").click(); });

  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  if (Plugins.App) {
    Plugins.App.addListener("backButton", () => {
      if (!$("#pinSheet").hidden) return closePin();
      if (tab !== "home") return show("home");
      Plugins.App.exitApp();
    });
  }

  applyText();
  show("home");
  startPolling();
})();
