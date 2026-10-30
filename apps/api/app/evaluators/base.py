import threading
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


class Shared:
    """What the evaluators of one worker process know in common about the machine they run
    on. app.worker hands one to every slot (they are threads), so the GPU machine is checked
    and its GPU load read once for all slots instead of once per slot: each is an SSH
    connection, and a busy machine refuses new ones."""

    def __init__(self):
        self.checking, self.reading = threading.Lock(), threading.Lock()
        self.verdicts = {}  # what was checked -> (valid until, checks, facts)
        self.proved = {}    # what was checked -> the slow check (a real GPU step) holds until
        self.load = None    # (machine, read at, GPU load, problem)

    def forget(self):
        """Every slot checks the machine again before its next run. Without the lock: a slot
        whose run just failed must not wait for another slot's check to finish."""
        self.verdicts.clear()
        self.proved.clear()


class Evaluator:
    name = "base"
    # EVAL_GPU_PICK=free (remote.py): the worker hands each run one of free_gpus().
    picks_gpus = False
    # Why the queue waits although the evaluator is ready (no free GPU), for the admin page.
    gpu_note = None
    # A Shared, for evaluators that ask a machine over SSH (remote.py); app.worker's slots share one.
    shared = None

    def configure(self, settings):
        """Takes the competition settings before each check; `settings` may be None."""

    def ready(self):
        """(ok, detail). A worker takes no submissions while its evaluator is not ready."""
        return True, "ready"

    def free_gpus(self, held=()):
        """With picks_gpus: the GPUs a run could take now, best first, leaving out `held` (the
        ones our running submissions have). Empty while none is free."""
        return []

    def run(self, submission, zip_path, tick) -> Outcome:
        """`tick()` must be called regularly so the worker can report liveness."""
        raise NotImplementedError
