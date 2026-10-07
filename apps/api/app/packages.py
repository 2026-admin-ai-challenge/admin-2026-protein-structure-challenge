"""What a submission's requirements.txt may ask for.

The scoring image installs only the base packages of apps/evaluator/requirements.txt and
keeps wheels of the 89 packages the data team pinned (`PACKAGE_LOCK`). Before inference the
worker installs the packages a submission names. Every one must be in the lock, otherwise
the ZIP is refused at upload. Version specifiers are ignored: the image has one version of
each package, so what gets installed is always `name==version` from the lock, never text
from the file.
"""
import codecs
import re
from functools import lru_cache

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from .config import PACKAGE_LOCK

MAX_BYTES = 64 * 1024
# Environment markers (`; sys_platform == "win32"`) are judged for the scoring container,
# not for the machine the worker runs on. A requirement whose marker is false is skipped,
# as pip would.
TARGET = {"os_name": "posix", "sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64",
          "platform_python_implementation": "CPython", "implementation_name": "cpython", "python_version": "3.12"}
# Options that only choose where pip looks. The image installs from its own wheels, so they
# are ignored. Any other option is refused.
IGNORED_OPTIONS = {"-i", "--index-url", "--extra-index-url", "--no-index", "-f", "--find-links",
                   "--trusted-host", "--pre", "--prefer-binary", "--only-binary", "--no-binary"}
INCLUDES = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable"}
COMMENT = re.compile(r"(^|\s+)#.*$")
# pip-compile --generate-hashes writes these after a requirement.
HASH = re.compile(r"\s+--hash[=\s]\S+")
SHOWN = 10


class RequirementsRejected(ValueError):
    pass


def parse_lock(text):
    """{canonical name: (name as written, Version)} from `name==version` lines."""
    pinned = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, version = line.partition("==")
            pinned[canonicalize_name(name)] = (name.strip(), Version(version))
    return pinned


@lru_cache(maxsize=1)
def lock():
    return parse_lock(PACKAGE_LOCK.read_text(encoding="utf-8"))


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


def _listed(items):
    items = [item[:60] for item in dict.fromkeys(items)]
    more = f" 외 {len(items) - SHOWN}개" if len(items) > SHOWN else ""
    return ", ".join(items[:SHOWN]) + more


def pins(text, pinned=None):
    """The packages to install for a requirements.txt: sorted `name==version` from the lock,
    whatever version the file asks for. Raises RequirementsRejected naming every package
    that is not in the lock."""
    pinned = lock() if pinned is None else pinned
    wanted, unknown = {}, []
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
        if requirement.extras:
            raise RequirementsRejected(f"{where}: extras({requirement.name[:60]}[{','.join(sorted(requirement.extras))[:60]}])는 "
                                       "쓸 수 없습니다. 필요한 패키지를 한 줄에 하나씩 적어 주세요.")
        key = canonicalize_name(requirement.name)
        if key not in pinned:
            unknown.append(requirement.name)
            continue
        name, version = pinned[key]
        wanted[key] = f"{name}=={version}"
    if unknown:
        raise RequirementsRejected("requirements.txt에 채점 환경에서 제공하지 않는 패키지가 있습니다: " + _listed(unknown)
                                   + ". 공지된 패키지 목록에 있는 패키지만 적어 주세요.")
    return sorted(wanted.values(), key=str.lower)
