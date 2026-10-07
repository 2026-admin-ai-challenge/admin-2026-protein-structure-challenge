"""Submission ZIP checks. `inspect` reads the directory listing and the root
requirements.txt, and is used when a ZIP is received. `safe_extract` is used by the worker
and enforces real sizes while unpacking, because the sizes written in a ZIP header can lie."""
import os
import re
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from . import packages
from .config import MAX_UNZIPPED_BYTES, MAX_ZIP_ENTRIES, ZIP_REQUIRED

DRIVE = re.compile(r"^[A-Za-z]:")
CHUNK = 1024 * 1024
REQUIREMENTS = "requirements.txt"


class ZipRejected(ValueError):
    pass


def _normalize(info):
    name = info.filename.replace("\\", "/")
    if not name or "\x00" in name or name.startswith("/") or DRIVE.match(name):
        raise ZipRejected(f"허용되지 않는 경로입니다: {info.filename[:80]!r}")
    parts = [part for part in name.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ZipRejected(f"상위 경로를 가리키는 항목이 있습니다: {info.filename[:80]!r}")
    return "/".join(parts)


def _is_directory(info):
    return info.filename.replace("\\", "/").endswith("/")


def _packages(path):
    """The pins for the root requirements.txt (see app.packages). `inspect` has already
    refused duplicate and unsafe names, so the normalized name finds one entry."""
    try:
        with zipfile.ZipFile(path) as archive:
            info = next(info for info in archive.infolist() if not _is_directory(info) and _normalize(info) == REQUIREMENTS)
            with archive.open(info) as source:
                data = source.read(packages.MAX_BYTES + 1)
    except (zipfile.BadZipFile, NotImplementedError, EOFError, OSError, RuntimeError, zlib.error):
        raise ZipRejected("requirements.txt의 압축을 풀 수 없습니다. ZIP을 다시 만들어 주세요.")
    try:
        return packages.pins(packages.decode(data))
    except packages.RequirementsRejected as error:
        raise ZipRejected(str(error))


def inspect(path, required=ZIP_REQUIRED, max_entries=MAX_ZIP_ENTRIES, max_total=MAX_UNZIPPED_BYTES):
    """Returns {"entries": n, "unpacked_bytes": total, "packages": [name==version, ...]} or
    raises ZipRejected. `packages` is what the root requirements.txt asks to install."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError):
        raise ZipRejected("ZIP 파일을 열 수 없습니다. 손상되었거나 ZIP 형식이 아닙니다.")
    if not infos:
        raise ZipRejected("빈 ZIP입니다.")
    if len(infos) > max_entries:
        raise ZipRejected(f"ZIP 항목이 너무 많습니다: {len(infos)}개 (최대 {max_entries}개)")
    files, directories, total = set(), set(), 0
    for info in infos:
        name = _normalize(info)
        if info.flag_bits & 0x1:
            raise ZipRejected("암호가 걸린 ZIP은 제출할 수 없습니다.")
        mode = info.external_attr >> 16
        if mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ZipRejected(f"심볼릭 링크나 특수 파일은 제출할 수 없습니다: {name[:80]}")
        if _is_directory(info):
            directories.add(name)
            continue
        if name in files:
            raise ZipRejected(f"같은 경로가 두 번 들어 있습니다: {name[:80]}")
        files.add(name)
        total += info.file_size
        if total > max_total:
            raise ZipRejected("압축을 풀었을 때 전체 크기가 허용 한도를 넘습니다.")
    for name in files:
        parents = PurePosixPath(name).parents
        directories.update(str(parent) for parent in parents if str(parent) != ".")
    if files & directories:
        raise ZipRejected("같은 이름의 파일과 폴더가 함께 들어 있습니다.")
    missing = []
    for item in required:
        present = item.rstrip("/") in directories if item.endswith("/") else item in files
        if not present:
            missing.append(item)
    if missing:
        raise ZipRejected(
            "ZIP 최상위에 필수 항목이 없습니다: " + ", ".join(missing)
            + ". 폴더째 압축하지 말고 파일과 model 폴더를 직접 선택해 압축하세요."
        )
    pins = _packages(path) if REQUIREMENTS in files else []
    return {"entries": len(infos), "unpacked_bytes": total, "packages": pins}


def safe_extract(path, destination, max_total=MAX_UNZIPPED_BYTES):
    """Unpacks into `destination` with fixed permissions. Call `inspect` first."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    os.chmod(destination, 0o755)
    written = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            target = destination.joinpath(*_normalize(info).split("/"))
            if _is_directory(info):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as output:
                while chunk := source.read(CHUNK):
                    written += len(chunk)
                    if written > max_total:
                        raise ZipRejected("압축을 풀었을 때 전체 크기가 허용 한도를 넘습니다.")
                    output.write(chunk)
            os.chmod(target, 0o644)
    for directory in [p for p in destination.rglob("*") if p.is_dir()]:
        os.chmod(directory, 0o755)
    return written
