import csv
import io


class SubmissionError(ValueError):
    """The message is shown to participants, so it reports counts only and never echoes
    values from the prediction file (they could carry hidden evaluation input)."""


def validate(content: bytes, expected_ids: list[str], allowed_labels: list[str]):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SubmissionError("UTF-8 CSV 파일만 허용됩니다.")
    if "\x00" in text:
        raise SubmissionError("잘못된 CSV 문자입니다.")
    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if reader.fieldnames != ["id", "label"]:
            raise SubmissionError("컬럼은 순서대로 id,label이어야 합니다.")
        records = list(reader)
    except csv.Error:
        raise SubmissionError("CSV를 읽을 수 없습니다.")
    if any(None in r or any(v is None or not v.strip() for v in r.values()) for r in records):
        raise SubmissionError("누락 값 또는 잘못된 CSV 열 수가 있습니다.")
    ids = [r["id"] for r in records]
    if len(set(ids)) != len(ids):
        raise SubmissionError("중복 ID가 있습니다.")
    expected = set(expected_ids)
    actual = set(ids)
    errors = []
    if len(records) != len(expected_ids):
        errors.append(f"행 수: {len(records)} / 필요: {len(expected_ids)}")
    if expected - actual:
        errors.append(f"누락된 ID: {len(expected - actual)}개")
    if actual - expected:
        errors.append(f"알 수 없는 ID: {len(actual - expected)}개")
    unknown = set(r["label"] for r in records) - set(allowed_labels)
    if unknown:
        errors.append(f"허용되지 않은 label: {len(unknown)}종")
    if errors:
        raise SubmissionError("; ".join(errors))
    lookup = {r["id"]: r["label"] for r in records}
    return [lookup[id] for id in expected_ids]
