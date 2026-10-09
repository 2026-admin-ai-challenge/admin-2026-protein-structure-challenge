"""Checks a prediction file with the data team's validator (`prediction_validator`).

Participants see error codes, messages and counts only. Their code read the hidden
evaluation input, so values from the prediction file are never echoed back to them;
the validator's full detail goes to the organizer log.
"""
import csv
import io
import json
import tempfile
from pathlib import Path

from prediction_validator import validate_submission_output, verify_contract_against_dataset

from ..config import PREDICTION_CONTRACT

DETAIL_CHARS = 8000  # validator detail kept in the organizer log, after the container output


class OutputRejected(ValueError):
    """The message is safe for participants. `detail` is for organizers only."""

    def __init__(self, message, detail, operator_fault):
        super().__init__(message)
        self.detail, self.operator_fault = detail, operator_fault


def check(content: bytes, ids: list[str], classes: list[str]):
    """Returns the predicted labels in `ids` order and a summary line for the organizer log."""
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "predictions.csv"
        path.write_bytes(content)
        outcome = validate_submission_output(path, contract_path=PREDICTION_CONTRACT, eval_ids=ids, classes=classes)
    if not outcome.ok:
        detail = json.dumps(outcome.operator_detail, ensure_ascii=False)[:DETAIL_CHARS]
        # participant_error_lines keeps the code, message, count and the fixed fix-it
        # hint, and leaves out warnings that are not why the submission was rejected.
        # The hint is a constant in the validator, so no file or evaluation value can
        # reach it, and it is what lets a team spend one fewer submission on a typo.
        message = " ".join(outcome.participant_error_lines)
        raise OutputRejected(message, f"{outcome.summary_line}\n{detail}", outcome.operator_fault)
    return _in_order(content, ids), outcome.summary_line


def contract_problem(ids: list[str]):
    """None when the copied contract matches the hidden evaluation IDs, otherwise why not.
    The worker checks this before scoring, as the contract's drift guard asks: scoring
    with a stale contract (e.g. the wrong expected_rows) would blame teams for it (E903)."""
    report = verify_contract_against_dataset(contract_path=PREDICTION_CONTRACT, eval_ids=ids)
    if report.ok:
        return None
    return "prediction contract does not match the dataset: " + "; ".join(
        f"{finding.code} {', '.join(finding.samples)}".strip() for finding in report.errors)


def _in_order(content, ids):
    """Reads a file the validator accepted. Like the validator, it strips header names and IDs."""
    rows = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""))
    header = [name.strip() for name in next(rows)]
    at_id, at_label = header.index("id"), header.index("label")
    lookup = {row[at_id].strip(): row[at_label] for row in rows if row}
    return [lookup[id] for id in ids]
