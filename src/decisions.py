"""Compare separate retrofit alternatives within two supplied simulation cases."""

import argparse, csv, json, sys
from collections import defaultdict
from fractions import Fraction as F
from pathlib import Path

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)
csv.field_size_limit(16 * 1024 * 1024)
ROOT = Path(__file__).resolve().parents[1]
WEATHERS = ["amy2018", "amy2012"]
RULES = ["nominal", "maximin", "minimax_regret"]


def exact(x):
    return f"{x.numerator}/{x.denominator}"


def display(x):
    return f"{float(x):.9f}"


def pack(row, key, value):
    row[key + "_exact"] = exact(value)
    row[key] = display(value)


def choose(gains):
    actions = sorted(gains)
    best = [max(gains[a][w] for a in actions) for w in range(2)]
    tops = [[a for a in actions if gains[a][w] == best[w]] for w in range(2)]
    worst = {a: min(gains[a]) for a in actions}
    regret = {a: max(best[w] - gains[a][w] for w in range(2)) for a in actions}
    objectives = {
        "nominal": {a: gains[a][0] for a in actions},
        "maximin": worst,
        "minimax_regret": {a: -regret[a] for a in actions},
    }
    selected = {
        r: min(a for a in actions if objectives[r][a] == max(objectives[r].values()))
        for r in RULES
    }
    ties = {
        r: [a for a in actions if objectives[r][a] == max(objectives[r].values())]
        for r in RULES
    }
    return best, tops, worst, regret, selected, ties


def write(path, rows):
    assert rows
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(role, output):
    with (ROOT / "results/scenario_inputs.csv").open(encoding="utf-8", newline="") as f:
        source = [r for r in csv.DictReader(f) if r["role"] == role]
    with (ROOT / "results/eligible_models.csv").open(encoding="utf-8", newline="") as f:
        models = {r["model_id"]: r for r in csv.DictReader(f) if r["role"] == role}
    by_model = defaultdict(dict)
    for r in source:
        by_model[r["model_id"]][(int(r["action"]), r["weather"])] = r
    action_rows = []
    choice_rows = []
    diagnostics = []
    for ident in sorted(models, key=int):
        m = models[ident]
        records = by_model[ident]
        actions = sorted({a for a, w in records})
        gains = {
            a: [
                100
                * (
                    F(records[a, w]["site_baseline_exact"])
                    - F(records[a, w]["site_action_exact"])
                )
                / F(records[a, w]["site_baseline_exact"])
                for w in WEATHERS
            ]
            for a in actions
        }
        best, tops, worst, regret, selected, ties = choose(gains)
        strict = len(tops[0]) == len(tops[1]) == 1 and tops[0] != tops[1]
        changed = tops[0] != tops[1]
        diagnostics.append(
            dict(
                model_id=ident,
                role=role,
                group=m["group"],
                type=m["type"],
                weekday_band=m["weekday_band"],
                feasible_actions=";".join(map(str, actions)),
                top_2018=";".join(map(str, tops[0])),
                top_2012=";".join(map(str, tops[1])),
                strict_unique_reversal=strict,
                top_set_changed=changed,
                tie_involved_change=changed and not strict,
                negative_action_case_cells=sum(
                    v < 0 for a in actions if a for v in gains[a]
                ),
            )
        )
        for a in actions:
            dominated = any(
                all(gains[b][w] >= gains[a][w] for w in range(2))
                and any(gains[b][w] > gains[a][w] for w in range(2))
                for b in actions
                if b != a
            )
            for wi, w in enumerate(WEATHERS):
                r = records[a, w]
                row = dict(
                    model_id=ident,
                    role=role,
                    group=m["group"],
                    type=m["type"],
                    weekday_band=m["weekday_band"],
                    action=a,
                    weather=w,
                    rank=1 + sum(gains[b][wi] > gains[a][wi] for b in actions),
                    top=a in tops[wi],
                    pareto_dominated=dominated,
                )
                pack(row, "gain_pp", gains[a][wi])
                pack(row, "regret_pp", best[wi] - gains[a][wi])
                delta = F(r["electricity_baseline_exact"]) - F(
                    r["electricity_action_exact"]
                )
                pack(row, "electricity_delta_kwh", delta)
                baseline = F(r["electricity_baseline_exact"])
                row["electricity_gain_pp_exact"] = (
                    exact(100 * delta / baseline) if baseline else ""
                )
                row["electricity_gain_pp"] = (
                    display(100 * delta / baseline) if baseline else ""
                )
                action_rows.append(row)
        for rule in RULES:
            a = selected[rule]
            row = dict(
                model_id=ident,
                role=role,
                group=m["group"],
                type=m["type"],
                weekday_band=m["weekday_band"],
                rule=rule,
                action=a,
                objective_top_set=";".join(map(str, ties[rule])),
                different_from_nominal=a != selected["nominal"],
            )
            for key, value in [
                ("gain_2018_pp", gains[a][0]),
                ("gain_2012_pp", gains[a][1]),
                ("worst_gain_pp", worst[a]),
                ("worst_regret_pp", regret[a]),
                ("equal_case_gain_pp", sum(gains[a]) / 2),
            ]:
                pack(row, key, value)
            choice_rows.append(row)
    metrics = []
    for dimension in ["overall", "group", "type", "weekday_band"]:
        values = (
            ["all"]
            if dimension == "overall"
            else sorted({m[dimension] for m in models.values()})
        )
        for value in values:
            subset = {
                ident
                for ident, m in models.items()
                if dimension == "overall" or m[dimension] == value
            }
            d = [r for r in diagnostics if r["model_id"] in subset]
            for rule in RULES:
                rows = [
                    r
                    for r in choice_rows
                    if r["model_id"] in subset and r["rule"] == rule
                ]
                metric = dict(
                    role=role,
                    dimension=dimension,
                    stratum=value,
                    rule=rule,
                    n=len(rows),
                    different_from_nominal=sum(
                        r["different_from_nominal"] for r in rows
                    ),
                    strict_unique_reversals=sum(r["strict_unique_reversal"] for r in d),
                    top_set_changes=sum(r["top_set_changed"] for r in d),
                    tie_involved_changes=sum(r["tie_involved_change"] for r in d),
                    negative_action_case_cells=sum(
                        r["negative_action_case_cells"] for r in d
                    ),
                )
                for key in [
                    "gain_2018_pp",
                    "gain_2012_pp",
                    "worst_gain_pp",
                    "worst_regret_pp",
                    "equal_case_gain_pp",
                ]:
                    pack(
                        metric,
                        "mean_" + key,
                        sum((F(r[key + "_exact"]) for r in rows), F()) / len(rows),
                    )
                metrics.append(metric)
    output.mkdir(exist_ok=True)
    for name, rows in [
        ("action_outcomes", action_rows),
        ("choices", choice_rows),
        ("model_diagnostics", diagnostics),
        ("metrics", metrics),
    ]:
        write(output / f"{role}_{name}.csv", rows)
    summary = dict(
        status="EXECUTED_FIXED_RULES",
        role=role,
        models=len(models),
        scenario_action_rows=len(action_rows),
        choices=len(choice_rows),
        metrics=len(metrics),
        rules=RULES,
        learned_parameters=0,
        selected_policy=None,
        scope="Finite supplied simulation cases;no probabilities,field effects,cost or national extrapolation",
    )
    (output / f"{role}_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--role", choices=["development", "held"], required=True)
    p.add_argument("--output-dir", type=Path, default=ROOT / "results")
    a = p.parse_args()
    run(a.role, a.output_dir)


if __name__ == "__main__":
    main()
