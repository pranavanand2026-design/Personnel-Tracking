"""Run the site monitor: python -m counter.web [--port 8000]

Create the admin account first: python -m counter.web.admin
If the site was live when the server last stopped, it goes live again from
data/runtime_config.json.
"""
import argparse

import uvicorn

from counter.web import db
from counter.web.app import create_app
from counter.web.runtime import RUNTIME_CONFIG, Runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Site monitor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    runtime = Runtime()
    org = db.get_org()
    if org and org["live"] and RUNTIME_CONFIG.exists():
        runtime.start_from_file()
        print(f"Resumed live monitoring from {RUNTIME_CONFIG}")
    if not db.get_admin():
        print("No admin account yet. Create one with: .venv/bin/python -m counter.web.admin")
    print(f"Site monitor at http://{args.host}:{args.port}")
    try:
        uvicorn.run(create_app(runtime), host=args.host, port=args.port, log_level="warning")
    finally:
        if runtime.sup:
            runtime.sup.stop()  # keep the live flag so a restart resumes


if __name__ == "__main__":
    main()
