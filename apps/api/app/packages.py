"""What a submission's requirements.txt may ask for.

The scoring image holds only the base packages of apps/evaluator/requirements.txt. Before
inference the worker downloads what a submission's requirements.txt lists from PyPI, as
wheels, into an environment of its own. The file is checked when the ZIP is received:
lines that would make pip fetch something other than an index package (other files,
paths, URLs, editable installs) are refused. What reaches pip is each requirement as
`packaging` re-writes it, never raw text from the file.
"""
import codecs
import re

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

MAX_BYTES = 64 * 1024
# The requirements travel as command-line arguments of the install container.
MAX_REQUIREMENTS = 300
# Environment markers (`; sys_platform == "win32"`) are judged for the scoring container,
# not for the machine the worker runs on. A requirement whose marker is false is skipped,
# as pip would.
TARGET = {"os_name": "posix", "sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64",
          "platform_python_implementation": "CPython", "implementation_name": "cpython", "python_version": "3.12"}
# Options that only choose where pip looks. The install container uses PyPI and the
# PyTorch CPU index, so they are ignored. Any other option is refused.
IGNORED_OPTIONS = {"-i", "--index-url", "--extra-index-url", "--no-index", "-f", "--find-links",
                   "--trusted-host", "--pre", "--prefer-binary", "--only-binary", "--no-binary"}
INCLUDES = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable"}
COMMENT = re.compile(r"(^|\s+)#.*$")
# pip-compile --generate-hashes writes these after a requirement.
HASH = re.compile(r"\s+--hash[=\s]\S+")


class RequirementsRejected(ValueError):
    pass


def decode(data):
    """requirements.txt as text. PowerShell 5.1 writes `pip freeze > requirements.txt` as UTF-16."""
    if len(data) > MAX_BYTES:
        raise RequirementsRejected(f"requirements.txt가 너무 큽니다. 최대 {MAX_BYTES // 1024} KB입니다.")
    try:
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RequirementsRejected("requirements.txt를 읽을 수 없습니다. UTF-8 텍스트로 저장해 주세요.")


def _lines(text):
    """(number of the first line, text) as pip reads a requirements file: lines ending in a
    backslash are joined, then comments are removed."""
    parts, first = [], None
    for number, line in enumerate(text.splitlines(), 1):
        if line.endswith("\\") and not COMMENT.match(line):
            first = first or number
            parts.append(line[:-1])
            continue
        if parts:
            parts.append(" " + line if COMMENT.match(line) else line)
            number, line, parts, first = first, "".join(parts), [], None
        line = COMMENT.sub("", line).strip()
        if line:
            yield number, line
    if parts and (line := COMMENT.sub("", "".join(parts)).strip()):
        yield first, line


def _without_local(specifier):
    """`torch==2.14.1+cu128` from a GPU machine's freeze names a CUDA build the scoring
    container cannot use; the same release's CPU build is installed instead."""
    return SpecifierSet(",".join(f"{item.operator}{item.version.split('+')[0]}" for item in specifier))


def requirements(text):
    """The requirements to install, as sorted pip arguments like `numpy<3,>=2` or
    `transformers[torch]==5.18.0`. Lines naming the same package are merged. Raises
    RequirementsRejected for a line pip would fetch from somewhere other than an index."""
    merged = {}
    for number, line in _lines(text):
        where = f"requirements.txt {number}번째 줄"
        if line.startswith("-"):
            option = re.split(r"[\s=]", line, maxsplit=1)[0]
            if option in IGNORED_OPTIONS:
                continue
            if option in INCLUDES:
                raise RequirementsRejected(f"{where}: 다른 파일이나 경로를 불러오는 {option} 옵션은 쓸 수 없습니다. "
                                           "패키지 이름과 버전만 적어 주세요.")
            raise RequirementsRejected(f"{where}: 지원하지 않는 옵션입니다: {option[:40]}")
        try:
            requirement = Requirement(HASH.sub("", line))
        except InvalidRequirement:
            raise RequirementsRejected(f"{where}을 해석할 수 없습니다: {line[:80]!r}. "
                                       "numpy==2.5.3처럼 패키지 이름과 버전만 적어 주세요.")
        if requirement.marker and not requirement.marker.evaluate(TARGET):
            continue
        if requirement.url:
            raise RequirementsRejected(f"{where}: 파일 경로나 URL로 지정한 패키지는 설치할 수 없습니다 ({requirement.name[:60]}). "
                                       "conda 환경이라면 pip list --format=freeze로 다시 만들어 주세요.")
        key = canonicalize_name(requirement.name)
        name, extras, specifier = merged.get(key, (requirement.name, set(), SpecifierSet()))
        merged[key] = (name, extras | requirement.extras, specifier & _without_local(requirement.specifier))
    if len(merged) > MAX_REQUIREMENTS:
        raise RequirementsRejected(f"requirements.txt의 패키지가 너무 많습니다: {len(merged)}개 (최대 {MAX_REQUIREMENTS}개)")
    return [name + (f"[{','.join(sorted(extras))}]" if extras else "") + str(specifier)
            for name, extras, specifier in sorted(merged.values(), key=lambda item: item[0].lower())]
