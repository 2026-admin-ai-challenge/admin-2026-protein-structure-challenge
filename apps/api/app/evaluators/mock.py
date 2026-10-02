"""Development evaluator. Produces FAKE scores so the whole flow can be demonstrated
without evaluation data. Never use it for a real competition.

A ZIP may include `mock.json` at its root to steer the result, e.g.
{"fail": "timeout"}, {"sleep": 20}, {"public": 0.71, "private": 0.64}.
"""
import json
import os
import time
import zipfile

from ..errors import FAILURES
from ..zipcheck import ZipRejected, inspect
from .base import Evaluator, Outcome, failure

MOCK_DELAY_SECONDS = float(os.getenv("MOCK_DELAY_SECONDS", "3"))


def _controls(zip_path):
    try:
        with zipfile.ZipFile(zip_path) as archive:
            if "mock.json" in archive.namelist() and archive.getinfo("mock.json").file_size <= 4096:
                data = json.loads(archive.read("mock.json"))
                return data if isinstance(data, dict) else {}
    except (ValueError, KeyError, zipfile.BadZipFile):
        pass
    return {}


class MockEvaluator(Evaluator):
    name = "mock"

    def ready(self):
        return True, "mock evaluator: scores are fake"

    def run(self, submission, zip_path, tick):
        try:
            inspect(zip_path)
        except ZipRejected as error:
            return failure("zip_invalid", str(error))
        controls = _controls(zip_path)
        try:
            delay = min(float(controls.get("sleep", MOCK_DELAY_SECONDS)), 900)
        except (TypeError, ValueError):
            delay = MOCK_DELAY_SECONDS
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            tick()
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        code = controls.get("fail")
        if code:
            code = code if code in FAILURES else "runtime_error"
            return failure(code, log=f"mock failure requested by mock.json: {code}")
        seed = submission.sha256 or "0" * 64
        public = 0.2 + 0.6 * int(seed[:8], 16) / 0xFFFFFFFF
        private = public + 0.1 * (int(seed[8:16], 16) / 0xFFFFFFFF - 0.5)
        try:
            public = min(1.0, max(0.0, float(controls.get("public", public))))
            private = min(1.0, max(0.0, float(controls.get("private", private))))
        except (TypeError, ValueError):
            pass
        return Outcome(ok=True, scores={"public": round(public, 5), "private": round(private, 5)},
                       log="mock evaluator: fake score derived from the ZIP hash")
