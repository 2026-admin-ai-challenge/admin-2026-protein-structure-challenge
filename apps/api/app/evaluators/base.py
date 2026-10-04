from dataclasses import dataclass


@dataclass
class Outcome:
    """Result of running one submission.

    A real evaluator returns `predictions` (the raw CSV the participant code wrote); the
    worker validates and scores it against hidden labels. The mock returns `scores`
    directly. On failure, `message` is shown to the team and `log` only to organizers.
    """
    ok: bool
    predictions: bytes | None = None
    scores: dict | None = None
    failure_code: str | None = None
    message: str | None = None
    log: str | None = None


def failure(code, message=None, log=None):
    return Outcome(ok=False, failure_code=code, message=message, log=log)


class Evaluator:
    name = "base"

    def ready(self):
        """(ok, detail). A worker takes no submissions while its evaluator is not ready."""
        return True, "ready"

    def run(self, submission, zip_path, tick) -> Outcome:
        """`tick()` must be called regularly so the worker can report liveness."""
        raise NotImplementedError
