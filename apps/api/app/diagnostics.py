"""Participant-safe explanations derived from organizer-only inference logs.

Never echo exception values, source lines, arbitrary module names or file paths:
participant code can put hidden evaluation data in any of those strings.
"""
import re

PACKAGES = {
    "catboost": "catboost", "xgboost": "xgboost", "lightgbm": "lightgbm",
    "torch": "torch", "tensorflow": "tensorflow", "sklearn": "scikit-learn",
    "numpy": "numpy", "pandas": "pandas", "scipy": "scipy", "joblib": "joblib",
}
EXPLANATIONS = {
    "FileNotFoundError": ("필요한 파일을 찾지 못했습니다.", "모델 파일이 ZIP의 model/ 폴더에 포함됐는지, 코드의 상대 경로와 파일명 대소문자가 일치하는지 확인하세요."),
    "ImportError": ("라이브러리 또는 기능을 불러오지 못했습니다.", "학습 환경과 채점 환경의 패키지 버전을 맞추고, 같은 평가 이미지에서 모델 로드와 import를 확인하세요."),
    "KeyError": ("코드가 요청한 키나 컬럼이 없습니다.", "입력 CSV의 컬럼명과 저장한 모델 묶음의 키가 추론 코드와 일치하는지 확인하세요."),
    "ValueError": ("입력값이나 데이터 형식이 코드의 예상과 다릅니다.", "학습·추론의 특징 개수, 컬럼 순서, 자료형과 전처리 방식이 같은지 확인하세요."),
    "TypeError": ("함수 인자 또는 데이터 자료형이 맞지 않습니다.", "오류가 난 함수의 인자와 학습·추론 환경의 라이브러리 버전을 확인하세요."),
    "PermissionError": ("허용되지 않은 경로에 접근했습니다.", "입력과 제출 폴더는 읽기 전용입니다. 임시 파일은 /tmp, 예측 파일은 /output에 저장하세요."),
    "SyntaxError": ("Python 코드의 문법 오류입니다.", "표시된 줄의 문법과 들여쓰기를 확인하고 Python 3.12에서 실행해 보세요."),
    "RuntimeError": ("추론 실행 중 RuntimeError가 발생했습니다.", "모델 로드와 추론을 동일한 평가 이미지에서 재현하세요. 전체 오류 값은 운영진 실행 로그에서 확인할 수 있습니다."),
}


def failure_detail(code, log):
    if code != "runtime_error" or not log:
        return None
    lines = log.splitlines()
    # Only interpret the final exception, never arbitrary earlier stdout messages.
    last = next((line.strip() for line in reversed(lines) if line.strip()), "")
    missing = re.fullmatch(r"ModuleNotFoundError: No module named ['\"]([a-zA-Z0-9_.]+)['\"]", last)
    if missing:
        package = PACKAGES.get(missing.group(1).split(".")[0])
        if package:
            cause = f"채점 환경에서 {package} 라이브러리를 찾지 못했습니다 (ModuleNotFoundError). 모델 파일을 읽을 때도 학습에 사용한 라이브러리가 필요할 수 있습니다."
            help_text = f"운영진에게 평가 이미지의 {package} 지원 여부를 확인하세요. requirements.txt에 적는 것만으로 채점 시 설치되지는 않습니다. 지원되는 공통 이미지로 학습·추론 환경을 맞춘 뒤 다시 제출하세요."
        else:
            cause = "필요한 Python 모듈을 찾지 못했습니다 (ModuleNotFoundError)."
            help_text = "사용한 라이브러리가 평가 이미지에 설치됐는지, 직접 작성한 모듈이 ZIP에 포함됐는지 확인하세요. 채점 중에는 패키지를 설치할 수 없습니다."
    else:
        exception = last.split(":", 1)[0]
        if exception not in EXPLANATIONS:
            return None
        cause, help_text = EXPLANATIONS[exception]
        cause = f"{cause} ({exception})"
    # Fixed entrypoint only. Never return arbitrary submitted paths/source lines.
    locations = re.findall(r'File "/submission/inference\.py", line ([0-9]{1,7}),', log)
    location = f"\n발생 위치: inference.py {locations[-1]}행" if locations else ""
    return f"원인: {cause}{location}\n해결 방법: {help_text}"
