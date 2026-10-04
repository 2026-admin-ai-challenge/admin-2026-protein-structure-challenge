"""예측 출력 계약 로딩.

계약 값은 코드에 박지 않고 `contract/prediction_contract.json` 에서 읽는다.
허용 클래스 목록과 평가 ID 목록은 데이터셋 산출물에서 주입한다.
둘 중 하나라도 비어 있으면 검증기는 참가자 파일을 탓하지 않고
운영 측 설정 오류(E901/E902)로 보고한다.

표준 라이브러리만 사용한다. 채점 작업자가 pandas 버전에 상관없이
같은 판정을 내려야 하고, pandas 는 형식 오류를 조용히 교정해 버려서
형식 검증기로는 적합하지 않다 (예: "1.10" -> 1.1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2] / "contract" / "prediction_contract.json"
)

PLACEHOLDER_TOKENS = frozenset({"PLACEHOLDER", "TODO", "UNCONFIRMED"})


@dataclass
class Contract:
    """검증에 필요한 계약 값."""

    version: str
    status: str

    # 출력 파일
    columns: tuple[str, ...]
    column_order_strict: bool
    allow_extra_columns: bool
    require_header: bool
    encoding: str
    allow_bom: bool
    max_file_bytes: int
    expected_rows: int | None

    # ID
    id_pattern: re.Pattern[str]
    train_id_pattern: re.Pattern[str] | None
    id_case_sensitive: bool
    id_strip_whitespace: bool
    reveal_expected_row_count: bool

    # 라벨
    label_case_sensitive: bool
    label_strip_whitespace: bool
    expected_class_count: int | None

    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # 런타임 주입 데이터
    classes: tuple[str, ...] = ()
    eval_ids: tuple[str, ...] = ()

    @property
    def id_column(self) -> str:
        return self.columns[0]

    @property
    def label_column(self) -> str:
        return self.columns[1]

    @property
    def has_classes(self) -> bool:
        return bool(self.classes)

    @property
    def has_eval_ids(self) -> bool:
        return bool(self.eval_ids)

    def with_classes(self, classes: list[str] | tuple[str, ...]) -> "Contract":
        self.classes = tuple(classes)
        return self

    def with_eval_ids(self, eval_ids: list[str] | tuple[str, ...]) -> "Contract":
        self.eval_ids = tuple(eval_ids)
        return self

    def undecided(self) -> dict[str, str]:
        return dict(self.raw.get("undecided", {}))


def load_contract(path: str | Path | None = None) -> Contract:
    """계약 JSON 을 읽어 Contract 로 만든다."""
    path = Path(path) if path else DEFAULT_CONTRACT_PATH
    data = json.loads(path.read_text(encoding="utf-8"))

    out = data["output"]
    ident = data["id"]
    label = data["label"]

    columns = tuple(out["columns"])
    if len(columns) != 2:
        raise ValueError(
            f"현재 검증기는 컬럼 2개(id, label) 계약만 지원합니다: {columns}"
        )

    train_pattern = ident.get("train_id_pattern")

    return Contract(
        version=data["contract_version"],
        status=data.get("status", "UNKNOWN"),
        columns=columns,
        column_order_strict=bool(out.get("column_order_strict", True)),
        allow_extra_columns=bool(out.get("allow_extra_columns", False)),
        require_header=bool(out.get("require_header", True)),
        encoding=out.get("encoding", "utf-8"),
        allow_bom=bool(out.get("allow_bom", True)),
        max_file_bytes=int(out.get("max_file_bytes", 10 * 1024 * 1024)),
        expected_rows=out.get("expected_rows"),
        id_pattern=re.compile(ident["pattern"]),
        train_id_pattern=re.compile(train_pattern) if train_pattern else None,
        id_case_sensitive=bool(ident.get("case_sensitive", True)),
        id_strip_whitespace=bool(ident.get("strip_whitespace", False)),
        reveal_expected_row_count=bool(ident.get("reveal_expected_row_count", True)),
        label_case_sensitive=bool(label.get("case_sensitive", True)),
        label_strip_whitespace=bool(label.get("strip_whitespace", False)),
        expected_class_count=label.get("expected_class_count"),
        raw=data,
    )


def load_classes(path: str | Path) -> list[str]:
    """허용 클래스 목록을 텍스트 파일에서 읽는다.

    주석(#)과 빈 줄은 무시한다. 플레이스홀더만 들어 있으면 빈 목록을 돌려주고,
    검증기가 E901 로 보고하게 한다.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    classes = [
        s
        for line in lines
        if (s := line.strip()) and not s.startswith("#")
    ]
    if any(c in PLACEHOLDER_TOKENS for c in classes):
        return []
    return classes


def load_classes_from_metadata(path: str | Path) -> list[str]:
    """데이터셋 `metadata.json` 의 labels 배열에서 클래스 목록을 읽는다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    labels = data.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError(f"{path} 에 labels 배열이 없습니다.")
    return [str(x) for x in labels]


def load_column_from_csv(path: str | Path, column: str) -> list[str]:
    """CSV 한 컬럼을 문자열 목록으로 읽는다.

    평가 ID 목록(`test.csv`/`labels.csv` 의 id)과 클래스 목록(`train.csv` 의
    label 고유값)을 읽는 데 쓴다. 숫자 변환을 하지 않아 "1.10" 이 1.1 로
    바뀌지 않는다.
    """
    import csv

    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise ValueError(
                f"{path} 에 '{column}' 컬럼이 없습니다. 컬럼: {reader.fieldnames}"
            )
        return [row[column] for row in reader]


def load_eval_ids(path: str | Path, column: str = "id") -> list[str]:
    return load_column_from_csv(path, column)


def load_classes_from_train_csv(path: str | Path, column: str = "label") -> list[str]:
    return sorted(set(load_column_from_csv(path, column)))
