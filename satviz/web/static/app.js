// Map controller. The map is navigated freely client-side (instant); analysis happens only
// when the user presses Snapshot, which captures the *current view*. The backend never sees
// pans/zooms — only the explicit snapshot.

let map;
let priorView = null;  // framing to return to after a POI fly-in
const markerLayer = L.layerGroup();

function resetView() {
  if (!priorView) return;
  map.flyTo(priorView.center, priorView.zoom, { duration: 0.8 });
  document.getElementById("reset-view").classList.add("hidden");
}

function initMap() {
  map = L.map("map").setView([51.5, -0.12], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(map);
  markerLayer.addTo(map);
  map.on("move zoom", updateReadout);
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

async function snapshot() {
  const c = map.getCenter();
  setLoading(true);
  try {
    const body = new URLSearchParams({ latitude: c.lat, longitude: c.lng, buffer_m: currentBuffer() });
    const resp = await fetch("/api/analyze", { method: "POST", body });
    document.getElementById("report").innerHTML = await resp.text();
    applyMarkers();
  } catch (err) {
    document.getElementById("report").innerHTML =
      `<div class="error"><strong>Request failed</strong><p>${err}</p></div>`;
  } finally {
    setLoading(false);
  }
}

async function loadRun(runId) {
  setLoading(true);
  try {
    const resp = await fetch(`/api/run/${encodeURIComponent(runId)}`);
    document.getElementById("report").innerHTML = await resp.text();
    applyMarkers({ recenter: true });
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

  if (recenter) map.setView([vp.latitude, vp.longitude], map.getZoom());

  markerLayer.clearLayers();
  L.circleMarker([vp.latitude, vp.longitude], { radius: 6, color: "#e63946", weight: 2, fillOpacity: 0.6 })
    .bindPopup("Snapshot centre")
    .addTo(markerLayer);
  (data.markers || []).forEach((m) => {
    L.circleMarker([m.lat, m.lon], { radius: 4, color: "#1d3557", weight: 1, fillOpacity: 0.7 })
      .bindPopup(`<strong>${m.name}</strong>${m.kind ? `<br><em>${m.kind}</em>` : ""}`)
      .addTo(markerLayer);
  });
}

function wireControls() {
  document.getElementById("snapshot").addEventListener("click", snapshot);

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

  // Keyboard: WASD pan, Z/X zoom (map only), Enter = snapshot. Ignore while typing.
  document.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "INPUT") return;
    const size = map.getSize();
    const key = ev.key.toLowerCase();
    if (key === "w") map.panBy([0, -size.y * 0.3]);
    else if (key === "s") map.panBy([0, size.y * 0.3]);
    else if (key === "a") map.panBy([-size.x * 0.3, 0]);
    else if (key === "d") map.panBy([size.x * 0.3, 0]);
    else if (key === "z") map.zoomIn();
    else if (key === "x") map.zoomOut();
    else if (key === "enter") snapshot();
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
