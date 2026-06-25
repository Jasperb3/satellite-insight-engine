"""Entry point for the Satellite Insight Engine.

    python main.py          # interactive CLI (default)
    python main.py --gui    # reserved for the future HTML GUI presenter
"""

import argparse

from satviz.presenters import cli


def main() -> None:
    parser = argparse.ArgumentParser(description="Satellite Insight Engine")
    parser.add_argument(
        "--gui", action="store_true",
        help="Launch the browser GUI (not yet implemented; reserved seam).",
    )
    args = parser.parse_args()

    if args.gui:
        print("The HTML GUI is not implemented yet. Run without --gui for the CLI.")
        return
    cli.run()


if __name__ == "__main__":
    main()
