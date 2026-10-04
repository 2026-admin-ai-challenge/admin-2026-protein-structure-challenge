"""Writes a new account sheet with random 10-character IDs and temporary passwords.

    python -m app.generate_accounts --count 10 --out accounts/participants.csv

The sheet holds plaintext passwords for handing out, so keep it out of Git (accounts/ is
ignored) and load it with `python -m app.sync_accounts`.
"""
import argparse
from pathlib import Path

from .accounts import generate_sheet


def main():
    parser = argparse.ArgumentParser(description="Generate a participant account sheet")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--out", default="accounts/participants.csv")
    parser.add_argument("--team-prefix", default="Team")
    args = parser.parse_args()
    target = Path(args.out)
    if target.exists():
        raise SystemExit(f"{target} 파일이 이미 있습니다. 덮어쓰지 않습니다. 직접 수정하거나 다른 --out 경로를 쓰세요.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_sheet(args.count, args.team_prefix), encoding="utf-8", newline="\n")
    print(f"{args.count}개 계정을 {target}에 만들었습니다.")


if __name__ == "__main__":
    main()
