"""오류 코드 체계와 검증 결과 자료구조.

참가자에게 돌려줄 메시지와 운영 로그용 상세를 분리한다.
`leaks_eval_set=True` 인 코드의 `samples` 는 숨김 평가 ID 집합을 드러내므로
참가자 응답에 절대 포함하지 않는다. CATH 원본이 공개 자료여서 평가 ID가
노출되면 정답 역추적 난이도가 내려간다 (docs/dataset.md 의 경고).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

Severity = Literal["error", "warning"]

MAX_SAMPLES = 20
"""코드별로 보관할 예시 개수 상한.

팀당 제출이 10회뿐이므로 첫 오류에서 멈추지 않고 모아서 보고한다.
대신 응답 크기가 평가셋 크기(5,387행)만큼 커지지 않도록 상한을 둔다.
"""


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    severity: Severity
    message: str
    hint: str
    leaks_eval_set: bool = False


def _s(
    code: str,
    severity: Severity,
    message: str,
    hint: str,
    leaks_eval_set: bool = False,
) -> ErrorSpec:
    return ErrorSpec(code, severity, message, hint, leaks_eval_set)


SPECS: dict[str, ErrorSpec] = {
    # --- E1xx 파일·인코딩 ---------------------------------------------------
    "E101": _s(
        "E101", "error",
        "예측 파일을 찾을 수 없습니다.",
        "inference.py 가 계약에 명시된 출력 경로에 예측 파일을 저장하는지 확인하세요. "
        "상대 경로는 작업 디렉터리에 따라 달라지므로 계약이 지정한 경로를 그대로 쓰세요.",
    ),
    "E102": _s(
        "E102", "error",
        "예측 파일이 비어 있습니다.",
        "추론이 중간에 종료됐을 수 있습니다. 파일 핸들을 닫는지, 예외로 빠져나가지 않는지 확인하세요.",
    ),
    "E103": _s(
        "E103", "error",
        "예측 파일 크기가 상한을 초과했습니다.",
        "id,label 두 컬럼만 저장하세요. 클래스별 확률이나 중간 산출물을 같은 파일에 쓰지 않습니다.",
    ),
    "E104": _s(
        "E104", "error",
        "예측 파일이 UTF-8 로 읽히지 않습니다.",
        "UTF-8 로 저장하세요: open(path, 'w', encoding='utf-8', newline='') "
        "또는 df.to_csv(path, index=False, encoding='utf-8').",
    ),
    "E105": _s(
        "E105", "error",
        "CSV 로 해석할 수 없습니다.",
        "구분자가 쉼표인지, 따옴표 짝이 맞는지 확인하세요. csv 모듈이나 to_csv 사용을 권장합니다.",
    ),
    "E106": _s(
        "E106", "error",
        "예측 파일에 NUL 바이트 등 바이너리 내용이 있습니다.",
        "pickle·npy·parquet 가 아니라 텍스트 CSV 로 저장해야 합니다.",
    ),

    # --- E2xx 헤더·스키마 ---------------------------------------------------
    "E201": _s(
        "E201", "error",
        "헤더 행이 없습니다.",
        "첫 줄에 컬럼명 id,label 을 그대로 적으세요. to_csv 는 header=True 가 기본입니다.",
    ),
    "E202": _s(
        "E202", "error",
        "필수 컬럼이 누락됐습니다.",
        "컬럼명을 철자·대소문자까지 똑같이 쓰세요. 'ID' 나 'prediction' 은 허용되지 않습니다.",
    ),
    "E203": _s(
        "E203", "error",
        "허용되지 않은 컬럼이 포함됐습니다.",
        "예측 파일에는 계약 컬럼만 남기세요. to_csv(index=False) 를 빠뜨려 "
        "인덱스 컬럼이 함께 저장되지 않았는지 확인하세요.",
    ),
    "E204": _s(
        "E204", "error",
        "컬럼 순서가 계약과 다릅니다.",
        "계약 순서대로 배치하세요: id,label.",
    ),
    "E205": _s(
        "E205", "error",
        "같은 컬럼명이 두 번 이상 있습니다.",
        "DataFrame 병합 과정에서 컬럼이 중복됐는지 확인하세요.",
    ),

    # --- E3xx 행 구조 -------------------------------------------------------
    "E301": _s(
        "E301", "error",
        "필드 수가 헤더와 다른 행이 있습니다.",
        "값에 쉼표가 들어가면 따옴표로 감싸야 합니다. csv 모듈을 쓰면 자동 처리됩니다.",
    ),
    "E302": _s(
        "E302", "error",
        "예측 행 수가 평가 입력 개수와 다릅니다.",
        "평가 입력의 모든 ID를 정확히 한 번씩 출력하세요.",
    ),
    "E303": _s(
        "E303", "error",
        "빈 행이 있습니다.",
        "파일 끝 줄바꿈 외에 빈 줄을 남기지 마세요.",
    ),

    # --- E4xx ID ------------------------------------------------------------
    "E401": _s(
        "E401", "error",
        "평가 입력에 있는 ID가 예측에 빠졌습니다.",
        "평가 입력 파일의 ID 전체를 순회해 예측을 만드세요. "
        "예외로 건너뛴 샘플이나 dropna 로 사라진 행이 없는지 확인하세요.",
        leaks_eval_set=True,
    ),
    "E402": _s(
        "E402", "error",
        "같은 ID가 두 번 이상 예측됐습니다.",
        "ID 기준으로 중복을 제거하세요. 배치 추론 결과를 이어 붙일 때 겹치는 구간이 없는지 확인하세요.",
    ),
    "E403": _s(
        "E403", "error",
        "평가 입력에 없는 ID가 예측에 있습니다.",
        "평가 입력에서 읽은 ID를 그대로 출력하세요.",
    ),
    "E404": _s(
        "E404", "error",
        "ID가 빈 값인 행이 있습니다.",
        "id 컬럼에 결측이 없도록 하세요.",
    ),
    "E405": _s(
        "E405", "error",
        "ID 형식이 계약과 맞지 않습니다.",
        "평가 입력의 ID 문자열을 가공하지 말고 그대로 출력하세요. "
        "숫자로 변환하면 TEST_000001 이 1 로 바뀌어 0 채움이 사라집니다.",
    ),
    "E406": _s(
        "E406", "warning",
        "ID 앞뒤에 공백이 있습니다.",
        "ID를 strip() 해서 저장하세요. 현재 설정에서는 공백을 제거한 뒤 계속 진행합니다.",
    ),
    "E407": _s(
        "E407", "error",
        "예측에 학습 데이터 ID(TRAIN_...)가 들어 있습니다.",
        "example_input.csv 는 학습 데이터에서 복사한 예제라 ID가 TRAIN_ 으로 시작합니다. "
        "추론 코드가 예제 입력이 아니라 채점용 평가 입력 경로를 읽는지 확인하세요.",
    ),

    # --- E5xx 라벨 ----------------------------------------------------------
    "E501": _s(
        "E501", "error",
        "라벨이 빈 값인 행이 있습니다.",
        "모든 평가 샘플에 허용 클래스 중 하나를 반드시 지정하세요.",
    ),
    "E502": _s(
        "E502", "error",
        "허용 클래스 목록에 없는 라벨이 있습니다.",
        "train.csv 의 label 고유값을 그대로 사용하세요.",
    ),
    "E503": _s(
        "E503", "error",
        "대소문자나 앞뒤 공백만 다른 라벨이 있습니다.",
        "클래스 문자열은 공백·대소문자까지 일치해야 합니다.",
    ),
    "E504": _s(
        "E504", "error",
        "라벨이 클래스 문자열이 아니라 클래스 인덱스(정수)로 보입니다.",
        "predict() 결과를 클래스 문자열로 역변환하세요. "
        "LabelEncoder 를 썼다면 encoder.inverse_transform 을 거쳐야 합니다.",
    ),
    "E505": _s(
        "E505", "error",
        "라벨에 결측 표현(nan, none, null 등)이 있습니다.",
        "예측이 실패한 샘플에도 허용 클래스 중 하나를 채우세요.",
    ),
    "E506": _s(
        "E506", "warning",
        "모든 예측이 한 클래스입니다.",
        "모델 로딩이나 특징 전처리가 실패했을 수 있습니다. 점수는 그대로 계산됩니다.",
    ),
    "E507": _s(
        "E507", "error",
        "라벨이 숫자로 변환돼 끝자리 0이 사라졌습니다.",
        "label 은 'C.A' 형태의 문자열입니다. 숫자로 읽으면 끝의 0이 사라져 다른 값이 됩니다. "
        "pd.read_csv(..., dtype=str) 로 읽고 문자열로 저장하세요.",
    ),

    # --- E9xx 채점기·운영 측 오류 (참가자 책임 아님) ------------------------
    "E901": _s(
        "E901", "error",
        "채점기 설정 오류: 허용 클래스 목록이 확정되지 않았습니다.",
        "운영 측 조치가 필요합니다. 데이터셋의 metadata.json labels 또는 train.csv 에서 "
        "클래스 목록을 주입하세요.",
    ),
    "E902": _s(
        "E902", "error",
        "채점기 설정 오류: 평가 ID 목록을 읽을 수 없습니다.",
        "운영 측 조치가 필요합니다.",
    ),
    "W903": _s(
        "W903", "warning",
        "파일에 UTF-8 BOM이 있습니다.",
        "현재 설정에서는 허용합니다. BOM 없는 UTF-8 저장을 권장합니다.",
    ),
    "W904": _s(
        "W904", "warning",
        "예측에 사용되지 않은 허용 클래스가 있습니다.",
        "Macro F1 은 모든 허용 클래스를 대상으로 계산하므로, 예측하지 않은 클래스는 "
        "해당 클래스 F1 을 0으로 만듭니다. 오류는 아닙니다.",
    ),
}

OPERATOR_CODES = frozenset({"E901", "E902"})
"""참가자 잘못이 아니라 운영 측 설정 문제인 코드. 제출 횟수 차감 정책(Q4)에서 제외해야 한다."""


@dataclass
class Finding:
    """오류/경고 1건. 같은 코드의 반복은 count 로 모은다."""

    code: str
    count: int = 0
    rows: list[int] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)

    @property
    def spec(self) -> ErrorSpec:
        return SPECS[self.code]

    @property
    def severity(self) -> Severity:
        return self.spec.severity

    def add(self, row: int | None = None, sample: str | None = None) -> None:
        self.count += 1
        if row is not None and len(self.rows) < MAX_SAMPLES:
            self.rows.append(row)
        if sample is not None and len(self.samples) < MAX_SAMPLES:
            self.samples.append(sample)

    def to_participant(self) -> dict[str, Any]:
        """참가자에게 반환할 형태. 숨김 평가 ID 집합을 드러내지 않는다."""
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.spec.message,
            "hint": self.spec.hint,
            "count": self.count,
        }
        if not self.spec.leaks_eval_set:
            if self.rows:
                out["rows"] = self.rows
            if self.samples:
                out["samples"] = self.samples
        return out

    def to_operator(self) -> dict[str, Any]:
        """운영 로그용. 전체 상세를 포함한다."""
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.spec.message,
            "count": self.count,
            "rows": self.rows,
            "samples": self.samples,
            "leaks_eval_set": self.spec.leaks_eval_set,
        }


@dataclass
class Report:
    """검증 결과. ok=True 이면 채점 단계로 넘겨도 된다."""

    contract_version: str = "unknown"
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    _index: dict[str, Finding] = field(default_factory=dict, repr=False)

    def record(
        self,
        code: str,
        row: int | None = None,
        sample: str | None = None,
    ) -> Finding:
        if code not in SPECS:
            raise KeyError(f"정의되지 않은 오류 코드: {code}")
        finding = self._index.get(code)
        if finding is None:
            finding = Finding(code)
            self._index[code] = finding
            self.findings.append(finding)
        finding.add(row=row, sample=sample)
        return finding

    def has(self, code: str) -> bool:
        return code in self._index

    def get(self, code: str) -> Finding | None:
        return self._index.get(code)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def operator_fault(self) -> bool:
        """운영 측 설정 오류로 실패했는지. 제출 횟수 차감 판단에 쓴다."""
        return any(f.code in OPERATOR_CODES for f in self.errors)

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]

    def participant_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "contract_version": self.contract_version,
            "errors": [f.to_participant() for f in self.errors],
            "warnings": [f.to_participant() for f in self.warnings],
        }

    def operator_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "contract_version": self.contract_version,
            "operator_fault": self.operator_fault,
            "summary": self.summary,
            "findings": [f.to_operator() for f in self.findings],
        }

    def to_json(self, *, operator: bool = False, indent: int | None = 2) -> str:
        payload = self.operator_payload() if operator else self.participant_payload()
        return json.dumps(payload, ensure_ascii=False, indent=indent)


def describe_codes(codes: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """오류 코드 표 덤프. 문서 생성과 연동 예제에 쓴다."""
    selected = list(codes) if codes is not None else list(SPECS)
    return [
        {
            "code": c,
            "severity": SPECS[c].severity,
            "message": SPECS[c].message,
            "hint": SPECS[c].hint,
            "leaks_eval_set": SPECS[c].leaks_eval_set,
            "operator_fault": c in OPERATOR_CODES,
        }
        for c in selected
    ]
