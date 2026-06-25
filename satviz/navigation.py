"""Pure WASD/zoom coordinate math. No I/O — trivially testable."""

MOVEMENT_SCALE = 0.01  # ~1 km at mid-latitudes
MIN_BUFFER = 500
ZOOM_STEP = 1000

CONTROLS_HELP = (
    "\nControls:\n"
    "  W - North   S - South   A - West   D - East\n"
    "  Z - Zoom In   X - Zoom Out   Q - Quit\n"
    "Enter command: "
)


def handle_movement(lat: float, lon: float, buffer: int, command: str) -> tuple[float, float, int]:
    """Return updated (lat, lon, buffer) for a single command. Unknown commands no-op."""
    cmd = command.strip().lower()
    if cmd == "w":
        return lat + MOVEMENT_SCALE, lon, buffer
    if cmd == "s":
        return lat - MOVEMENT_SCALE, lon, buffer
    if cmd == "a":
        return lat, lon - MOVEMENT_SCALE, buffer
    if cmd == "d":
        return lat, lon + MOVEMENT_SCALE, buffer
    if cmd == "z":
        return lat, lon, max(MIN_BUFFER, buffer - ZOOM_STEP)
    if cmd == "x":
        return lat, lon, buffer + ZOOM_STEP
    return lat, lon, buffer
