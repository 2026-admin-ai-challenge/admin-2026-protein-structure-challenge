r"""Loads the organizer account sheet into the database.

    docker compose exec -T api python -m app.sync_accounts < accounts/participants.csv
    python -m app.sync_accounts accounts/participants.csv --exclusive
    cmd /c "docker compose exec -T api python -m app.sync_accounts < accounts\participants.csv"   (Windows PowerShell)

The sheet (team_name, username, password, display_name) is the editable source of truth
for participant logins: edit a row and run this again. Only password hashes are stored.
Participants sign in with team_name and password; username is the account's internal ID.
`--exclusive` blocks every participant account that is not in the sheet.
"""
import argparse
import sys
from pathlib import Path

from .accounts import sync_sheet
from .db import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="Sync participant accounts from a CSV sheet")
    parser.add_argument("path", nargs="?", default="-", help="CSV file, or - for standard input")
    parser.add_argument("--exclusive", action="store_true", help="block participant accounts missing from the sheet")
    args = parser.parse_args()
    if args.path == "-":
        text = sys.stdin.buffer.read().decode("utf-8-sig")
    else:
        text = Path(args.path).read_text(encoding="utf-8-sig")
    with SessionLocal() as db:
        try:
            summary = sync_sheet(db, text, exclusive=args.exclusive)
        except ValueError as error:
            db.rollback()
            raise SystemExit(f"계정 시트 오류: {error}")
        db.commit()
    print(", ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
