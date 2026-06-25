// Map controller: owns the Leaflet surface and spatial/keyboard events, calls backend
// endpoints, and syncs the map from the run-data the server embeds in each report swap.
// HTMX owns the search form + history fragment swaps; everything spatial lives here.

let map, satOverlay;
const markerLayer = L.layerGroup();
let current = null; // {latitude, longitude, buffer_m}

function initMap() {
  map = L.map("map").setView([30, 0], 3);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(map);
  markerLayer.addTo(map);

  map.on("click", (ev) => {
    const buffer = current ? current.buffer_m : 1500;
    postAction("/api/analyze", { latitude: ev.latlng.lat, longitude: ev.latlng.lng, buffer_m: buffer });
  });
}

function setLoading(on) {
  document.body.classList.toggle("busy", on);
}

async function postAction(url, data) {
  setLoading(true);
  try {
    const body = new URLSearchParams(data);
    const resp = await fetch(url, { method: "POST", body });
    document.getElementById("report").innerHTML = await resp.text();
    syncFromPanel();
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
    syncFromPanel();
  } finally {
    setLoading(false);
  }
}

// Read the run-data the server embedded and update map center, overlay, markers, status.
function syncFromPanel() {
  const el = document.getElementById("run-data");
  if (!el) return;
  let data;
  try { data = JSON.parse(el.textContent); } catch { return; }
  const vp = data.viewport;
  if (!vp || vp.latitude == null || vp.longitude == null) return;
  current = vp;

  const lat = vp.latitude, lon = vp.longitude, buf = vp.buffer_m || 1500;
  const dLat = buf / 111320;
  const dLon = buf / (111320 * Math.cos((lat * Math.PI) / 180));
  const bounds = [[lat - dLat, lon - dLon], [lat + dLat, lon + dLon]];

  if (satOverlay) map.removeLayer(satOverlay);
  satOverlay = L.imageOverlay(data.image_url, bounds, { opacity: 0.9 }).addTo(map);
  map.fitBounds(bounds);

  markerLayer.clearLayers();
  L.circleMarker([lat, lon], { radius: 6, color: "#e63946", weight: 2, fillOpacity: 0.6 })
    .bindPopup("Analysis centre")
    .addTo(markerLayer);
  (data.markers || []).forEach((m) => {
    L.circleMarker([m.lat, m.lon], { radius: 4, color: "#1d3557", weight: 1, fillOpacity: 0.7 })
      .bindPopup(`<strong>${m.name}</strong>${m.kind ? `<br><em>${m.kind}</em>` : ""}`)
      .addTo(markerLayer);
  });

  const status = document.getElementById("status-line");
  if (status) status.textContent = `${lat.toFixed(4)}, ${lon.toFixed(4)} · zoom ${buf} m`;

  document.body.dispatchEvent(new Event("refreshRuns")); // HTMX refreshes history list
}

function wireControls() {
  document.querySelectorAll("#controls [data-command]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!current) return;
      postAction("/api/move", { ...current, command: btn.dataset.command });
    });
  });
  document.querySelectorAll("#controls [data-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!current) return;
      postAction("/api/zoom", { ...current, command: btn.dataset.zoom });
    });
  });

  // Keyboard navigation (ignore when typing in the search box).
  document.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "INPUT" || !current) return;
    const key = ev.key.toLowerCase();
    if ("wasd".includes(key)) postAction("/api/move", { ...current, command: key });
    else if (key === "z" || key === "x") postAction("/api/zoom", { ...current, command: key });
  });

  // History item + POI clicks (delegated; survive HTMX swaps).
  document.body.addEventListener("click", (ev) => {
    const hist = ev.target.closest(".history-item");
    if (hist) { ev.preventDefault(); loadRun(hist.dataset.run); return; }
    const poi = ev.target.closest(".poi");
    if (poi) { map.panTo([parseFloat(poi.dataset.lat), parseFloat(poi.dataset.lon)]); }
  });
}

// After HTMX swaps the report panel (search) or history, keep the map in sync.
document.body.addEventListener("htmx:afterSwap", (ev) => {
  if (ev.detail.target.id === "report") syncFromPanel();
});

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  wireControls();
});
