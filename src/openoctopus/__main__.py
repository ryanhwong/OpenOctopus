import sys

from openoctopus.login import main


def run() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        main()
    else:
        print("usage: python -m openoctopus login [--url URL]", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    run()
