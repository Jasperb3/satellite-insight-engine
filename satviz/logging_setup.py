"""One place to configure timestamped logging for both the CLI and the web app, so every
behind-the-scenes action (geocode, imagery, vision, each enrichment tool, report) shows in
the terminal with a time and duration."""

import logging

_CONFIGURED = False


def configure(level: int = logging.INFO) -> None:
    """Idempotent root logging config with timestamps. Safe to call from CLI and web."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy third parties; keep our own loggers at INFO.
    for noisy in ("urllib3", "googleapiclient", "google", "httpx", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
