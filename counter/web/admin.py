"""Create or reset the single local admin account (there is no sign-up page).

Usage: .venv/bin/python -m counter.web.admin [--username admin]
"""
import argparse
import getpass
import sys

from counter.web import db
from counter.web.auth import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", default="admin")
    args = parser.parse_args()

    password = getpass.getpass(f"Password for {args.username}: ")
    if len(password) < 8:
        print("Use at least 8 characters.")
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.")
        return 1
    existed = db.get_admin() is not None
    db.set_admin(args.username, hash_password(password))
    print(f"{'Reset' if existed else 'Created'} admin '{args.username}' in {db.DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
