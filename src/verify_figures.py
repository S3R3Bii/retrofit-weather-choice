"""Recompute chart values from individual ledgers and inspect actual SVG paths."""

import csv, hashlib, json, re, sys, xml.etree.ElementTree as ET
from fractions import Fraction as Q
from pathlib import Path

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)
ROOT = Path(__file__).resolve().parents[1]


def read(n):
    with (ROOT / "results" / n).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    expected = {}
    groups = ["Office", "Retail", "Hotel", "Warehouse"]
    models = read("model_eligibility.csv")
    choices = read("development_choices.csv") + read("held_choices.csv")
    diags = read("development_model_diagnostics.csv") + read(
        "held_model_diagnostics.csv"
    )
    for i, g in enumerate(groups):
        expected[f"cohort-0-{i}"] = sum(r["group"] == g for r in models)
        expected[f"cohort-1-{i}"] = sum(
            r["group"] == g and r["eligible"] == "True" for r in models
        )
        n = expected[f"cohort-1-{i}"]
        expected[f"change-0-{i}"] = (
            100
            * sum(
                r["group"] == g and r["strict_unique_reversal"] == "True" for r in diags
            )
            / n
        )
        for j, rule in enumerate(["maximin", "minimax_regret"], 1):
            expected[f"change-{j}-{i}"] = (
                100
                * sum(
                    r["group"] == g
                    and r["rule"] == rule
                    and r["different_from_nominal"] == "True"
                    for r in choices
                )
                / n
            )
    for panel, field in enumerate(["worst_gain_pp_exact", "worst_regret_pp_exact"]):
        for j, rule in enumerate(["nominal", "maximin", "minimax_regret"]):
            for i, role in enumerate(["development", "held"]):
                rows = [r for r in choices if r["role"] == role and r["rule"] == rule]
                expected[f"tradeoff-{panel}-{j}-{i}"] = float(
                    sum((Q(r[field]) for r in rows), Q()) / len(rows)
                )
    read_json = lambda n: json.loads((ROOT / n).read_text(encoding="utf-8"))
    records = read_json("figures/artist_geometry.json")
    assert len(records) == len(expected) == 32
    checks = 0
    trees = {}
    for r in records:
        assert r["value"] == expected[r["gid"]]
        checks += 1
        name = r["figure"]
        if name not in trees:
            trees[name] = ET.parse(ROOT / "figures" / (name + ".svg"))
        group = trees[name].find('.//*[@id="' + r["gid"] + '"]')
        assert group is not None
        path = group.find("{http://www.w3.org/2000/svg}path")
        values = [
            float(v)
            for v in re.findall(
                r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", path.attrib["d"]
            )
        ]
        assert len(values) >= 8
        for a, b in zip(values[:8], [v for point in r["points"] for v in point]):
            assert abs(a - b) < 1e-5
            checks += 1
    for name, digest in read_json("figures/manifest.json").items():
        assert (
            hashlib.sha256((ROOT / "figures" / name).read_bytes()).hexdigest() == digest
        )
        checks += 1
    result = dict(
        status="PASS",
        checks=checks,
        source_values=32,
        svg_coordinates=256,
        hashes=9,
        scope="Individual-ledger arithmetic,actual SVG rectangle coordinates and artifact hashes;not field savings",
    )
    (ROOT / "results/figure_verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
