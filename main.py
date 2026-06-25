"""Entry point for the Satellite Insight Engine.

    python main.py          # interactive CLI (default)
    python main.py --gui    # reserved for the future HTML GUI presenter
"""

import argparse

from satviz.logging_setup import configure
from satviz.presenters import cli


def main() -> None:
    configure()
    parser = argparse.ArgumentParser(description="Satellite Insight Engine")
    parser.add_argument(
        "--gui", action="store_true",
        help="Launch the browser GUI (FastAPI + Leaflet) on http://localhost:8000.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="GUI bind host.")
    parser.add_argument("--port", type=int, default=8000, help="GUI port.")
    args = parser.parse_args()

    if args.gui:
        import uvicorn
        print(f"Satellite Insight Engine GUI → http://{args.host}:{args.port}")
        uvicorn.run("satviz.web.app:app", host=args.host, port=args.port)
        return
    cli.run()


if __name__ == "__main__":
    main()
