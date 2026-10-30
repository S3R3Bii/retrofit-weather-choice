"""Separate SQL model-key joins and Decimal qualification;no analysis imports."""

import csv, gzip, json, sqlite3
from collections import Counter
from decimal import Decimal, InvalidOperation
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def readrows(n):
    if n.endswith(".gz"):
        with gzip.open(ROOT / n, "rt", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    with (ROOT / n).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    raw = readrows("data/records.csv.gz")
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE raw(idx INTEGER PRIMARY KEY,bid TEXT,weather TEXT,up INTEGER,signature TEXT)"
    )
    fields = [k for k in raw[0] if k not in ["source_file", "source_row", "weather"]]
    db.executemany(
        "INSERT INTO raw VALUES(?,?,?,?,?)",
        (
            (
                i,
                r["bldg_id"],
                r["weather"],
                int(r["upgrade"]),
                json.dumps([r[k] for k in fields]),
            )
            for i, r in enumerate(raw)
        ),
    )
    db.execute("CREATE INDEX identity ON raw(bid,weather,up)")
    groups = {}
    checks = 0
    for bid, weather, up, n, distinct, index in db.execute(
        "SELECT bid,weather,up,count(*),count(DISTINCT signature),min(idx) FROM raw GROUP BY bid,weather,up"
    ):
        # All current copies agree literally,which is stronger than the declared
        # representation allowance. Primary fixtures cover allowed tiny differences.
        assert distinct == 1, (
            "Current literal duplicate disagreement",
            bid,
            weather,
            up,
        )
        groups[(bid, weather, up)] = (raw[index], n)
        checks += 1
    planned = [
        x[0]
        for x in db.execute(
            "SELECT DISTINCT bid FROM raw WHERE weather='amy2018' AND up=0 ORDER BY CAST(bid AS INTEGER)"
        )
    ]
    mapping = {
        **{k: "Office" for k in ["SmallOffice", "MediumOffice", "LargeOffice"]},
        **{k: "Retail" for k in ["RetailStandalone", "RetailStripmall"]},
        **{k: "Hotel" for k in ["SmallHotel", "LargeHotel"]},
        "Warehouse": "Warehouse",
    }
    numeric = [
        "in.sqft",
        "in.weekday_operating_hours",
        "in.weekend_operating_hours",
        "out.site_energy.total.energy_consumption",
        "out.electricity.total.energy_consumption",
    ]

    def value(r, k):
        if r[k + "__type"] == "null":
            return None
        try:
            x = Decimal(r[k])
            return x if x.is_finite() else None
        except InvalidOperation:
            return None

    def ratio(x):
        x = F(x)
        return f"{x.numerator}/{x.denominator}"

    eligibility = []
    models = []
    inputs = []
    reason_counts = Counter()
    pop = Counter()
    eligible_counts = Counter()
    for bid in planned:
        reasons = []
        baselines = {}
        name = ""
        group = ""
        role = "unscored"
        actions = [0]
        states = []
        for weather in ["amy2018", "amy2012"]:
            item = groups.get((bid, weather, 0))
            if item is None:
                reasons.append(weather + "_missing_baseline")
                continue
            r = item[0]
            baselines[weather] = r
            if r["completed_status"] != "Success":
                reasons.append(weather + "_baseline_not_success")
            for k in numeric:
                x = value(r, k)
                if (
                    x is None
                    or x < 0
                    or (
                        k in ["in.sqft", "out.site_energy.total.energy_consumption"]
                        and x == 0
                    )
                ):
                    reasons.append(weather + "_invalid_baseline_" + k)
        if "amy2018" in baselines:
            name = baselines["amy2018"]["in.comstock_building_type"]
            group = mapping.get(name, "outside")
            role = (
                "development"
                if group in ["Office", "Retail"]
                else "held" if group in ["Hotel", "Warehouse"] else "unscored"
            )
            pop[group] += 1
            if group == "outside":
                reasons.append("outside_four_archetypes")
        if len(baselines) == 2:
            a, b = baselines["amy2018"], baselines["amy2012"]
            same = a["in.comstock_building_type"] == b["in.comstock_building_type"]
            for k in numeric[:3]:
                x, y = value(a, k), value(b, k)
                same &= a[k + "__type"] == b[k + "__type"] and (
                    (abs(x - y) <= max(Decimal("1e-9"), abs(y) * Decimal("2e-16")))
                    if x is not None and y is not None
                    else a[k] == b[k]
                )
            if not same:
                reasons.append("baseline_input_mismatch_between_cases")
        if bid in ["62841", "93569", "205619"]:
            reasons.append("precollection_documentation_example_id")
        for up in [39, 40, 45, 48]:
            a, b = groups.get((bid, "amy2018", up)), groups.get((bid, "amy2012", up))
            for weather, item in [("amy2018", a), ("amy2012", b)]:
                if item is None:
                    reasons.append(weather + "_missing_upgrade_" + str(up))
            if a is None or b is None:
                continue
            pair = [a[0], b[0]]
            flags = [
                r["applicability"] if r["applicability__type"] == "bool" else "?"
                for r in pair
            ]
            if any(x not in ["true", "false"] for x in flags):
                reasons.append("unknown_applicability_" + str(up))
                continue
            if flags[0] != flags[1]:
                reasons.append("inconsistent_applicability_" + str(up))
                continue
            if flags[0] == "false":
                states.append(str(up) + ":not_applicable")
                continue
            valid = True
            for weather, r in zip(["amy2018", "amy2012"], pair):
                if r["completed_status"] != "Success":
                    reasons.append(weather + "_upgrade_not_success_" + str(up))
                    valid = False
                for k in numeric[-2:]:
                    x = value(r, k)
                    if x is None or x < 0:
                        reasons.append(weather + "_invalid_upgrade_energy_" + str(up))
                        valid = False
            if valid:
                actions.append(up)
                states.append(str(up) + ":applicable")
        if len(actions) == 1:
            reasons.append(
                "no_applicable_retrofit"
                if len(states) == 4
                and all(x.endswith(":not_applicable") for x in states)
                else "no_complete_applicable_action_information"
            )
        reasons = sorted(set(reasons))
        good = not reasons
        reason_counts.update(reasons)
        copies = db.execute("SELECT count(*) FROM raw WHERE bid=?", (bid,)).fetchone()[
            0
        ]
        eligibility.append(
            dict(
                model_id=bid,
                type=name,
                group=group,
                role=role,
                eligible=str(good),
                reasons=";".join(reasons),
                feasible_actions=";".join(map(str, actions)),
                applicability=";".join(states),
                source_rows=str(copies),
            )
        )
        if not good:
            continue
        eligible_counts[group] += 1
        r = baselines["amy2018"]
        duration = value(r, "in.weekday_operating_hours")
        band = "<=8hr" if duration <= 8 else "(8,12]hr" if duration <= 12 else ">12hr"
        models.append(
            dict(
                model_id=bid,
                type=name,
                group=group,
                role=role,
                area_exact=ratio(value(r, "in.sqft")),
                weekday_duration_exact=ratio(duration),
                weekend_duration_exact=ratio(value(r, "in.weekend_operating_hours")),
                weekday_band=band,
                feasible_actions=";".join(map(str, actions)),
            )
        )
        for weather in ["amy2018", "amy2012"]:
            baseline = baselines[weather]
            for up in actions:
                scenario = baseline if up == 0 else groups[(bid, weather, up)][0]
                inputs.append(
                    dict(
                        model_id=bid,
                        role=role,
                        group=group,
                        type=name,
                        weather=weather,
                        action=str(up),
                        site_baseline_exact=ratio(value(baseline, numeric[-2])),
                        site_action_exact=ratio(value(scenario, numeric[-2])),
                        electricity_baseline_exact=ratio(value(baseline, numeric[-1])),
                        electricity_action_exact=ratio(value(scenario, numeric[-1])),
                    )
                )
    for name, expected in [
        ("model_eligibility.csv", eligibility),
        ("eligible_models.csv", models),
        ("scenario_inputs.csv", inputs),
    ]:
        assert readrows("results/" + name) == expected, name
        checks += sum(len(r) for r in expected)
    byid = {r["model_id"]: r for r in eligibility}
    source = []
    for r in raw:
        a = byid.get(r["bldg_id"])
        source.append(
            dict(
                source_file=r["source_file"],
                source_row=r["source_row"],
                model_id=r["bldg_id"],
                weather=r["weather"],
                upgrade=r["upgrade"],
                copies_for_key=str(
                    groups[(r["bldg_id"], r["weather"], int(r["upgrade"]))][1]
                ),
                consistent_copies="True",
                used_model=str(bool(a and a["eligible"] == "True")),
                model_reasons=a["reasons"] if a else "outside_2018_baseline_population",
            )
        )
    assert readrows("results/source_row_eligibility.csv.gz") == source
    checks += len(source) * 9
    gate = json.loads((ROOT / "results/source_gate.json").read_text(encoding="utf-8"))
    expected = dict(
        status=(
            "PASS"
            if len(models) >= 20
            and all(
                eligible_counts[g] >= 5
                for g in ["Office", "Retail", "Hotel", "Warehouse"]
            )
            else "FAIL_MINIMUM_COHORT"
        ),
        source_rows=len(raw),
        planned_models=len(planned),
        eligible_models=len(models),
        planned_by_group=dict(pop),
        eligible_by_group=dict(eligible_counts),
        eligible_by_role=dict(Counter(r["role"] for r in models)),
        overlapping_reason_counts=dict(reason_counts),
        source_key_groups=len(groups),
        repeated_source_rows=len(raw) - len(groups),
        conflicting_key_groups=0,
        scope="Unweighted unique simulation IDs in one county,two published weather cases;no field savings,national totals,controlled occupancy effect or weather-causality validation",
    )
    assert gate == expected
    checks += len(gate)
    result = dict(
        status="PASS",
        checks=checks,
        source_rows=len(raw),
        planned_models=len(planned),
        eligible_models=len(models),
        scenario_rows=len(inputs),
        independence="Separate SQL key/role joins,literal-copy proof and Decimal numeric qualification;no analysis helper imports",
        limits="Current finite projection and cohort;no physical-model,occupancy-causality or field-savings validation",
    )
    (ROOT / "results/independent_inputs.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
