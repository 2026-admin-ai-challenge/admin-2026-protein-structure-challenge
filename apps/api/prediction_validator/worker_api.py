"""채점 작업자 연동 표면 (Day 4 산출물).

웹/API 팀의 채점 작업자는 이 모듈의 함수 하나만 쓰면 된다.
검증기를 subprocess 로 띄울 필요 없이 같은 프로세스에서 호출할 수 있고,
반환값이 DB 기록과 참가자 응답에 바로 들어갈 형태다.

사용 예
-------
    from prediction_validator import validate_submission_output

    outcome = validate_submission_output(
        prediction_path=container_output / "predictions.csv",
        eval_ids_csv=private_root / "test.csv",       # 정답 아님, 입력 ID만
        classes_metadata=public_root / "metadata.json",
    )

    if not outcome.ok:
        if outcome.operator_fault:
            mark_submission_retryable(submission_id, outcome.operator_detail)
        else:
            mark_submission_failed(submission_id, outcome.participant_response)
        return

    score_submission(outcome.rows)   # 검증을 통과한 뒤에만 채점한다

주의
----
- `classes_*` 와 `eval_ids_csv` 는 **채점기 쪽 신뢰 저장소**에서 읽는다.
  추론 컨테이너 안에서 이 함수를 호출하지 않는다. 컨테이너에는 평가 입력만
  읽기 전용으로 들어가고, 검증·채점은 컨테이너 밖에서 수행한다
  (ADMIN_대회_개발_디렉팅.md 4절).
- `participant_response` 만 참가자에게 보낸다. `operator_detail` 에는
  누락된 평가 ID 예시가 들어 있어 참가자에게 노출하면 평가셋이 샌다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contract import (
    Contract,
    load_classes,
    load_classes_from_metadata,
    load_classes_from_train_csv,
    load_contract,
    load_eval_ids,
)
from .errors import Report
from .validator import validate_file


@dataclass
class ValidationOutcome:
    """검증 결과 묶음. 채점 작업자가 이 값만 보고 분기할 수 있다."""

    ok: bool
    contract_version: str
    operator_fault: bool
    participant_response: dict[str, Any]
    operator_detail: dict[str, Any]
    participant_lines: list[str] = field(default_factory=list)
    """참가자에게 보여줄 한 줄 메시지 목록(오류 + 경고). 조치 안내를 함께 담는다."""

    participant_error_lines: list[str] = field(default_factory=list)
    """거절 사유만 담은 한 줄 메시지 목록. 제출을 거절할 때 쓴다."""

    error_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    report: Report | None = field(default=None, repr=False)

    @property
    def codes(self) -> list[str]:
        """오류와 경고를 합친 전체 코드 목록."""
        return self.error_codes + self.warning_codes

    @property
    def summary_line(self) -> str:
        """DB status_message 컬럼이나 로그 한 줄용 요약."""
        if self.ok:
            if self.warning_codes:
                return (
                    f"검증 통과, 경고 {len(self.warning_codes)}건 "
                    f"({', '.join(self.warning_codes)}) · 계약 {self.contract_version}"
                )
            return f"검증 통과 (계약 {self.contract_version})"
        kind = "채점기 설정 오류" if self.operator_fault else "출력 형식 오류"
        return f"{kind}: {', '.join(self.error_codes)}"


def build_contract(
    *,
    contract_path: str | Path | None = None,
    classes_metadata: str | Path | None = None,
    classes_train_csv: str | Path | None = None,
    classes_file: str | Path | None = None,
    eval_ids_csv: str | Path | None = None,
    eval_ids: list[str] | None = None,
    classes: list[str] | None = None,
) -> Contract:
    """계약을 읽고 클래스 목록·평가 ID를 주입한다.

    클래스 목록은 metadata.json -> train.csv -> classes.txt 순으로 찾는다.
    아무것도 못 찾으면 빈 목록으로 남고, 검증 시 E901 로 보고된다.
    """
    contract = load_contract(contract_path)

    resolved_classes = classes
    if resolved_classes is None:
        if classes_metadata and Path(classes_metadata).is_file():
            resolved_classes = load_classes_from_metadata(classes_metadata)
        elif classes_train_csv and Path(classes_train_csv).is_file():
            resolved_classes = load_classes_from_train_csv(classes_train_csv)
        elif classes_file and Path(classes_file).is_file():
            resolved_classes = load_classes(classes_file)
    contract.with_classes(resolved_classes or [])

    resolved_ids = eval_ids
    if resolved_ids is None and eval_ids_csv and Path(eval_ids_csv).is_file():
        resolved_ids = load_eval_ids(eval_ids_csv)
    contract.with_eval_ids(resolved_ids or [])

    return contract


def verify_contract_against_dataset(
    *,
    contract_path: str | Path | None = None,
    eval_ids: list[str] | None = None,
    eval_ids_csv: str | Path | None = None,
) -> Report:
    """계약 파일이 현재 데이터셋과 맞는지 확인한다. **작업자 시작 시 한 번 호출한다.**

    데이터셋은 품질 점검 결과에 따라 재생성되고(데이터 저장소 PR #5·#11·#13),
    그때 평가 건수가 바뀐다. 계약이 따라오지 않거나 다른 저장소의 계약 사본이
    낡으면 낡은 계약으로 채점하게 된다.

    이 검사를 제출마다 하지 않는 이유: 평가 ID 일부만 주입하는 호출이 정당하게
    존재한다(테스트, 개발 도구). 어긋남은 제출의 성질이 아니라 설정의 성질이다.

    사용 예 (작업자 시작 시):

        report = verify_contract_against_dataset(
            contract_path=PREDICTION_CONTRACT,
            eval_ids_csv=PRIVATE_ROOT / "test.csv",
        )
        if not report.ok:
            raise SystemExit(report.to_json(operator=True))

    CI 에서도 같은 함수를 돌리면 배포 전에 잡힌다.
    """
    contract = load_contract(contract_path)
    report = Report(contract_version=contract.version)

    ids = eval_ids
    if ids is None and eval_ids_csv is not None and Path(eval_ids_csv).is_file():
        ids = load_eval_ids(eval_ids_csv)
    if not ids:
        report.record("E902", sample=str(eval_ids_csv) if eval_ids_csv else "주입 없음")
        return report

    actual = len(set(ids))
    report.summary["contract_expected_rows"] = contract.expected_rows
    report.summary["dataset_eval_ids"] = actual

    if contract.expected_rows is not None and contract.expected_rows != actual:
        report.record(
            "E903",
            sample=f"계약 expected_rows={contract.expected_rows} / 데이터셋 {actual}건",
        )
    return report


def validate_submission_output(
    prediction_path: str | Path,
    *,
    contract_path: str | Path | None = None,
    classes_metadata: str | Path | None = None,
    classes_train_csv: str | Path | None = None,
    classes_file: str | Path | None = None,
    eval_ids_csv: str | Path | None = None,
    eval_ids: list[str] | None = None,
    classes: list[str] | None = None,
) -> ValidationOutcome:
    """제출 추론 결과를 검증한다. 채점 작업자의 유일한 진입점."""
    contract = build_contract(
        contract_path=contract_path,
        classes_metadata=classes_metadata,
        classes_train_csv=classes_train_csv,
        classes_file=classes_file,
        eval_ids_csv=eval_ids_csv,
        eval_ids=eval_ids,
        classes=classes,
    )
    report = validate_file(prediction_path, contract)
    return ValidationOutcome(
        ok=report.ok,
        contract_version=report.contract_version,
        operator_fault=report.operator_fault,
        participant_response=report.participant_payload(),
        participant_lines=report.participant_lines(),
        participant_error_lines=report.participant_lines(errors_only=True),
        operator_detail=report.operator_payload(),
        error_codes=[f.code for f in report.errors],
        warning_codes=[f.code for f in report.warnings],
        report=report,
    )
