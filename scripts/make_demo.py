"""Builds FAKE demo material so the whole flow can be rehearsed before the data team
delivers the real dataset. Nothing here is competition data.

    python scripts/make_demo.py --out var/demo

Creates:
    var/demo/code.zip               a valid submission (predicts one label for every row)
    var/demo/code_crash.zip         inference.py raises an error      -> runtime_error
    var/demo/code_bad_output.zip    writes a malformed prediction CSV  -> output_invalid
    var/demo/code_mock_timeout.zip  mock evaluator only                -> timeout
    var/demo/data/public/           metadata.json, train.csv           (DATA_HOST_DIR)
    var/demo/data/private/          labels.csv                         (worker only)
    var/demo/eval-input/            test.csv                           (EVAL_INPUT_HOST_DIR)

The inference command and input layout follow the PROVISIONAL contract in
docs/api-contract.md and will change once the data team fixes the real one.
"""
import argparse
import io
import json
import random
import zipfile
from pathlib import Path

LABELS = ["1.10", "2.60", "3.40"]

INFERENCE = '''"""Demo inference: reads /input/test.csv, writes id,label predictions."""
import argparse, csv, json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
label = json.loads(Path("model/model.json").read_text())["label"]
with open(Path(args.input) / "test.csv", newline="") as source, open(args.output, "w", newline="") as target:
    writer = csv.writer(target)
    writer.writerow(["id", "label"])
    for row in csv.DictReader(source):
        writer.writerow([row["id"], label])
'''
CRASH = 'raise RuntimeError("demo failure: the model could not be loaded")\n'
BAD_OUTPUT = '''import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input"); parser.add_argument("--output")
open(parser.parse_args().output, "w").write("identifier,prediction\\nA,B\\n")
'''


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            zipped.writestr(name, content)
    return buffer.getvalue()


def submission(inference, extra=None):
    return archive({"inference.py": inference, "train.py": "# training code; not run during scoring\n",
                    "requirements.txt": "# standard library only\n",
                    "model/model.json": json.dumps({"label": "3.40"}), **(extra or {})})


def main():
    parser = argparse.ArgumentParser(description="Create fake demo submissions and a tiny fake dataset")
    parser.add_argument("--out", default="var/demo")
    parser.add_argument("--rows", type=int, default=200)
    args = parser.parse_args()
    out = Path(args.out)
    public, private, eval_input = out / "data/public", out / "data/private", out / "eval-input"
    for directory in (public, private, eval_input):
        directory.mkdir(parents=True, exist_ok=True)

    (out / "code.zip").write_bytes(submission(INFERENCE))
    (out / "code_crash.zip").write_bytes(submission(CRASH))
    (out / "code_bad_output.zip").write_bytes(submission(BAD_OUTPUT))
    (out / "code_mock_timeout.zip").write_bytes(submission(INFERENCE, {"mock.json": json.dumps({"fail": "timeout"})}))

    rng = random.Random(42)
    amino = "ACDEFGHIKLMNPQRSTVWY"
    sequence = lambda: "".join(rng.choice(amino) for _ in range(rng.randint(40, 120)))
    train = ["id,sequence,label"] + [f"TRAIN_{i:06d},{sequence()},{rng.choice(LABELS)}" for i in range(1, args.rows + 1)]
    test = ["id,sequence"]
    labels = ["id,label,partition"]
    for i in range(1, args.rows + 1):
        test.append(f"TEST_{i:06d},{sequence()}")
        labels.append(f"TEST_{i:06d},{rng.choice(LABELS)},{'public' if i % 10 < 3 else 'private'}")
    (public / "train.csv").write_text("\n".join(train) + "\n", encoding="utf-8")
    (eval_input / "test.csv").write_text("\n".join(test) + "\n", encoding="utf-8")
    (private / "labels.csv").write_text("\n".join(labels) + "\n", encoding="utf-8")
    (public / "metadata.json").write_text(json.dumps({
        "version": "FAKE-demo-1", "labels": LABELS,
        "validation": {"passed": False, "note": "fake demo data, not validated"},
        "stats": {"total": 2 * args.rows, "classes": len(LABELS), "train": args.rows, "test": args.rows},
        "files": {"train.csv": {"rows": args.rows, "columns": ["id", "sequence", "label"],
                                "bytes": (public / "train.csv").stat().st_size}},
    }, indent=2), encoding="utf-8")
    print(f"demo files written to {out.resolve()}")


if __name__ == "__main__":
    main()
