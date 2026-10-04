from ..config import EVALUATOR


def get_evaluator():
    if EVALUATOR == "docker":
        from .docker import DockerEvaluator
        return DockerEvaluator()
    from .mock import MockEvaluator
    return MockEvaluator()
