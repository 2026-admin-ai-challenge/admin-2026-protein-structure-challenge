"""명령줄 진입점.

    python -m prediction_validator predictions.csv \
        --eval-ids data/private/test.csv \
        --classes-metadata data/public/metadata.json

종료 코드
---------
0  검증 통과 (경고는 있을 수 있음)
1  참가자 출력 형식 오류
2  채점기 설정 오류 (운영 측 조치 필요)
3  사용법 오류
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import SPECS, describe_codes
from .worker_api import validate_submission_output

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_OPERATOR = 2
EXIT_USAGE = 3


def _force_utf8_stdout() -> None:
    """Windows 콘솔 기본 코드페이지(cp949)에서 한국어 메시지가 깨지지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prediction_validator",
        description="ADMIN 2026 대회 예측 출력 검증기",
    )
    parser.add_argument(
        "prediction",
        nargs="?",
        type=Path,
        help="검증할 예측 CSV 경로",
    )
    parser.add_argument("--contract", type=Path, default=None, help="계약 JSON 경로")
    parser.add_argument(
        "--eval-ids",
        type=Path,
        default=None,
        help="평가 ID 목록 CSV (id 컬럼). 예: data/private/test.csv",
    )
    parser.add_argument(
        "--classes-metadata",
        type=Path,
        default=None,
        help="데이터셋 metadata.json (labels 배열에서 클래스 목록을 읽음)",
    )
    parser.add_argument(
        "--classes-train-csv",
        type=Path,
        default=None,
        help="train.csv (label 고유값에서 클래스 목록을 읽음)",
    )
    parser.add_argument(
        "--classes-file",
        type=Path,
        default=None,
        help="클래스 목록 텍스트 파일 (한 줄에 하나)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="사람이 읽는 표 대신 JSON 으로 출력",
    )
    parser.add_argument(
        "--operator",
        action="store_true",
        help="운영 상세 출력. 누락된 평가 ID 예시가 포함되므로 참가자에게 보여주지 않는다",
    )
    parser.add_argument(
        "--list-codes",
        action="store_true",
        help="오류 코드 표를 출력하고 종료",
    )
    return parser


def _print_codes() -> int:
    print(f"{'코드':<6} {'등급':<8} 메시지")
    print("-" * 78)
    for item in describe_codes():
        flags = []
        if item["leaks_eval_set"]:
            flags.append("평가셋노출")
        if item["operator_fault"]:
            flags.append("운영측")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{item['code']:<6} {item['severity']:<8} {item['message']}{suffix}")
    print(f"\n총 {len(SPECS)}개 코드")
    return EXIT_OK


def _print_report(outcome, operator: bool) -> None:
    status = "통과" if outcome.ok else "실패"
    print(f"계약 버전: {outcome.contract_version}")
    print(f"결과: {status}")

    summary = outcome.operator_detail.get("summary", {})
    if summary:
        parts = [f"{k}={v}" for k, v in summary.items()]
        print(f"요약: {', '.join(parts)}")

    payload = outcome.operator_detail if operator else outcome.participant_response
    findings = (
        payload["findings"]
        if operator
        else payload["errors"] + payload["warnings"]
    )

    if not findings:
        print("오류·경고 없음")
        return

    print()
    for item in findings:
        mark = "오류" if item["severity"] == "error" else "경고"
        print(f"[{item['code']}] {mark} ({item['count']}건) {item['message']}")
        if item.get("rows"):
            shown = ", ".join(str(r) for r in item["rows"])
            print(f"       행: {shown}")
        if item.get("samples"):
            for sample in item["samples"][:5]:
                print(f"       예: {sample}")
        if item.get("hint"):
            print(f"       조치: {item['hint']}")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_codes:
        return _print_codes()

    if args.prediction is None:
        parser.print_usage()
        print("\n오류: 검증할 예측 파일 경로가 필요합니다.", file=sys.stderr)
        return EXIT_USAGE

    outcome = validate_submission_output(
        args.prediction,
        contract_path=args.contract,
        classes_metadata=args.classes_metadata,
        classes_train_csv=args.classes_train_csv,
        classes_file=args.classes_file,
        eval_ids_csv=args.eval_ids,
    )

    if args.json:
        print(outcome.report.to_json(operator=args.operator))
    else:
        _print_report(outcome, args.operator)

    if outcome.ok:
        return EXIT_OK
    return EXIT_OPERATOR if outcome.operator_fault else EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
