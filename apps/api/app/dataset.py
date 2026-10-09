"""Read-only access to the dataset prepared by the data team.

The API only ever reads DATA_DIR/public. Hidden answers (DATA_DIR/private) are read by
the scoring worker alone, so the web-facing process cannot leak them.
"""
import hashlib
import json

from .config import DATA_DIR

# Participant downloads. Evaluation input (test.csv, test_features.csv, test_structures.zip)
# and the old data-bearing starter kit are deliberately absent: models are scored on the
# server, so participants never receive evaluation input. The data team's analysis charts
# (class_distribution.png, sequence_length_distribution.png) are kept for the presentation
# and are not distributed either.
# The example-* files are the data team's small public example in the evaluation input
# format (test.csv, test_features.csv, test_structures.zip) plus a matching output.
PUBLIC_FILES = {
    "train": "train.csv",
    "train-features": "train_features.csv",
    "train-structures": "train_structures.zip",
    "validation-split": "validation_split.csv",
    "example-input": "example_input.csv",
    "example-features": "example_features.csv",
    "example-structures": "example_structures.zip",
    "example-output": "example_output.csv",
}
MEDIA_TYPES = {".csv": "text/csv", ".zip": "application/zip"}
# What participants see of metadata.json. An allowlist, so a key the data team adds later
# (like the seed or split settings, which could help rebuild the Public/Private split)
# stays private until it is added here on purpose.
PUBLIC_METADATA_KEYS = ("version", "labels", "stats", "files")
# Inside stats only the sizes the Data tab shows. The per-class counts cover train and test together,
# so subtracting the public train.csv would reveal the hidden evaluation set's class distribution.
PUBLIC_STATS_KEYS = ("classes", "train", "test")


def metadata():
    path = DATA_DIR / "public/metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def public_metadata():
    """Metadata for participants: only PUBLIC_METADATA_KEYS, and only entries describing
    files they can download."""
    meta = metadata()
    if not meta:
        return None
    allowed = set(PUBLIC_FILES.values())
    shown = {key: meta[key] for key in PUBLIC_METADATA_KEYS if key in meta}
    if isinstance(shown.get("stats"), dict):
        shown["stats"] = {key: value for key, value in shown["stats"].items() if key in PUBLIC_STATS_KEYS}
    return {**shown, "files": {name: info for name, info in (meta.get("files") or {}).items() if name in allowed}}


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def public_file_report(with_hashes=False):
    meta = metadata() or {}
    described = meta.get("files") or {}
    report = []
    for kind, name in PUBLIC_FILES.items():
        path = DATA_DIR / "public" / name
        entry = {"kind": kind, "name": name, "present": path.exists(), "rows": (described.get(name) or {}).get("rows")}
        if path.exists():
            entry["bytes"] = path.stat().st_size
            if with_hashes:
                entry["sha256"] = hash_file(path)
        report.append(entry)
    return report


def answers():
    """Hidden labels and the allowed class list. Worker only."""
    import pandas as pd

    path = DATA_DIR / "private/labels.csv"
    meta = metadata()
    if not path.exists() or not meta:
        raise RuntimeError("Hidden labels or dataset metadata are not available")
    frame = pd.read_csv(path, dtype=str)
    if not frame.id.is_unique or set(frame.partition) != {"public", "private"}:
        raise RuntimeError("Private dataset integrity check failed")
    if not set(frame.label) <= set(meta["labels"]):
        raise RuntimeError("Invalid private label")
    return frame, meta["labels"]
