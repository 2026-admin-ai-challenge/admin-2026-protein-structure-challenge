"""예측 출력 검증 핵심 로직.

설계 원칙
---------
1. 표준 라이브러리만 쓴다. pandas 는 형식 오류를 조용히 교정하므로
   형식 검증기로 쓰면 안 된다. 특히 label 이 "1.10" 같은 'C.A' 문자열이라
   dtype 지정 없이 읽으면 1.1 이 되어 다른 클래스가 된다.
2. 첫 오류에서 멈추지 않는다. 팀당 제출이 10회뿐이므로 한 번의 실패
   응답에 고칠 거리를 최대한 담는다. 단 코드별 예시는 MAX_SAMPLES 로 제한한다.
3. 숨김 평가 ID 집합을 참가자 응답에 흘리지 않는다. 누락 ID(E401)는
   개수만 알려주고 실제 ID는 운영 로그에만 남긴다.
4. 운영 측 설정 오류(E901/E902)와 참가자 형식 오류를 구분한다.
   제출 횟수 차감 정책(Q4)이 둘을 다르게 다뤄야 한다.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .contract import Contract
from .errors import MAX_SAMPLES, Report

NULLISH = frozenset({"nan", "none", "null", "na", "n/a", "<na>", "-", "?"})
"""결측으로 해석되는 라벨 문자열 (소문자 비교)."""

INT_INDEX = re.compile(r"^[+-]?\d{1,3}$")
"""클래스 인덱스로 제출한 경우를 잡는 패턴. 'C.A' 라벨에는 점이 있으므로 겹치지 않는다."""

DECIMAL_LABEL = re.compile(r"^\d+\.\d+$")
"""'C.A' 형태 라벨. 숫자 변환으로 끝자리 0이 사라졌는지 판단하는 데 쓴다."""

CSV_FIELD_LIMIT = 1_000_000


def _looks_like_truncated_decimal(value: str, classes: frozenset[str]) -> str | None:
    """숫자 변환으로 끝자리 0이 사라진 라벨인지 확인한다.

    "1.10" 을 float 로 읽으면 1.1 이 되고, 다시 문자열로 쓰면 "1.1" 이다.
    허용 클래스 중 뒤에 0을 붙이면 일치하는 값이 있으면 그 원래 값을 돌려준다.
    """
    if not DECIMAL_LABEL.fullmatch(value) or value in classes:
        return None
    for candidate in classes:
        if DECIMAL_LABEL.fullmatch(candidate) and candidate.rstrip("0") == value:
            return candidate
        # 1.1 -> 1.10 처럼 0을 채워 맞는 경우
        if candidate.startswith(value) and set(candidate[len(value):]) <= {"0"}:
            return candidate
    return None


def _case_insensitive_match(value: str, classes: frozenset[str]) -> str | None:
    folded = value.strip().casefold()
    for candidate in classes:
        if candidate.casefold() == folded:
            return candidate
    return None


def validate_file(
    path: str | Path,
    contract: Contract,
    *,
    report: Report | None = None,
) -> Report:
    """예측 파일 하나를 검증한다.

    파일 수준 오류(없음·빈 파일·크기·인코딩)를 먼저 확인하고,
    통과하면 내용 검증으로 넘어간다.
    """
    report = report or Report(contract_version=contract.version)
    path = Path(path)

    if not path.is_file():
        report.record("E101", sample=str(path.name))
        return report

    size = path.stat().st_size
    report.summary["file_bytes"] = size
    report.summary["file_name"] = path.name

    if size == 0:
        report.record("E102")
        return report

    if size > contract.max_file_bytes:
        report.record(
            "E103",
            sample=f"{size} bytes > 상한 {contract.max_file_bytes} bytes",
        )
        return report

    blob = path.read_bytes()

    if b"\x00" in blob:
        report.record("E106")
        return report

    try:
        text = blob.decode(contract.encoding)
    except UnicodeDecodeError as exc:
        report.record("E104", sample=f"byte {exc.start} 부근")
        return report

    if text.startswith("﻿"):
        if contract.allow_bom:
            report.record("W903")
            text = text.lstrip("﻿")
        else:
            report.record("E104", sample="UTF-8 BOM")
            return report

    return validate_text(text, contract, report=report)


def validate_text(
    text: str,
    contract: Contract,
    *,
    report: Report | None = None,
) -> Report:
    """예측 파일 내용을 검증한다. 파일 수준 검사는 호출자가 끝낸 상태로 본다."""
    report = report or Report(contract_version=contract.version)

    # 운영 측 설정부터 확인한다. 참가자 파일을 탓하기 전에 채점기가
    # 판정할 수 있는 상태인지 본다.
    if not contract.has_classes:
        report.record("E901")
    if not contract.has_eval_ids:
        report.record("E902")
    if report.operator_fault:
        return report

    rows, parse_failed = _parse_csv(text, report)
    if parse_failed:
        return report

    if not rows:
        report.record("E102")
        return report

    header = rows[0]
    if not _check_header(header, contract, report):
        return report

    id_index = header.index(contract.id_column)
    label_index = header.index(contract.label_column)
    field_count = len(header)

    ids, labels = _check_rows(
        rows[1:], field_count, id_index, label_index, contract, report
    )

    _check_ids(ids, contract, report)
    _check_labels(labels, contract, report)

    report.summary["rows"] = len(rows) - 1
    report.summary["unique_ids"] = len(set(ids))
    return report


def _parse_csv(text: str, report: Report) -> tuple[list[list[str]], bool]:
    """CSV 를 파싱한다. 실패하면 (빈 목록, True) 를 돌려준다."""
    # 따옴표 불균형을 먼저 잡는다. csv 모듈은 닫히지 않은 따옴표에 오류를 내지
    # 않고 파일 끝까지 한 필드로 삼켜 버리므로, 그대로 두면 참가자가 원인과
    # 무관한 "필드 수 불일치" 메시지를 받는다. 올바른 CSV에서 따옴표는 항상
    # 짝을 이루므로(이스케이프는 "") 총 개수가 홀수면 불균형이 확실하다.
    if text.count('"') % 2 == 1:
        report.record("E105", sample="닫히지 않은 따옴표가 있습니다 (따옴표 개수가 홀수)")
        return [], True

    previous = csv.field_size_limit()
    try:
        csv.field_size_limit(CSV_FIELD_LIMIT)
        reader = csv.reader(io.StringIO(text, newline=""))
        return [row for row in reader], False
    except csv.Error as exc:
        report.record("E105", sample=str(exc)[:200])
        return [], True
    finally:
        csv.field_size_limit(previous)


def _check_header(header: list[str], contract: Contract, report: Report) -> bool:
    """헤더를 검증한다. 계속 진행할 수 있으면 True."""
    cleaned = [h.strip() for h in header]

    # 헤더 자리에 데이터가 온 경우: 첫 행이 ID 형식이면 헤더가 없는 것으로 본다.
    if contract.require_header and cleaned and contract.id_pattern.fullmatch(cleaned[0]):
        report.record("E201", sample=",".join(cleaned[:4]))
        return False

    duplicates = {h for h in cleaned if cleaned.count(h) > 1}
    for dup in sorted(duplicates):
        report.record("E205", sample=dup)

    missing = [c for c in contract.columns if c not in cleaned]
    for col in missing:
        report.record("E202", sample=col)

    extra = [h for h in cleaned if h not in contract.columns]
    if extra and not contract.allow_extra_columns:
        for col in extra:
            report.record("E203", sample=col or "(빈 컬럼명)")

    if missing or duplicates:
        # 어느 컬럼이 id/label 인지 특정할 수 없으므로 행 검증으로 넘어가지 않는다.
        return False

    if contract.column_order_strict:
        contract_order = [h for h in cleaned if h in contract.columns]
        if contract_order != list(contract.columns):
            report.record(
                "E204",
                sample=f"받은 순서 {','.join(cleaned)} / 계약 순서 {','.join(contract.columns)}",
            )
            return False

    header[:] = cleaned
    return not report.errors


def _check_rows(
    data_rows: list[list[str]],
    field_count: int,
    id_index: int,
    label_index: int,
    contract: Contract,
    report: Report,
) -> tuple[list[str], list[str]]:
    """행 구조를 검증하고 id·label 값을 뽑아낸다.

    반환되는 ids/labels 는 계약에 따른 정규화(공백 제거)만 적용한 값이다.
    """
    ids: list[str] = []
    labels: list[str] = []

    for offset, row in enumerate(data_rows):
        line = offset + 2  # 1-기반, 헤더 포함

        if not row or (len(row) == 1 and not row[0].strip()):
            report.record("E303", row=line)
            continue

        if len(row) != field_count:
            report.record(
                "E301",
                row=line,
                sample=f"필드 {len(row)}개 (헤더는 {field_count}개)",
            )
            continue

        raw_id = row[id_index]
        raw_label = row[label_index]

        if raw_id != raw_id.strip():
            # 경고로 알리고 교정한 값으로 계속 본다. 공백 하나 때문에
            # 뒤따르는 ID 검사가 전부 실패하면 응답이 도움이 되지 않는다.
            report.record("E406", row=line, sample=repr(raw_id))
        ids.append(raw_id.strip())
        labels.append(raw_label.strip() if contract.label_strip_whitespace else raw_label)

    return ids, labels


def _check_ids(ids: list[str], contract: Contract, report: Report) -> None:
    expected = set(contract.eval_ids)
    seen: dict[str, int] = {}

    for offset, value in enumerate(ids):
        line = offset + 2

        if not value:
            report.record("E404", row=line)
            continue

        seen[value] = seen.get(value, 0) + 1

        if value in expected:
            continue

        # 평가셋에 없는 ID. 왜 그런지 가장 구체적인 코드를 고른다.
        if contract.train_id_pattern and contract.train_id_pattern.fullmatch(value):
            report.record("E407", row=line, sample=value)
        elif not contract.id_pattern.fullmatch(value):
            report.record("E405", row=line, sample=value)
        else:
            report.record("E403", row=line, sample=value)

    # 중복 ID는 참가자 자신의 값이라 그대로 보여줘도 평가셋이 새지 않는다.
    for value, count in sorted(seen.items()):
        if count > 1:
            report.record("E402", sample=f"{value} ({count}회)")

    missing = expected - set(ids)
    if missing:
        finding = report.record("E401")
        # count 는 실제 누락 건수로 맞춘다. record() 가 1 로 올려 둔 값을 덮어쓴다.
        finding.count = len(missing)
        # 누락 ID는 우리 쪽 자료다. 운영 로그에만 남고 참가자 응답에는
        # Finding.to_participant() 가 제외한다 (leaks_eval_set=True).
        finding.samples.extend(sorted(missing)[:MAX_SAMPLES])

    missing_count = len(missing)

    if contract.expected_rows is not None and len(ids) != len(expected):
        detail = (
            f"예측 {len(ids)}행 / 평가 입력 {len(expected)}건"
            if contract.reveal_expected_row_count
            else f"예측 {len(ids)}행"
        )
        report.record("E302", sample=detail)

    report.summary["missing_ids"] = missing_count
    report.summary["duplicate_ids"] = sum(1 for c in seen.values() if c > 1)


def _check_labels(labels: list[str], contract: Contract, report: Report) -> None:
    classes = frozenset(contract.classes)
    used: set[str] = set()

    for offset, value in enumerate(labels):
        line = offset + 2

        if not value.strip():
            report.record("E501", row=line)
            continue

        if value in classes:
            used.add(value)
            continue

        lowered = value.strip().casefold()

        if lowered in NULLISH:
            report.record("E505", row=line, sample=value)
            continue

        if INT_INDEX.fullmatch(value.strip()):
            report.record("E504", row=line, sample=value)
            continue

        original = _looks_like_truncated_decimal(value.strip(), classes)
        if original is not None:
            report.record("E507", row=line, sample=f"{value} → {original} 로 보임")
            continue

        matched = _case_insensitive_match(value, classes)
        if matched is not None:
            report.record("E503", row=line, sample=f"{value!r} vs {matched!r}")
            continue

        report.record("E502", row=line, sample=value)

    if labels and len(used) == 1 and not report.has("E502"):
        report.record("E506", sample=next(iter(used)))

    unused = classes - used
    if used and unused:
        finding = report.record("W904")
        finding.count = len(unused)
        finding.samples.extend(sorted(unused)[:20])

    report.summary["classes_used"] = len(used)
    report.summary["classes_allowed"] = len(classes)
