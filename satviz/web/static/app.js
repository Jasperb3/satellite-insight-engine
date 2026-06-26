// Map controller. The map is navigated freely client-side (instant); analysis happens only
// when the user presses Snapshot, which captures the *current view*. The backend never sees
// pans/zooms — only the explicit snapshot.

let map;
let priorView = null;  // framing to return to after a POI fly-in
let imageOverlay = null;  // current captured-image overlay (E4)
let currentJobId = null;  // in-flight analysis job (E1/E2)
let pollTimer = null;
let lastSurpriseIdx = -1;  // avoid repeating the same Surprise back-to-back (B8)
let flyToken = 0;          // guards fly-then-snapshot against intervening pans (B9)
const POLL_MS = 1200;
const STAGE_ORDER = ["imagery", "vision", "enrichment", "report"];
const markerLayer = L.layerGroup();

// Geographic bounds of the analysed square: buffer_m on each side of the centre (E4).
function viewportBounds(vp) {
  const dLat = vp.buffer_m / 111320;
  // Clamp the cosine so the longitude span stays finite near the poles (E13).
  const dLon = vp.buffer_m / (111320 * Math.max(Math.cos((vp.latitude * Math.PI) / 180), 0.01));
  return [[vp.latitude - dLat, vp.longitude - dLon], [vp.latitude + dLat, vp.longitude + dLon]];
}

// [lat, lng, zoom, name] for the 🎲 Surprise button (E7/E14).
const SURPRISE_PLACES = [
  [29.9792, 31.1342, 16, "Pyramids of Giza"],
  [48.8584, 2.2945, 16, "Eiffel Tower"],
  [27.1751, 78.0421, 17, "Taj Mahal"],
  [-13.1631, -72.5450, 16, "Machu Picchu"],
  [41.8902, 12.4922, 17, "Colosseum"],
  [-33.8568, 151.2153, 17, "Sydney Opera House"],
  [37.8267, -122.4233, 15, "Alcatraz Island"],
  [51.1789, -1.8262, 17, "Stonehenge"],
  [40.4319, 116.5704, 15, "Great Wall (Mutianyu)"],
  [-22.9519, -43.2105, 16, "Christ the Redeemer"],
  [64.1466, -21.9426, 14, "Reykjavík"],
  [25.1972, 55.2744, 16, "Burj Khalifa"],
  [27.9881, 86.9250, 13, "Mount Everest"],
  [-3.0674, 37.3556, 12, "Mount Kilimanjaro"],
  [36.1069, -112.1129, 13, "Grand Canyon"],
  [44.4280, 110.5885, 12, "Yellowstone (Old Faithful)"],
  [43.0828, -79.0742, 15, "Niagara Falls"],
  [-25.3444, 131.0369, 14, "Uluru"],
  [-18.9249, 25.8540, 14, "Victoria Falls"],
  [13.4125, 103.8670, 15, "Angkor Wat"],
  [29.6516, 91.1170, 15, "Potala Palace, Lhasa"],
  [35.3606, 138.7274, 12, "Mount Fuji"],
  [37.9715, 23.7257, 17, "Acropolis of Athens"],
  [30.3285, 35.4444, 16, "Petra"],
  [21.4225, 39.8262, 17, "Kaaba, Mecca"],
  [20.6843, -88.5678, 16, "Chichén Itzá"],
  [27.1228, 88.4262, 12, "Darjeeling Himalaya"],
  [78.2232, 15.6267, 11, "Svalbard"],
  [-50.9423, -73.4068, 12, "Torres del Paine"],
  [63.0695, -151.0074, 9, "Denali"],
  [46.5763, 7.9904, 13, "Matterhorn"],
  [1.2834, 103.8607, 16, "Marina Bay, Singapore"],
  [40.6892, -74.0445, 15, "Statue of Liberty"],
  [55.7520, 37.6175, 16, "Red Square, Moscow"],
  [13.7563, 100.4944, 16, "Grand Palace, Bangkok"],
  [-1.2921, 36.8219, 13, "Nairobi"],
  [-13.5320, -71.9675, 14, "Cusco"],
  [64.2558, -21.1278, 12, "Þingvellir, Iceland"],
  [68.4690, 17.4270, 11, "Lofoten Islands"],
  [-34.6037, -58.3816, 14, "Buenos Aires"],
  [31.7767, 35.2345, 16, "Old City of Jerusalem"],
];

function resetView() {
  if (!priorView) return;
  map.flyTo(priorView.center, priorView.zoom, { duration: 0.8 });
  // flyTo fires a layout change before tiles settle; force a re-fetch when it lands.
  map.once("moveend", () => map.invalidateSize());
  document.getElementById("reset-view").classList.add("hidden");
}

// Restore the last centre/zoom so returning users don't snap back to London (E16).
function savedView() {
  try {
    const v = JSON.parse(localStorage.getItem("satviz:view"));
    if (v && Number.isFinite(v.lat) && Number.isFinite(v.lng) && Number.isFinite(v.zoom)) return v;
  } catch { /* ignore */ }
  return null;
}

function initMap() {
  const start = savedView();
  map = L.map("map").setView(start ? [start.lat, start.lng] : [51.5, -0.12], start ? start.zoom : 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(map);
  markerLayer.addTo(map);
  map.on("move zoom", updateReadout);
  map.on("moveend zoomend", () => {
    const c = map.getCenter();
    localStorage.setItem("satviz:view", JSON.stringify({ lat: c.lat, lng: c.lng, zoom: map.getZoom() }));
  });
  updateReadout();
}

// Buffer (metres) for the current view: half the smaller visible span, so the analysed
// square fits within what the user sees. Clamped to sane GEE limits.
function currentBuffer() {
  const b = map.getBounds();
  const c = map.getCenter();
  const widthM = map.distance([c.lat, b.getWest()], [c.lat, b.getEast()]);
  const heightM = map.distance([b.getSouth(), c.lng], [b.getNorth(), c.lng]);
  return Math.max(300, Math.min(20000, Math.round(Math.min(widthM, heightM) / 2)));
}

function updateReadout() {
  const c = map.getCenter();
  const buf = currentBuffer();
  const acrossKm = ((buf * 2) / 1000).toFixed(buf * 2 >= 1000 ? 1 : 2);
  const status = document.getElementById("status-line");
  if (status) status.textContent =
    `${c.lat.toFixed(4)}, ${c.lng.toFixed(4)} · ~${acrossKm} km across`;
}

function setLoading(on) {
  document.body.classList.toggle("busy", on);
  document.getElementById("snapshot").disabled = on;
  document.getElementById("snapshot").textContent = on ? "📸 Capturing…" : "📸 Snapshot";
}

// Highlight the active stage in the loading panel (E1).
function setStage(stage) {
  const idx = STAGE_ORDER.indexOf(stage);
  document.querySelectorAll("#loading .stages li").forEach((li) => {
    const i = STAGE_ORDER.indexOf(li.dataset.stage);
    li.classList.toggle("done", idx >= 0 && i < idx);
    li.classList.toggle("active", i === idx);
  });
}

function reportError(title, detail) {
  document.getElementById("report").innerHTML =
    `<div class="error"><strong>${title}</strong><p>${detail}</p></div>`;
}

// Resolve a non-blocking open-water confirmation via the in-panel modal (B5/E11):
// resolves true to proceed, false to abort. Replaces the fragile, thread-blocking confirm().
function confirmOpenWater() {
  const modal = document.getElementById("openwater-modal");
  modal.classList.remove("hidden");
  return new Promise((resolve) => {
    const yes = modal.querySelector("#ow-confirm");
    const no = modal.querySelector("#ow-cancel");
    const done = (val) => {
      modal.classList.add("hidden");
      yes.removeEventListener("click", onYes);
      no.removeEventListener("click", onNo);
      resolve(val);
    };
    const onYes = () => done(true);
    const onNo = () => done(false);
    yes.addEventListener("click", onYes);
    no.addEventListener("click", onNo);
  });
}

// Analyse a point. `target` ([lat, lng]) pins the location for fly-then-snapshot so an
// intervening pan can't redirect it (B9); without it the current map centre is used.
async function snapshot(target) {
  const c = target ? { lat: target[0], lng: target[1] } : map.getCenter();
  // Warn before committing ~2 minutes to a point that reverse-geocodes to open water (B5).
  try {
    const r = await fetch(`/api/reverse?latitude=${c.lat}&longitude=${c.lng}`);
    if (r.ok) {
      const info = await r.json();
      if (!info.located && !(await confirmOpenWater())) return;
    }
  } catch { /* reverse check is best-effort; proceed if it fails */ }

  document.getElementById("panel").scrollTop = 0;  // keep progress/cancel in view (B4)
  setLoading(true);
  setStage("imagery");
  try {
    const body = new URLSearchParams({ latitude: c.lat, longitude: c.lng, buffer_m: currentBuffer() });
    const resp = await fetch("/api/analyze/start", { method: "POST", body });
    const { job_id } = await resp.json();
    currentJobId = job_id;
    pollJob(job_id);
  } catch (err) {
    reportError("Request failed", err);
    setLoading(false);
  }
}

// Poll a running job; update stages, then render the result / cancellation / error (E1/E2).
async function pollJob(jobId) {
  if (currentJobId !== jobId) return;  // cancelled or superseded
  let status;
  try {
    status = await (await fetch(`/api/analyze/status/${jobId}`)).json();
  } catch {
    pollTimer = setTimeout(() => pollJob(jobId), POLL_MS);  // transient; retry
    return;
  }
  setStage(status.stage);
  if (status.state === "running") {
    pollTimer = setTimeout(() => pollJob(jobId), POLL_MS);
    return;
  }
  if (status.state === "done") {
    const html = await (await fetch(`/api/analyze/result/${jobId}`)).text();
    document.getElementById("report").innerHTML = html;
    applyMarkers();
  } else if (status.state === "cancelled") {
    reportError("Cancelled", "The capture was cancelled.");
  } else {
    reportError("Analysis failed", status.error || "Unknown error.");
  }
  currentJobId = null;
  setLoading(false);
}

async function loadRun(runId) {
  setLoading(true);
  try {
    const resp = await fetch(`/api/run/${encodeURIComponent(runId)}`);
    document.getElementById("report").innerHTML = await resp.text();
    applyMarkers({ recenter: true });
    // Reflect what was loaded in the search field so users know where they are (E5).
    const el = document.getElementById("run-data");
    if (el) {
      try { document.getElementById("place").value = JSON.parse(el.textContent).viewport?.display_name ?? ""; }
      catch { /* leave field as-is */ }
    }
  } catch (err) {
    document.getElementById("report").innerHTML =
      `<div class="error"><strong>Could not load run</strong><p>${err}</p></div>`;
  } finally {
    setLoading(false);
  }
}

async function flyTo(place) {
  if (!place.trim()) return;
  const resp = await fetch(`/api/geocode?place=${encodeURIComponent(place)}`);
  if (!resp.ok) {
    const status = document.getElementById("status-line");
    if (status) status.textContent = `Could not find "${place}".`;
    const input = document.getElementById("place");
    input.classList.remove("shake");
    void input.offsetWidth;  // restart the animation
    input.classList.add("shake");
    return;
  }
  const data = await resp.json();
  map.setView([data.latitude, data.longitude], 14);
}

// Drop the centre + POI markers after a report (no image overlay on the map).
function applyMarkers({ recenter = false } = {}) {
  const el = document.getElementById("run-data");
  if (!el) return;
  let data;
  try { data = JSON.parse(el.textContent); } catch { return; }
  const vp = data.viewport;
  if (!vp || vp.latitude == null) return;

  if (recenter) {
    // Reconstruct the snapshot's framing: buffer_m is half the analysed square's side,
    // so a 2*buffer bounds gives back the zoom currentBuffer() would have produced.
    let zoom = map.getZoom();
    if (vp.buffer_m) {
      const bounds = L.latLng(vp.latitude, vp.longitude).toBounds(vp.buffer_m * 2);
      zoom = map.getBoundsZoom(bounds);
    }
    map.setView([vp.latitude, vp.longitude], zoom);
  }

  markerLayer.clearLayers();
  L.circleMarker([vp.latitude, vp.longitude], { radius: 6, color: "#e63946", weight: 2, fillOpacity: 0.6 })
    .bindPopup("Snapshot centre")
    .addTo(markerLayer);
  (data.markers || []).forEach((m) => {
    // Emoji pin per POI category (E14); falls back to a generic marker if no icon.
    const icon = L.divIcon({ className: "poi-pin", html: m.icon || "📍",
                             iconSize: [22, 22], iconAnchor: [11, 11] });
    L.marker([m.lat, m.lon], { icon })
      .bindPopup(`<strong>${m.name}</strong>${m.kind ? `<br><em>${m.kind}</em>` : ""}`)
      .addTo(markerLayer);
  });

  // Captured-image overlay at its true geographic bounds (E4).
  if (imageOverlay) { map.removeLayer(imageOverlay); imageOverlay = null; }
  const toggle = document.getElementById("toggle-overlay");
  const slider = document.getElementById("overlay-opacity");
  if (data.image_url) {
    imageOverlay = L.imageOverlay(data.image_url, viewportBounds(vp),
                                  { opacity: parseFloat(slider.value) }).addTo(map);
    toggle.classList.remove("hidden");
    toggle.classList.add("active");
    slider.classList.remove("hidden");
    setOverlayLabel(true);
  } else {
    toggle.classList.add("hidden");
    slider.classList.add("hidden");
  }
}

// Reflect overlay visibility in the toggle's label so its state is unambiguous (E3).
function setOverlayLabel(on) {
  document.getElementById("toggle-overlay").textContent = on ? "🛰 Overlay on" : "🛰 Overlay off";
}

// Fly to a target and snapshot it once the camera lands. The token guards against an
// intervening pan/fly firing the snapshot for the wrong place (B9); the explicit target
// coords are passed straight through so the analysed point is always the intended one.
function flyThenSnapshot(lat, lng, zoom, name) {
  if (name) document.getElementById("place").value = name;
  const token = ++flyToken;
  map.flyTo([lat, lng], zoom, { duration: 0.8 });
  map.once("moveend", () => { if (token === flyToken) snapshot([lat, lng]); });
}

// Pick a famous place at random, never repeating the last one (B8), then fly + snapshot.
function triggerSurprise() {
  if (document.body.classList.contains("busy")) return;
  let idx;
  do { idx = Math.floor(Math.random() * SURPRISE_PLACES.length); }
  while (SURPRISE_PLACES.length > 1 && idx === lastSurpriseIdx);
  lastSurpriseIdx = idx;
  const [lat, lng, zoom, name] = SURPRISE_PLACES[idx];
  flyThenSnapshot(lat, lng, zoom, name);
}

// Pick a truly random point and keep trying until one lands on (reverse-geocodable) land (E2).
async function surpriseRandom() {
  if (document.body.classList.contains("busy")) return;
  const status = document.getElementById("status-line");
  if (status) status.textContent = "🌍 Finding a random spot on land…";
  for (let i = 0; i < 8; i++) {
    const lat = Math.random() * 126 - 56;   // ~ -56°..70°, biased to inhabited latitudes
    const lng = Math.random() * 360 - 180;
    try {
      const info = await (await fetch(`/api/reverse?latitude=${lat}&longitude=${lng}`)).json();
      if (info.located) { flyThenSnapshot(lat, lng, 13, info.display_name); return; }
    } catch { /* try another point */ }
  }
  if (status) status.textContent = "Couldn't find land — press 🌍 to try again.";
}

function wireControls() {
  document.getElementById("snapshot").addEventListener("click", () => snapshot());

  // ✕ Cancel an in-flight analysis (E2): stop polling and tell the server to abort.
  document.getElementById("cancel-snapshot").addEventListener("click", () => {
    if (!currentJobId) return;
    const id = currentJobId;
    currentJobId = null;          // stops the poll loop
    clearTimeout(pollTimer);
    fetch(`/api/analyze/${id}`, { method: "DELETE" }).catch(() => {});
    reportError("Cancelled", "The capture was cancelled.");
    setLoading(false);
  });

  document.getElementById("search-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    flyTo(document.getElementById("place").value);
  });

  // Bottom-left arrows pan the MAP (client-side, instant). Zoom uses Leaflet's native
  // top-left control + pinch, so there's no duplicate here.
  const panBy = { up: [0, -0.3], down: [0, 0.3], left: [-0.3, 0], right: [0.3, 0] };
  document.querySelectorAll("#controls [data-pan]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const size = map.getSize();
      const [fx, fy] = panBy[btn.dataset.pan];
      map.panBy([size.x * fx, size.y * fy]);
    });
  });

  document.getElementById("history-btn").addEventListener("click", () => {
    window.open("/history", "_blank");
  });
  document.getElementById("reset-view").addEventListener("click", resetView);

  // 🛰 Toggle the captured-image overlay on the map (E3/E4).
  document.getElementById("toggle-overlay").addEventListener("click", (ev) => {
    if (!imageOverlay) return;
    const willShow = !map.hasLayer(imageOverlay);
    if (willShow) imageOverlay.addTo(map); else map.removeLayer(imageOverlay);
    ev.currentTarget.classList.toggle("active", willShow);
    setOverlayLabel(willShow);
  });

  // Blend the satellite overlay against the basemap (E1).
  document.getElementById("overlay-opacity").addEventListener("input", (ev) => {
    if (imageOverlay) imageOverlay.setOpacity(parseFloat(ev.currentTarget.value));
  });

  // 🎲 Surprise: fly to a random famous place and analyse it (E14).
  document.getElementById("surprise-btn").addEventListener("click", triggerSurprise);
  // 🌍 Random: fly to a random point that's actually on land, then analyse it (E2).
  document.getElementById("random-btn").addEventListener("click", surpriseRandom);

  // ⌨ Keyboard-shortcut help modal (E11).
  const helpModal = document.getElementById("help-modal");
  document.getElementById("help-btn").addEventListener("click", () => helpModal.classList.remove("hidden"));
  helpModal.addEventListener("click", (ev) => {
    if (ev.target === helpModal || ev.target.closest(".modal-close")) helpModal.classList.add("hidden");
  });

  // 🔍 Satellite-image lightbox (E9): click the image to view it fullscreen.
  const lightbox = document.getElementById("lightbox");
  document.body.addEventListener("click", (ev) => {
    const img = ev.target.closest(".sat-image");
    if (img) { lightbox.querySelector("img").src = img.src; lightbox.classList.remove("hidden"); }
  });
  lightbox.addEventListener("click", () => lightbox.classList.add("hidden"));

  // Keyboard: WASD pan, Z/X zoom (map only), Enter = snapshot. Ignore while typing.
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      document.getElementById("help-modal").classList.add("hidden");
      document.getElementById("lightbox").classList.add("hidden");
      return;
    }
    if (ev.target.tagName === "INPUT") return;
    const size = map.getSize();
    const key = ev.key.toLowerCase();
    if (key === "w") map.panBy([0, -size.y * 0.3]);
    else if (key === "s") map.panBy([0, size.y * 0.3]);
    else if (key === "a") map.panBy([-size.x * 0.3, 0]);
    else if (key === "d") map.panBy([size.x * 0.3, 0]);
    else if (key === "z") map.zoomIn();
    else if (key === "x") map.zoomOut();
    else if (key === "r") triggerSurprise();
    else if (key === "enter" && !document.body.classList.contains("busy")) snapshot();
  });

  // Copy a shareable deep-link (?run=<id>) for the current report. Delegated because the
  // report partial is swapped in after each snapshot/run load.
  document.body.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".copy-link");
    if (!btn) return;
    const url = `${location.origin}/?run=${encodeURIComponent(btn.dataset.runId)}`;
    navigator.clipboard.writeText(url).then(() => {
      btn.textContent = "✓ Copied";
      setTimeout(() => { btn.textContent = "🔗 Copy link"; }, 1500);
    });
  });

  // POI focus: remember the framing, then smoothly fly in so it's actually visible.
  document.body.addEventListener("click", (ev) => {
    const poi = ev.target.closest(".poi");
    if (!poi) return;
    priorView = { center: map.getCenter(), zoom: map.getZoom() };
    map.flyTo([parseFloat(poi.dataset.lat), parseFloat(poi.dataset.lon)], 16, { duration: 0.8 });
    document.getElementById("reset-view").classList.remove("hidden");
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  wireControls();
  // Deep-link: /?run=<id> opens a saved run directly (used by the History page).
  const runId = new URLSearchParams(location.search).get("run");
  if (runId) loadRun(runId);
});
