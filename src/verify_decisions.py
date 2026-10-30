"""Independently enumerate exact objectives from the retained scenario inputs."""

import argparse, csv, json, sys
from collections import defaultdict
from fractions import Fraction as Q
from pathlib import Path

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)
csv.field_size_limit(16 * 1024 * 1024)
ROOT = Path(__file__).resolve().parents[1]


def read(name):
    with (ROOT / "results" / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--role", choices=["development", "held"], required=True)
    a = p.parse_args()
    role = a.role
    checks = 0

    def check(actual, expected, label):
        nonlocal checks
        checks += 1
        assert actual == str(expected), (label, actual, expected)

    def value(row, key, number):
        check(row[key + "_exact"], f"{number.numerator}/{number.denominator}", key)
        check(row[key], format(float(number), ".9f"), key + " display")

    models = {
        r["model_id"]: r for r in read("eligible_models.csv") if r["role"] == role
    }
    inputs = defaultdict(dict)
    for r in read("scenario_inputs.csv"):
        if r["role"] != role:
            continue
        pair = inputs[r["model_id"]]
        key = (int(r["action"]), r["weather"])
        assert key not in pair
        pair[key] = r
    expected = {}
    weather = ["amy2018", "amy2012"]
    rules = ["nominal", "maximin", "minimax_regret"]
    for ident, m in models.items():
        cells = inputs[ident]
        actions = sorted({k[0] for k in cells})
        scores = {}
        electric = {}
        electric_pp = {}
        for action in actions:
            scores[action] = []
            for w in weather:
                r = cells[action, w]
                baseline = Q(r["site_baseline_exact"])
                scores[action].append(
                    Q(100) * (1 - Q(r["site_action_exact"]) / baseline)
                )
                delta = Q(r["electricity_baseline_exact"]) - Q(
                    r["electricity_action_exact"]
                )
                electric[action, w] = delta
                electric_pp[action, w] = (
                    100 * delta / Q(r["electricity_baseline_exact"])
                    if Q(r["electricity_baseline_exact"])
                    else None
                )
        tops = [
            sorted(
                x for x in actions if all(scores[x][i] >= scores[y][i] for y in actions)
            )
            for i in range(2)
        ]
        maxes = [scores[tops[i][0]][i] for i in range(2)]
        objectives = {}
        chosen = {}
        ties = {}
        max_regret = {
            x: max(maxes[i] - scores[x][i] for i in range(2)) for x in actions
        }
        for rule in rules:
            objectives[rule] = {
                x: (
                    scores[x][0]
                    if rule == "nominal"
                    else min(scores[x]) if rule == "maximin" else -max_regret[x]
                )
                for x in actions
            }
            ties[rule] = sorted(
                x
                for x in actions
                if all(objectives[rule][x] >= objectives[rule][y] for y in actions)
            )
            chosen[rule] = ties[rule][0]
        assert min(scores[chosen["maximin"]]) >= min(scores[chosen["nominal"]])
        assert max_regret[chosen["minimax_regret"]] <= max_regret[chosen["nominal"]]
        checks += 2
        expected[ident] = dict(
            scores=scores,
            tops=tops,
            actions=actions,
            chosen=chosen,
            ties=ties,
            max_regret=max_regret,
            electric=electric,
            electric_pp=electric_pp,
            maxes=maxes,
        )
    action_rows = read(role + "_action_outcomes.csv")
    assert len(action_rows) == sum(len(x["actions"]) * 2 for x in expected.values())
    seen = set()
    for r in action_rows:
        ident = r["model_id"]
        x = expected[ident]
        m = models[ident]
        action = int(r["action"])
        w = r["weather"]
        wi = weather.index(w)
        key = (ident, action, w)
        assert key not in seen
        seen.add(key)
        for col in ["role", "group", "type", "weekday_band"]:
            check(r[col], m[col], col)
        check(
            r["rank"],
            1
            + len(
                [
                    b
                    for b in x["actions"]
                    if x["scores"][b][wi] > x["scores"][action][wi]
                ]
            ),
            "rank",
        )
        check(r["top"], action in x["tops"][wi], "top")
        dominated = False
        for b in x["actions"]:
            differences = [x["scores"][b][i] - x["scores"][action][i] for i in range(2)]
            if min(differences) >= 0 and max(differences) > 0:
                dominated = True
        check(r["pareto_dominated"], dominated, "dominance")
        value(r, "gain_pp", x["scores"][action][wi])
        value(r, "regret_pp", x["maxes"][wi] - x["scores"][action][wi])
        value(r, "electricity_delta_kwh", x["electric"][action, w])
        if x["electric_pp"][action, w] is None:
            check(
                r["electricity_gain_pp_exact"], "", "undefined electricity denominator"
            )
            check(r["electricity_gain_pp"], "", "undefined electricity display")
        else:
            value(r, "electricity_gain_pp", x["electric_pp"][action, w])
    expected_choices = {}
    choices = read(role + "_choices.csv")
    assert len(choices) == len(models) * 3
    for r in choices:
        ident = r["model_id"]
        rule = r["rule"]
        key = (ident, rule)
        assert key not in expected_choices
        x = expected[ident]
        action = x["chosen"][rule]
        score = x["scores"][action]
        for col in ["role", "group", "type", "weekday_band"]:
            check(r[col], models[ident][col], col)
        check(r["action"], action, "decision")
        check(
            r["objective_top_set"],
            ";".join(map(str, x["ties"][rule])),
            "objective ties",
        )
        check(
            r["different_from_nominal"],
            action != x["chosen"]["nominal"],
            "choice disagreement",
        )
        vals = dict(
            gain_2018_pp=score[0],
            gain_2012_pp=score[1],
            worst_gain_pp=min(score),
            worst_regret_pp=x["max_regret"][action],
            equal_case_gain_pp=sum(score) / 2,
        )
        for col, number in vals.items():
            value(r, col, number)
        expected_choices[key] = vals
    diagnostics = read(role + "_model_diagnostics.csv")
    assert len(diagnostics) == len(models)
    expected_diagnostics = {}
    for r in diagnostics:
        ident = r["model_id"]
        x = expected[ident]
        assert ident not in expected_diagnostics
        for col in ["role", "group", "type", "weekday_band"]:
            check(r[col], models[ident][col], col)
        strict = (
            len(x["tops"][0]) == len(x["tops"][1]) == 1 and x["tops"][0] != x["tops"][1]
        )
        change = x["tops"][0] != x["tops"][1]
        vals = dict(
            strict_unique_reversal=strict,
            top_set_changed=change,
            tie_involved_change=change and not strict,
            negative_action_case_cells=sum(
                v < 0 for action, s in x["scores"].items() if action for v in s
            ),
        )
        for col, v in vals.items():
            check(r[col], v, col)
        check(r["feasible_actions"], ";".join(map(str, x["actions"])), "actions")
        for i, y in enumerate(["2018", "2012"]):
            check(r["top_" + y], ";".join(map(str, x["tops"][i])), "top sets")
        expected_diagnostics[ident] = vals
    metrics = read(role + "_metrics.csv")
    keys = set()
    expected_rows = 3 * (
        1
        + len({m["group"] for m in models.values()})
        + len({m["type"] for m in models.values()})
        + len({m["weekday_band"] for m in models.values()})
    )
    assert len(metrics) == expected_rows
    for r in metrics:
        dimension = r["dimension"]
        stratum = r["stratum"]
        rule = r["rule"]
        key = (dimension, stratum, rule)
        assert key not in keys
        keys.add(key)
        ids = [
            ident
            for ident, m in models.items()
            if dimension == "overall" or m[dimension] == stratum
        ]
        assert ids
        check(r["role"], role, "role")
        check(r["n"], len(ids), "denominator")
        check(
            r["different_from_nominal"],
            sum(
                expected[i]["chosen"][rule] != expected[i]["chosen"]["nominal"]
                for i in ids
            ),
            "disagreements",
        )
        for col, source in [
            ("strict_unique_reversals", "strict_unique_reversal"),
            ("top_set_changes", "top_set_changed"),
            ("tie_involved_changes", "tie_involved_change"),
            ("negative_action_case_cells", "negative_action_case_cells"),
        ]:
            check(r[col], sum(expected_diagnostics[i][source] for i in ids), col)
        for col in [
            "gain_2018_pp",
            "gain_2012_pp",
            "worst_gain_pp",
            "worst_regret_pp",
            "equal_case_gain_pp",
        ]:
            value(
                r,
                "mean_" + col,
                sum((expected_choices[i, rule][col] for i in ids), Q()) / len(ids),
            )
    summary = json.loads(
        (ROOT / "results" / f"{role}_summary.json").read_text(encoding="utf-8")
    )
    assert summary == dict(
        status="EXECUTED_FIXED_RULES",
        role=role,
        models=len(models),
        scenario_action_rows=len(action_rows),
        choices=len(choices),
        metrics=len(metrics),
        rules=rules,
        learned_parameters=0,
        selected_policy=None,
        scope="Finite supplied simulation cases;no probabilities,field effects,cost or national extrapolation",
    )
    checks += len(summary)
    result = dict(
        status="PASS",
        role=role,
        checks=checks,
        models=len(models),
        scenario_action_rows=len(action_rows),
        choices=len(choices),
        metric_rows=len(metrics),
        independence="Separate exact-rational objective enumeration and field/stratum reconstruction;no analysis-helper imports",
        limits="Finite mathematical and export checks,not source-model accuracy or empirical investment validation",
    )
    (ROOT / "results" / f"independent_{role}.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
