import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="openoctopus")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("login")
    args = parser.parse_args()

    if args.cmd == "login":
        from openoctopus.login import main as login_main

        login_main()
        return

    import uvicorn

    from openoctopus.config import get_settings
    from openoctopus.jobs.context import build_context
    from openoctopus.web.app import create_app

    settings = get_settings()
    app = create_app(build_context(settings), run_worker=True)
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
