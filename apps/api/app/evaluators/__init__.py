from ..config import EVALUATOR


def get_evaluator():
    if EVALUATOR == "docker":
        from .docker import DockerEvaluator
        return DockerEvaluator()
    if EVALUATOR == "remote":
        from .remote import RemoteEvaluator
        return RemoteEvaluator()
    if EVALUATOR == "sandbox":
        from .sandbox import SandboxEvaluator
        return SandboxEvaluator()
    from .mock import MockEvaluator
    return MockEvaluator()
