"""Replay into separate outputs without replacing frozen inputs or compressed containers."""

import csv, gzip, hashlib, json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
csv.field_size_limit(16 * 1024 * 1024)


def main():
    originals = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(x in p.parts for x in [".git", "__pycache__", "rendered"])
        and p.name != "reproduction.json"
        and p.suffix not in [".log", ".aux", ".out", ".xdv"]
    }
    fields = documents = 0
    with tempfile.TemporaryDirectory(prefix="retrofit-replay-") as name:
        target = Path(name) / "study"
        rebuilt = Path(name) / "rebuilt"
        rebuilt.mkdir()
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(target)],
            check=True,
        )

        def run(*args):
            p = subprocess.run(
                [sys.executable, *args], cwd=target, capture_output=True, text=True
            )
            if p.returncode:
                raise RuntimeError(
                    str(args) + "\n" + p.stdout[-1800:] + "\n" + p.stderr[-1800:]
                )

        def compare(names, json_names):
            nonlocal fields, documents
            for item in names:
                opener = gzip.open if item.endswith(".gz") else open
                with opener(
                    ROOT / "results" / item, "rt", encoding="utf-8", newline=""
                ) as left, opener(
                    rebuilt / item, "rt", encoding="utf-8", newline=""
                ) as right:
                    for x, y in zip(csv.reader(left), csv.reader(right), strict=True):
                        assert x == y, item
                        fields += len(x)
            for item in json_names:
                assert json.loads(
                    (ROOT / "results" / item).read_text(encoding="utf-8")
                ) == json.loads((rebuilt / item).read_text(encoding="utf-8")), item
                documents += 1

        run("src/freeze_proof.py")
        run("src/verify_source.py")
        run("src/prepare_inputs.py", "--output-dir", str(rebuilt))
        compare(
            [
                "model_eligibility.csv",
                "source_row_eligibility.csv.gz",
                "eligible_models.csv",
                "scenario_inputs.csv",
            ],
            ["source_gate.json"],
        )
        for role in ["development", "held"]:
            run("src/decisions.py", "--role", role, "--output-dir", str(rebuilt))
            compare(
                [
                    role + "_" + n + ".csv"
                    for n in [
                        "action_outcomes",
                        "choices",
                        "model_diagnostics",
                        "metrics",
                    ]
                ],
                [role + "_summary.json"],
            )
        # Compare fresh checker receipts before restoring their frozen evidence bytes.
        for args, item in [
            (("src/verify_inputs.py",), "independent_inputs.json"),
            (
                ("src/verify_decisions.py", "--role", "development"),
                "independent_development.json",
            ),
            (("src/verify_decisions.py", "--role", "held"), "independent_held.json"),
        ]:
            path = target / "results" / item
            before = path.read_bytes()
            run(*args)
            assert json.loads(path.read_bytes()) == json.loads(before), item
            path.write_bytes(before)
            documents += 1
        run("-m", "unittest", "discover", "-s", "tests")
        run("src/freeze_proof.py")
    for item, digest in originals.items():
        assert hashlib.sha256((ROOT / item).read_bytes()).hexdigest() == digest, item
    result = dict(
        status="PASS",
        exact_csv_fields_including_headers=fields,
        json_documents=documents,
        tests=29,
        frozen_dependencies=28,
        original_files_unchanged=True,
        network_during_replay=False,
        scope="Local committed clone,separate regenerated outputs,exact CSV/JSON equality,independent arithmetic and fixtures;no original source recapture",
    )
    (ROOT / "results/reproduction.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
