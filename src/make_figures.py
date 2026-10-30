"""Original cohort,choice-change and finite-scenario tradeoff figures."""

import csv, hashlib, json, sys
from fractions import Fraction as Q
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)
ROOT = Path(__file__).resolve().parents[1]
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "svg.fonttype": "none",
        "svg.hashsalt": "retrofit27-v1",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def read(n):
    with (ROOT / "results" / n).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    geometry = []
    hashes = {}
    groups = ["Office", "Retail", "Hotel", "Warehouse"]
    roles = ["development", "held"]
    rules = ["nominal", "maximin", "minimax_regret"]
    colors = ["#296f88", "#cb822b", "#666366"]
    gate = json.loads((ROOT / "results/source_gate.json").read_text(encoding="utf-8"))
    metrics = read("development_metrics.csv") + read("held_metrics.csv")

    def save(fig, name, artists):
        fig.canvas.draw()
        height = fig.get_figheight() * fig.dpi
        for gid, value, patch in artists:
            points = patch.get_transform().transform(patch.get_path().vertices[:4])
            geometry.append(
                dict(
                    figure=name,
                    gid=gid,
                    value=float(value),
                    points=[
                        [float(x * 72 / fig.dpi), float((height - y) * 72 / fig.dpi)]
                        for x, y in points
                    ],
                )
            )
        for ext in ["pdf", "svg", "png"]:
            p = ROOT / "figures" / (name + "." + ext)
            fig.savefig(
                p,
                dpi=160,
                metadata=(
                    {"Creator": "Retrofit weather choice,Study27"}
                    if ext == "pdf"
                    else None
                ),
            )
            if ext == "svg":
                p.write_bytes(
                    (
                        "\n".join(
                            line.rstrip()
                            for line in p.read_text(encoding="utf-8").splitlines()
                        )
                        + "\n"
                    ).encode()
                )
            hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    fig.subplots_adjust(left=0.1, right=0.98, top=0.78, bottom=0.25)
    artists = []
    for j, field in enumerate(["planned_by_group", "eligible_by_group"]):
        values = [gate[field][g] for g in groups]
        bars = ax.bar(
            [i + (j - 0.5) * 0.34 for i in range(4)],
            values,
            width=0.32,
            color=["#b3bec2", colors[0]][j],
            label=["2018 reference IDs", "Eligible paired cases"][j],
        )
        ax.bar_label(bars, padding=3, fontsize=8)
        for i, (v, p) in enumerate(zip(values, bars)):
            gid = f"cohort-{j}-{i}"
            p.set_gid(gid)
            artists.append((gid, v, p))
    ax.set_xticks(range(4), groups)
    ax.set_ylim(0, 360)
    ax.set_ylabel("Unique model IDs (unweighted)")
    ax.set_title(
        "Paired-case eligibility narrows the comparison",
        loc="left",
        pad=18,
        fontsize=12,
    )
    fig.legend(
        *ax.get_legend_handles_labels(),
        loc="lower center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 0.01),
    )
    save(fig, "cohort_coverage", artists)
    fig, ax = plt.subplots(figsize=(7.4, 3.8))
    fig.subplots_adjust(left=0.1, right=0.98, top=0.76, bottom=0.29)
    artists = []
    for j, field in enumerate(["strict_unique_reversals", "maximin", "minimax_regret"]):
        values = []
        labels = []
        for g in groups:
            row = next(
                r
                for r in metrics
                if r["dimension"] == "group"
                and r["stratum"] == g
                and r["rule"] == ("nominal" if j == 0 else field)
            )
            count = int(
                row["strict_unique_reversals"]
                if j == 0
                else row["different_from_nominal"]
            )
            n = int(row["n"])
            values.append(100 * count / n)
            labels.append(f"{count}/{n}")
        bars = ax.bar(
            [i + (j - 1) * 0.24 for i in range(4)],
            values,
            width=0.23,
            color=colors[j],
            label=[
                "Unique top reversal",
                "Maximin vs nominal",
                "Minimax regret vs nominal",
            ][j],
        )
        ax.bar_label(bars, labels, padding=3, fontsize=7, rotation=90)
        for i, (v, p) in enumerate(zip(values, bars)):
            gid = f"change-{j}-{i}"
            p.set_gid(gid)
            artists.append((gid, v, p))
    ax.set_xticks(range(4), groups)
    ax.set_ylim(0, 32)
    ax.set_ylabel("Eligible models (%)")
    ax.set_title(
        "Most choices persist;some warrant a closer review",
        loc="left",
        pad=20,
        fontsize=12,
    )
    fig.legend(
        *ax.get_legend_handles_labels(),
        loc="lower center",
        ncol=1,
        frameon=False,
        fontsize=8,
        bbox_to_anchor=(0.5, -0.01),
    )
    save(fig, "choice_changes", artists)
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 3.8))
    fig.subplots_adjust(left=0.1, right=0.98, top=0.77, bottom=0.27, wspace=0.38)
    artists = []
    for panel, field in enumerate(["mean_worst_gain_pp", "mean_worst_regret_pp"]):
        ax = axes[panel]
        for j, rule in enumerate(rules):
            values = [
                float(
                    Q(
                        next(
                            r
                            for r in metrics
                            if r["role"] == role
                            and r["dimension"] == "overall"
                            and r["rule"] == rule
                        )[field + "_exact"]
                    )
                )
                for role in roles
            ]
            bars = ax.bar(
                [i + (j - 1) * 0.24 for i in range(2)],
                values,
                width=0.23,
                color=colors[j],
                label=["Nominal", "Maximin", "Minimax regret"][j],
            )
            ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=7, rotation=90)
            for i, (v, p) in enumerate(zip(values, bars)):
                gid = f"tradeoff-{panel}-{j}-{i}"
                p.set_gid(gid)
                artists.append((gid, v, p))
        ax.set_xticks(
            range(2), ["Office/Retail\n423 cases", "Hotel/Warehouse\n112 cases"]
        )
        ax.set_ylim(0, 7.6 if panel == 0 else 0.16)
        ax.set_ylabel("Mean percentage points of case baseline")
        ax.set_title(
            ["Worst-case gain (higher)", "Worst-case regret (lower)"][panel],
            loc="left",
            fontsize=10,
        )
    fig.suptitle(
        "Finite-scenario objectives produce small tradeoffs",
        x=0.1,
        ha="left",
        fontsize=12,
    )
    fig.legend(
        *axes[0].get_legend_handles_labels(),
        loc="lower center",
        ncol=3,
        frameon=False,
        fontsize=8,
        bbox_to_anchor=(0.5, 0.01),
    )
    save(fig, "scenario_tradeoffs", artists)
    (ROOT / "figures/artist_geometry.json").write_bytes(
        (json.dumps(geometry, indent=2) + "\n").encode()
    )
    (ROOT / "figures/manifest.json").write_bytes(
        (json.dumps(hashes, indent=2, sort_keys=True) + "\n").encode()
    )
    print("FIGURES_CREATED", len(geometry), "SOURCE_VALUES")


if __name__ == "__main__":
    main()
