/* =====================================================================
   AI VISION X - dashboard logic
   Everything on screen comes from the Flask API (no fake numbers):
     /api/stats  /api/alerts  /api/tracks  /api/system  /api/videos
     POST /api/control/start | /api/control/stop | /api/settings | /api/upload
   ===================================================================== */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad = (n) => String(n).padStart(2, "0");
  const fmtUptime = (s) => `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;

  const PALETTE = ["#22d3ee", "#a78bfa", "#34d399", "#fbbf24", "#3b82f6", "#f472b6", "#f87171", "#2dd4bf"];
  const HAS_CHART = typeof window.Chart !== "undefined";

  const state = {
    view: "dashboard",
    source: "webcam",
    stats: null,
    backendUp: true,
    lastEventId: 0,
    unseenAlerts: 0,
    alertsLoaded: false,
    videos: [],
    statsKey: "",
  };

  /* ------------------------------------------------------------- api */
  async function api(path, options) {
    const res = await fetch(path, options);
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok) throw new Error(data.message || `Request failed (${res.status})`);
    return data;
  }
  const post = (path, body) => api(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });

  function toast(msg, kind = "ok", ms = 4200) {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    $("toasts").appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  function showBanner(msg, kind = "err") {
    const b = $("banner");
    if (!msg) { b.hidden = true; return; }
    b.className = `banner ${kind}`;
    b.textContent = msg;
    b.hidden = false;
  }

  /* ------------------------------------------------------- navigation */
  function setView(name) {
    state.view = name;
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
    $("app").classList.remove("menu-open");
    history.replaceState(null, "", `#${name}`);
    if (name === "alerts") { state.unseenAlerts = 0; updateBadge(); }
    if (name === "analytics") { ensureChartsB(); redrawCharts(true); }
    if (name === "tracking") pollTracks();
    if (name === "cameras") refreshVideos();
    window.scrollTo({ top: 0 });
    if (state.stats) renderStats(state.stats);
  }
  $$(".nav-item").forEach((n) => n.addEventListener("click", () => setView(n.dataset.view)));
  $$("[data-goto]").forEach((n) => n.addEventListener("click", () => setView(n.dataset.goto)));
  $("menuBtn").addEventListener("click", () => $("app").classList.toggle("menu-open"));
  $("scrim").addEventListener("click", () => $("app").classList.remove("menu-open"));

  /* ------------------------------------------------------------ clock */
  function tickClock() {
    const d = new Date();
    const date = d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
    const time = d.toLocaleTimeString("en-GB");
    $("clock").textContent = `${date} | ${time}`;
    $("vidClock").textContent = time;
  }
  setInterval(tickClock, 1000);
  tickClock();

  /* ----------------------------------------------------------- charts */
  const charts = {};
  const dark = { ticks: "#8da0c0", grid: "rgba(38,56,90,.55)" };

  function lineOptions() {
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { intersect: false, mode: "index" },
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: dark.ticks, maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: dark.ticks, precision: 0 }, grid: { color: dark.grid } },
      },
    };
  }
  function makeLine(id) {
    return new Chart($(id), {
      type: "line",
      data: { labels: [], datasets: [{ data: [], borderColor: "#22d3ee", borderWidth: 2, tension: 0.35, pointRadius: 0, fill: true,
        backgroundColor: (ctx) => {
          const { chart } = ctx; const a = chart.chartArea;
          if (!a) return "rgba(34,211,238,.15)";
          const g = chart.ctx.createLinearGradient(0, a.top, 0, a.bottom);
          g.addColorStop(0, "rgba(34,211,238,.35)"); g.addColorStop(1, "rgba(34,211,238,0)");
          return g;
        } }] },
      options: lineOptions(),
    });
  }

  function ensureChartsA() {
    if (!HAS_CHART || charts.dist) return;
    charts.dist = new Chart($("chartDist"), {
      type: "doughnut",
      data: { labels: [], datasets: [{ data: [], backgroundColor: PALETTE, borderColor: "#0e1729", borderWidth: 3 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, cutout: "66%",
        plugins: { legend: { position: "right", labels: { color: "#cdd9ef", boxWidth: 10, boxHeight: 10, usePointStyle: true } } },
      },
    });
    charts.time = makeLine("chartTime");
  }
  function ensureChartsB() {
    if (!HAS_CHART || charts.dist2) return;
    charts.dist2 = new Chart($("chartDist2"), {
      type: "bar",
      data: { labels: [], datasets: [{ data: [], backgroundColor: PALETTE, borderRadius: 6 }] },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, ticks: { color: dark.ticks, precision: 0 }, grid: { color: dark.grid } },
          y: { ticks: { color: "#cdd9ef" }, grid: { display: false } },
        },
      },
    });
    charts.time2 = makeLine("chartTime2");
  }

  /* minimal canvas fallbacks - used only if Chart.js could not be loaded (offline) */
  function fallbackLine(canvas, values) {
    const r = canvas.getBoundingClientRect(); const dpr = window.devicePixelRatio || 1;
    canvas.width = r.width * dpr; canvas.height = r.height * dpr;
    const c = canvas.getContext("2d"); c.scale(dpr, dpr); c.clearRect(0, 0, r.width, r.height);
    const max = Math.max(3, ...values); const W = r.width - 30, H = r.height - 24;
    c.strokeStyle = "rgba(38,56,90,.6)"; c.fillStyle = "#8da0c0"; c.font = "11px sans-serif";
    for (let i = 0; i <= 3; i++) { const y = 8 + (H * i) / 3; c.beginPath(); c.moveTo(26, y); c.lineTo(r.width, y); c.stroke(); c.fillText(String(Math.round(max - (max * i) / 3)), 2, y + 4); }
    if (values.length < 2) return;
    c.strokeStyle = "#22d3ee"; c.lineWidth = 2; c.beginPath();
    values.forEach((v, i) => { const x = 28 + (W * i) / (values.length - 1); const y = 8 + H - (H * v) / max; i ? c.lineTo(x, y) : c.moveTo(x, y); });
    c.stroke();
  }
  function fallbackBars(canvas, labels, values) {
    const r = canvas.getBoundingClientRect(); const dpr = window.devicePixelRatio || 1;
    canvas.width = r.width * dpr; canvas.height = r.height * dpr;
    const c = canvas.getContext("2d"); c.scale(dpr, dpr); c.clearRect(0, 0, r.width, r.height);
    const max = Math.max(1, ...values); const rowH = Math.min(36, (r.height - 8) / Math.max(labels.length, 1));
    c.font = "12px sans-serif";
    labels.forEach((l, i) => {
      const y = 6 + i * rowH; c.fillStyle = "#cdd9ef"; c.fillText(l, 4, y + rowH * 0.6);
      c.fillStyle = PALETTE[i % PALETTE.length]; c.fillRect(110, y + 4, ((r.width - 160) * values[i]) / max, rowH - 10);
      c.fillStyle = "#8da0c0"; c.fillText(String(values[i]), 116 + ((r.width - 160) * values[i]) / max, y + rowH * 0.6);
    });
  }

  function redrawCharts(force) {
    const s = state.stats; if (!s) return;
    const dist = Object.entries(s.class_distribution);
    const labels = dist.map((d) => d[0]); const values = dist.map((d) => d[1]);
    const tLabels = s.timeline.map((p) => p.t); const tValues = s.timeline.map((p) => p.objects);

    $("distEmpty").hidden = values.length > 0;

    if (HAS_CHART) {
      ensureChartsA();
      if (charts.dist) { charts.dist.data.labels = labels; charts.dist.data.datasets[0].data = values; charts.dist.update("none"); }
      if (charts.time) { charts.time.data.labels = tLabels; charts.time.data.datasets[0].data = tValues; charts.time.update("none"); }
      if (state.view === "analytics" && charts.dist2) {
        charts.dist2.data.labels = labels; charts.dist2.data.datasets[0].data = values; charts.dist2.update("none");
        charts.time2.data.labels = tLabels; charts.time2.data.datasets[0].data = tValues; charts.time2.update("none");
        if (force) { charts.dist2.resize(); charts.time2.resize(); }
      }
    } else {
      // Chart.js unavailable: DOM bars for the donut, tiny canvas drawings for the rest
      $("chartDist").hidden = true; $("distFallback").hidden = false;
      const max = Math.max(1, ...values);
      $("distFallback").innerHTML = values.length ? dist.map(([n, v], i) =>
        `<div class="fb-row"><span>${esc(n)}</span><div class="fb-bar"><i style="width:${(v / max) * 100}%;background:${PALETTE[i % PALETTE.length]}"></i></div><b>${v}</b></div>`).join("") : "";
      fallbackLine($("chartTime"), tValues);
      if (state.view === "analytics") { fallbackBars($("chartDist2"), labels, values); fallbackLine($("chartTime2"), tValues); }
    }
  }

  /* ----------------------------------------------------------- render */
  const STATUS = {
    live: ["live", "LIVE"], standby: ["standby", "STANDBY"], completed: ["done", "COMPLETED"], error: ["error", "ERROR"],
  };
  const catClass = (c) => `cat-${c || "object"}`;

  function renderStats(s) {
    state.stats = s;

    // status + model pills
    const [cls, label] = STATUS[s.status] || STATUS.standby;
    $("statusPill").className = `pill ${cls}`;
    $("statusText").textContent = label;
    const mp = $("modelPill");
    if (s.model_status === "ready") { mp.className = "pill pill-model ready"; $("modelText").textContent = `${s.model_name} · ${s.tracker}`; }
    else if (s.model_status === "error") { mp.className = "pill pill-model error"; $("modelText").textContent = "Model error"; }
    else { mp.className = "pill pill-model"; $("modelText").textContent = "Loading model…"; }
    $("sideModel").textContent = s.model_name;
    $("setModel").textContent = `${s.model_name} (${s.model_file})`;

    // banners
    if (s.model_status === "error") showBanner(`The AI model could not be loaded: ${s.model_error}. Check that yolo11n.pt is next to app.py and that ultralytics is installed.`);
    else if (s.model_status === "loading") showBanner("Loading the YOLO model… the Start button unlocks in a few seconds.", "info");
    else if (s.status === "error" && s.message) showBanner(s.message);
    else if (s.status === "completed") showBanner("The video file finished playing. Press Start to run it again.", "info");
    else showBanner("");

    // buttons
    const live = s.running, ready = s.model_status === "ready";
    [["startBtn", "stopBtn"], ["startBtn2", "stopBtn2"]].forEach(([a, b]) => { $(a).disabled = live || !ready; $(b).disabled = !live; });

    // live panel
    $("liveSource").textContent = s.source.label;
    $("liveBadge").hidden = !live;
    $("vidFps").hidden = !live;
    $("vidFps").textContent = `${s.fps.toFixed(1)} FPS`;

    // stat cards
    $("sTotal").textContent = s.total_detections;
    $("sInFrame").textContent = s.objects_in_frame;
    $("sTracks").textContent = s.active_tracks;
    $("sFps").textContent = s.fps.toFixed(1);
    $("sLatency").textContent = live ? `${s.latency_ms.toFixed(0)} ms / frame` : "— ms / frame";
    const fc = Object.entries(s.frame_counts).sort((a, b) => b[1] - a[1]).map(([n, c]) => `${c} ${n}`);
    $("sInFrameNote").textContent = fc.length ? fc.slice(0, 3).join(", ") : "nothing detected";

    // statistics list
    const dist = Object.entries(s.class_distribution);
    $("kFrames").textContent = s.frames_processed.toLocaleString();
    $("kRaw").textContent = s.raw_detections.toLocaleString();
    $("kTop").textContent = dist.length ? `${dist[0][0]} (${dist[0][1]})` : "—";
    $("kClasses").textContent = dist.length;
    $("kUptime").textContent = fmtUptime(s.uptime_s);
    $("kConf").textContent = s.settings.confidence.toFixed(2);

    // cameras view
    $("camSource").textContent = s.source.label;
    $("camStatus").textContent = label[0] + label.slice(1).toLowerCase();
    $("camFrames").textContent = s.frames_processed.toLocaleString();

    // detections view
    if (state.view === "detections") {
      $("detBody").innerHTML = s.current.length ? s.current.map((d) => `
        <tr class="${catClass(d.category)}"><td><span class="tag">${esc(d.class)}</span></td>
        <td>${esc(d.category)}</td><td class="mono">${d.id === null ? "pending" : "#" + d.id}</td>
        <td class="mono"><span class="conf-bar"><i style="width:${Math.round(d.confidence * 100)}%"></i></span>${(d.confidence * 100).toFixed(1)}%</td></tr>`).join("")
        : `<tr><td colspan="4" class="empty-cell">Nothing detected right now.</td></tr>`;
    }
    // analytics class table
    if (state.view === "analytics") {
      const names = new Set([...Object.keys(s.class_distribution), ...Object.keys(s.frame_counts)]);
      $("classBody").innerHTML = names.size ? [...names].map((n) =>
        `<tr><td><span class="tag">${esc(n)}</span></td><td class="mono">${s.class_distribution[n] || 0}</td><td class="mono">${s.frame_counts[n] || 0}</td></tr>`).join("")
        : `<tr><td colspan="3" class="empty-cell">No data yet.</td></tr>`;
    }

    // settings controls reflect server values unless the user is dragging
    if (document.activeElement !== $("confRange")) { $("confRange").value = s.settings.confidence; $("confVal").textContent = s.settings.confidence.toFixed(2); }
    if (document.activeElement !== $("imgszSelect")) $("imgszSelect").value = String(s.settings.imgsz);

    const key = JSON.stringify([s.class_distribution, s.timeline.length, s.timeline[s.timeline.length - 1]]) + state.view;
    if (key !== state.statsKey) { state.statsKey = key; redrawCharts(false); }
  }

  function renderEvents(list) {
    const row = (e) => `
      <div class="ev ${catClass(e.category)}${e.event_id > state.lastEventId && state.alertsLoaded ? " fresh" : ""}" title="${esc(e.source)}">
        <div class="ev-main">
          <div class="ev-title">${esc(e.class)} detected<small>${esc(e.category)}</small></div>
          <div class="ev-meta">Track ID #${e.track_id} · confidence ${(e.confidence * 100).toFixed(0)}%</div>
        </div>
        <div class="ev-time">${esc(e.time)}</div>
      </div>`;
    const empty = `<div class="empty">No events yet.<br>Start monitoring to see detections here.</div>`;
    $("eventsMini").innerHTML = list.length ? list.slice(0, 8).map(row).join("") : empty;
    $("eventsFull").innerHTML = list.length ? list.map(row).join("") : `<div class="empty">No events yet.</div>`;
  }

  function updateBadge() {
    const b = $("alertBadge");
    b.hidden = state.unseenAlerts <= 0;
    b.textContent = state.unseenAlerts > 99 ? "99+" : state.unseenAlerts;
  }

  function renderSystem(m) {
    const set = (key, pct, warn = true) => {
      const el = document.querySelector(`.gauge[data-key="${key}"]`);
      el.style.setProperty("--p", Math.min(Math.max(pct, 0), 100) / 100);
      el.classList.toggle("crit", warn && pct >= 90);
      el.classList.toggle("warn", warn && pct >= 75 && pct < 90);
    };
    $("gCpu").textContent = `${m.cpu_percent.toFixed(0)}%`;
    $("gCpuSub").textContent = `${m.cpu_cores} threads`;
    set("cpu", m.cpu_percent);

    $("gMem").textContent = `${m.memory_used_gb} GB`;
    $("gMemSub").textContent = `/ ${m.memory_total_gb} GB`;
    set("mem", m.memory_percent);

    $("gDisk").textContent = `${m.disk_percent.toFixed(0)}%`;
    $("gDiskSub").textContent = `${m.disk_used_gb} / ${m.disk_total_gb} GB`;
    set("disk", m.disk_percent);

    const scale = m.net_link_mbps || Math.max(100, m.net_peak_mbps);
    $("gNet").textContent = `${m.net_total_mbps.toFixed(m.net_total_mbps < 10 ? 1 : 0)} Mbps`;
    $("gNetSub").textContent = `↓${m.net_down_mbps.toFixed(1)}  ↑${m.net_up_mbps.toFixed(1)}`;
    set("net", (m.net_total_mbps / scale) * 100, false);
  }

  function renderTracks(tracks) {
    $("trackBody").innerHTML = tracks.length ? tracks.map((t) => `
      <tr class="${catClass(t.category)}"><td class="mono">#${t.id}</td><td><span class="tag">${esc(t.class)}</span></td>
      <td class="mono">${(t.confidence * 100).toFixed(1)}%</td><td class="mono">${esc(t.first_seen)}</td>
      <td class="mono">${t.duration_s.toFixed(1)} s</td><td class="mono">${t.frames}</td></tr>`).join("")
      : `<tr><td colspan="6" class="empty-cell">No active tracks.</td></tr>`;
  }

  /* ---------------------------------------------------------- polling */
  function backendStatus(ok) {
    if (ok === state.backendUp) return;
    state.backendUp = ok;
    if (!ok) showBanner("Lost connection to the AI VISION X backend. Is app.py still running in PowerShell?");
  }

  async function pollStats() {
    try { renderStats(await api("/api/stats")); backendStatus(true); } catch (_) { backendStatus(false); }
  }
  async function pollAlerts() {
    try {
      const { alerts } = await api("/api/alerts?limit=100");
      const newest = alerts.length ? alerts[0].event_id : 0;
      if (newest < state.lastEventId) state.lastEventId = 0;            // new session restarted numbering
      if (state.alertsLoaded && newest > state.lastEventId && state.view !== "alerts") {
        state.unseenAlerts += newest - state.lastEventId; updateBadge();
      }
      renderEvents(alerts);
      state.lastEventId = newest;
      state.alertsLoaded = true;
    } catch (_) { /* handled by stats poll */ }
  }
  async function pollSystem() {
    try { renderSystem(await api("/api/system")); } catch (_) { /* ignore */ }
  }
  async function pollTracks() {
    if (state.view !== "tracking") return;
    try { renderTracks((await api("/api/tracks")).tracks); } catch (_) { /* ignore */ }
  }
  async function refreshVideos() {
    try {
      state.videos = (await api("/api/videos")).videos;
      const sel = $("videoSelect"); const prev = sel.value;
      sel.innerHTML = state.videos.length ? state.videos.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("") : `<option value="">— no uploads yet —</option>`;
      if (state.videos.includes(prev)) sel.value = prev;
      $("videoList").innerHTML = state.videos.length ? state.videos.map((v) => `<div class="video-item"><svg class="ic"><use href="#i-film"/></svg>${esc(v)}</div>`).join("") : `<div class="empty">No videos uploaded yet.</div>`;
    } catch (_) { /* ignore */ }
  }

  setInterval(pollStats, 700);
  setInterval(pollAlerts, 1500);
  setInterval(pollSystem, 2000);
  setInterval(pollTracks, 1000);

  /* --------------------------------------------------------- controls */
  async function startMonitoring() {
    const body = state.source === "video"
      ? { source: "video", video: $("videoSelect").value }
      : { source: "webcam", camera_index: Number($("camSelect").value) };
    if (state.source === "video" && !body.video) { toast("Upload a video file first (Upload button).", "err"); return; }
    try {
      await post("/api/control/start", body);
      toast("Monitoring started.");
      state.lastEventId = 0; state.alertsLoaded = false; state.unseenAlerts = 0; updateBadge();
      pollStats();
    } catch (e) { toast(e.message, "err", 8000); }
  }
  async function stopMonitoring() {
    try { await post("/api/control/stop"); toast("Monitoring stopped."); pollStats(); }
    catch (e) { toast(e.message, "err"); }
  }
  ["startBtn", "startBtn2"].forEach((id) => $(id).addEventListener("click", startMonitoring));
  ["stopBtn", "stopBtn2"].forEach((id) => $(id).addEventListener("click", stopMonitoring));

  $$("#srcSeg button").forEach((b) => b.addEventListener("click", () => {
    state.source = b.dataset.src;
    $$("#srcSeg button").forEach((x) => x.classList.toggle("on", x === b));
    $("webcamGroup").hidden = state.source !== "webcam";
    $("videoGroup").hidden = state.source !== "video";
    if (state.source === "video") refreshVideos();
  }));

  $("videoFile").addEventListener("change", async (ev) => {
    const file = ev.target.files[0]; if (!file) return;
    const form = new FormData(); form.append("file", file);
    $("uploadState").textContent = `Uploading ${file.name}…`;
    try {
      const data = await api("/api/upload", { method: "POST", body: form });
      await refreshVideos();
      $("videoSelect").value = data.filename;
      $("uploadState").textContent = "Uploaded ✓";
      toast(`Uploaded ${data.filename}. Press Start to process it.`);
    } catch (e) { $("uploadState").textContent = ""; toast(e.message, "err", 7000); }
    ev.target.value = "";
  });

  // settings
  let confTimer;
  $("confRange").addEventListener("input", (e) => {
    $("confVal").textContent = Number(e.target.value).toFixed(2);
    clearTimeout(confTimer);
    confTimer = setTimeout(() => post("/api/settings", { confidence: Number(e.target.value) }).catch((er) => toast(er.message, "err")), 250);
  });
  $("imgszSelect").addEventListener("change", (e) =>
    post("/api/settings", { imgsz: Number(e.target.value) }).then(() => toast(`Inference size set to ${e.target.value}px.`)).catch((er) => toast(er.message, "err")));

  $("refreshBtn").addEventListener("click", async () => {
    await Promise.all([pollStats(), pollAlerts(), pollSystem(), pollTracks(), refreshVideos()]);
    // reconnect the video stream too
    $("feed").src = `/video_feed?t=${Date.now()}`;
    toast("Dashboard refreshed.");
  });

  // if the MJPEG connection drops, reconnect it
  $("feed").addEventListener("error", () => setTimeout(() => { $("feed").src = `/video_feed?t=${Date.now()}`; }, 1500));

  window.addEventListener("resize", () => { if (!HAS_CHART) redrawCharts(true); });

  /* ------------------------------------------------------------- boot */
  const initial = (location.hash || "").replace("#", "");
  if (document.getElementById(`view-${initial}`)) setView(initial);
  pollStats(); pollAlerts(); pollSystem(); refreshVideos();
})();
