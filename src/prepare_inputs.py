"""Keep model copies together and retain every source/applicability exclusion."""

import argparse, csv, gzip, io, json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEATHERS = ["amy2018", "amy2012"]
UPGRADES = [39, 40, 45, 48]
GROUPS = {
    **{k: "Office" for k in ["SmallOffice", "MediumOffice", "LargeOffice"]},
    **{k: "Retail" for k in ["RetailStandalone", "RetailStripmall"]},
    **{k: "Hotel" for k in ["SmallHotel", "LargeHotel"]},
    "Warehouse": "Warehouse",
}
NUMERIC = [
    "in.sqft",
    "in.weekday_operating_hours",
    "in.weekend_operating_hours",
    "out.site_energy.total.energy_consumption",
    "out.electricity.total.energy_consumption",
]


def number(row, field):
    if row[field + "__type"] == "null":
        return None
    try:
        return F(row[field])
    except (ValueError, ZeroDivisionError):
        return None


def boolean(row):
    if row["applicability__type"] != "bool":
        return None
    return (
        True
        if row["applicability"] == "true"
        else False if row["applicability"] == "false" else None
    )


def exact(x):
    return f"{x.numerator}/{x.denominator}"


def same(a, b, fields):
    for field in fields:
        if a[field + "__type"] != b[field + "__type"]:
            return False
        if field in NUMERIC:
            x, y = number(a, field), number(b, field)
            if x is not None and y is not None:
                if abs(x - y) > max(F(1, 10**9), abs(y) * F(2, 10**16)):
                    return False
            elif a[field] != b[field]:
                return False
        elif a[field] != b[field]:
            return False
    return True


def canonical(copies, fields):
    ordered = sorted(copies, key=lambda r: (r["source_file"], int(r["source_row"])))
    if not ordered or any(not same(r, ordered[0], fields) for r in ordered[1:]):
        return None
    return ordered[0]


def write_csv(path, rows):
    assert rows
    stream = io.StringIO(newline="")
    w = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    if path.suffix == ".gz":
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", mtime=0) as f:
            f.write(stream.getvalue().encode())
        path.write_bytes(buffer.getvalue())
    else:
        path.write_bytes(stream.getvalue().encode())


def qualify(rows):
    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["bldg_id"], r["weather"], int(r["upgrade"]))].append(r)
    fields = [
        k
        for k in rows[0]
        if k not in ["source_file", "source_row", "weather"]
        and not k.endswith("__type")
    ]
    originals = {k: canonical(v, fields) for k, v in grouped.items()}
    planned = sorted(
        {
            r["bldg_id"]
            for r in rows
            if r["weather"] == "amy2018" and r["upgrade"] == "0"
        },
        key=int,
    )
    audit = []
    models = []
    scenarios = []
    reason_counts = Counter()
    pop = Counter()
    counts = Counter()
    for ident in planned:
        reasons = []
        base = {}
        actions = [0]
        type_name = ""
        group = ""
        role = "unscored"
        for weather in WEATHERS:
            key = (ident, weather, 0)
            if key not in grouped:
                reasons.append(weather + "_missing_baseline")
                continue
            row = originals[key]
            if row is None:
                reasons.append(weather + "_conflicting_baseline_copies")
                continue
            base[weather] = row
            if row["completed_status"] != "Success":
                reasons.append(weather + "_baseline_not_success")
            for field in NUMERIC:
                value = number(row, field)
                if (
                    value is None
                    or value < 0
                    or (
                        field in ["in.sqft", "out.site_energy.total.energy_consumption"]
                        and value == 0
                    )
                ):
                    reasons.append(weather + "_invalid_baseline_" + field)
        if "amy2018" in base:
            type_name = base["amy2018"]["in.comstock_building_type"]
            group = GROUPS.get(type_name, "outside")
            role = (
                "development"
                if group in ["Office", "Retail"]
                else "held" if group in ["Hotel", "Warehouse"] else "unscored"
            )
            pop[group] += 1
            if group == "outside":
                reasons.append("outside_four_archetypes")
        if all(w in base for w in WEATHERS):
            if not same(
                base["amy2018"],
                base["amy2012"],
                [
                    "in.comstock_building_type",
                    "in.sqft",
                    "in.weekday_operating_hours",
                    "in.weekend_operating_hours",
                ],
            ):
                reasons.append("baseline_input_mismatch_between_cases")
        if ident in ["62841", "93569", "205619"]:
            reasons.append("precollection_documentation_example_id")
        applicability = []
        for upgrade in UPGRADES:
            pair = {}
            valid = True
            for weather in WEATHERS:
                key = (ident, weather, upgrade)
                if key not in grouped:
                    reasons.append(weather + "_missing_upgrade_" + str(upgrade))
                    valid = False
                    continue
                row = originals[key]
                if row is None:
                    reasons.append(
                        weather + "_conflicting_upgrade_copies_" + str(upgrade)
                    )
                    valid = False
                    continue
                pair[weather] = row
            if not valid:
                continue
            flags = [boolean(pair[w]) for w in WEATHERS]
            if any(f is None for f in flags):
                reasons.append("unknown_applicability_" + str(upgrade))
                continue
            if flags[0] != flags[1]:
                reasons.append("inconsistent_applicability_" + str(upgrade))
                continue
            if flags == [False, False]:
                applicability.append(str(upgrade) + ":not_applicable")
                continue
            for weather, row in pair.items():
                if row["completed_status"] != "Success":
                    reasons.append(weather + "_upgrade_not_success_" + str(upgrade))
                    valid = False
                for field in [
                    "out.site_energy.total.energy_consumption",
                    "out.electricity.total.energy_consumption",
                ]:
                    value = number(row, field)
                    if value is None or value < 0:
                        reasons.append(
                            weather + "_invalid_upgrade_energy_" + str(upgrade)
                        )
                        valid = False
            if valid:
                actions.append(upgrade)
                applicability.append(str(upgrade) + ":applicable")
        if len(actions) == 1:
            reasons.append(
                "no_applicable_retrofit"
                if len(applicability) == 4
                and all(x.endswith(":not_applicable") for x in applicability)
                else "no_complete_applicable_action_information"
            )
        reasons = sorted(set(reasons))
        good = not reasons
        reason_counts.update(reasons)
        row = dict(
            model_id=ident,
            type=type_name,
            group=group,
            role=role,
            eligible=good,
            reasons=";".join(reasons),
            feasible_actions=";".join(map(str, actions)),
            applicability=";".join(applicability),
            source_rows=sum(len(v) for k, v in grouped.items() if k[0] == ident),
        )
        audit.append(row)
        if not good:
            continue
        counts[group] += 1
        b = base["amy2018"]
        hours = number(b, "in.weekday_operating_hours")
        band = "<=8hr" if hours <= 8 else "(8,12]hr" if hours <= 12 else ">12hr"
        models.append(
            dict(
                model_id=ident,
                type=type_name,
                group=group,
                role=role,
                area_exact=exact(number(b, "in.sqft")),
                weekday_duration_exact=exact(hours),
                weekend_duration_exact=exact(number(b, "in.weekend_operating_hours")),
                weekday_band=band,
                feasible_actions=";".join(map(str, actions)),
            )
        )
        for weather in WEATHERS:
            b = base[weather]
            for action in actions:
                alternative = b if action == 0 else originals[(ident, weather, action)]
                scenarios.append(
                    dict(
                        model_id=ident,
                        role=role,
                        group=group,
                        type=type_name,
                        weather=weather,
                        action=action,
                        site_baseline_exact=exact(
                            number(b, "out.site_energy.total.energy_consumption")
                        ),
                        site_action_exact=exact(
                            number(
                                alternative, "out.site_energy.total.energy_consumption"
                            )
                        ),
                        electricity_baseline_exact=exact(
                            number(b, "out.electricity.total.energy_consumption")
                        ),
                        electricity_action_exact=exact(
                            number(
                                alternative, "out.electricity.total.energy_consumption"
                            )
                        ),
                    )
                )
    audit_by_id = {r["model_id"]: r for r in audit}
    source_audit = []
    for r in rows:
        a = audit_by_id.get(r["bldg_id"])
        key = (r["bldg_id"], r["weather"], int(r["upgrade"]))
        source_audit.append(
            dict(
                source_file=r["source_file"],
                source_row=r["source_row"],
                model_id=r["bldg_id"],
                weather=r["weather"],
                upgrade=r["upgrade"],
                copies_for_key=len(grouped[key]),
                consistent_copies=originals[key] is not None,
                used_model=bool(a and a["eligible"]),
                model_reasons=a["reasons"] if a else "outside_2018_baseline_population",
            )
        )
    gate = dict(
        status=(
            "PASS"
            if len(models) >= 20
            and all(counts[g] >= 5 for g in ["Office", "Retail", "Hotel", "Warehouse"])
            else "FAIL_MINIMUM_COHORT"
        ),
        source_rows=len(rows),
        planned_models=len(planned),
        eligible_models=len(models),
        planned_by_group=dict(pop),
        eligible_by_group=dict(counts),
        eligible_by_role=dict(Counter(r["role"] for r in models)),
        overlapping_reason_counts=dict(reason_counts),
        source_key_groups=len(grouped),
        repeated_source_rows=len(rows) - len(grouped),
        conflicting_key_groups=sum(r is None for r in originals.values()),
        scope="Unweighted unique simulation IDs in one county,two published weather cases;no field savings,national totals,controlled occupancy effect or weather-causality validation",
    )
    return audit, source_audit, models, scenarios, gate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, default=ROOT / "results")
    a = p.parse_args()
    a.output_dir.mkdir(exist_ok=True)
    with gzip.open(
        ROOT / "data/records.csv.gz", "rt", encoding="utf-8", newline=""
    ) as f:
        records = list(csv.DictReader(f))
    audit, source, models, scenarios, gate = qualify(records)
    for name, rows in [
        ("model_eligibility.csv", audit),
        ("source_row_eligibility.csv.gz", source),
        ("eligible_models.csv", models),
        ("scenario_inputs.csv", scenarios),
    ]:
        if rows:
            write_csv(a.output_dir / name, rows)
    (a.output_dir / "source_gate.json").write_bytes(
        (json.dumps(gate, indent=2) + "\n").encode()
    )
    print(json.dumps(gate))
    assert gate["status"] == "PASS", "Preserve failed cohort gate;no ranking scores"


if __name__ == "__main__":
    main()
