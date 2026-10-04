"""Checks that stored submission ZIPs match their database records.

    docker compose exec api python -m app.check_files           # presence and size
    docker compose exec api python -m app.check_files --hash    # also re-hash every ZIP (slow)

Exits with status 1 when something does not match. Nothing is changed or deleted.
"""
import argparse
import json

from .db import SessionLocal
from .files import check


def main():
    parser = argparse.ArgumentParser(description="Compare stored submission ZIPs with the database")
    parser.add_argument("--hash", action="store_true", help="re-hash every stored ZIP and compare with the recorded SHA-256")
    args = parser.parse_args()
    with SessionLocal() as db:
        report = check(db, with_hashes=args.hash)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
