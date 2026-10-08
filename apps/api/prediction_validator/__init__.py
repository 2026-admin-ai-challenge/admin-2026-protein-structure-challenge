"""ADMIN 2026 대회 예측 출력 검증기.

채점 작업자가 참가자 제출 모델의 추론 결과를 점수 계산 전에 검사한다.

채점 작업자에서 쓸 때는 `worker_api.validate_submission_output` 하나만 호출하면 된다.
"""

from .contract import (
    Contract,
    load_classes,
    load_classes_from_metadata,
    load_classes_from_train_csv,
    load_contract,
    load_eval_ids,
)
from .errors import MAX_SAMPLES, OPERATOR_CODES, SPECS, Finding, Report, describe_codes
from .validator import validate_file, validate_text
from .worker_api import (
    ValidationOutcome,
    validate_submission_output,
    verify_contract_against_dataset,
)

__all__ = [
    "Contract",
    "Finding",
    "MAX_SAMPLES",
    "OPERATOR_CODES",
    "Report",
    "SPECS",
    "ValidationOutcome",
    "describe_codes",
    "load_classes",
    "load_classes_from_metadata",
    "load_classes_from_train_csv",
    "load_contract",
    "load_eval_ids",
    "validate_file",
    "validate_submission_output",
    "validate_text",
    "verify_contract_against_dataset",
]

__version__ = "0.2.0"
