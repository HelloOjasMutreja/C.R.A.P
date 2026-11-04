"""Paired bootstrap for the repeat-sighting comparison, then the paper's figures.

Run after run_experiments.py, from the repository root:
    python docs/paper/experiments/analyse_and_plot.py
"""

import json
import random
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_experiments import (  # noqa: E402
    CLASS_METADATA,
    FIGURES,
    RESULTS,
    engine_call,
    image_pools,
    single_image_call,
    visit_sequence,
)

BOOTSTRAPS = 300
PLANTS = 200
VISITS = 3
THRESHOLD = 0.60


def paired_rates(diseased, healthy, rng):
    """Same simulated plants judged by both methods; the first visit is the single image."""
    out = {k: 0 for k in ("s_false", "r_false", "s_true", "r_true", "s_wrong", "r_wrong")}
    healthy_keys, disease_keys = list(healthy), list(diseased)

    for _ in range(PLANTS):
        s = rng.choice(healthy_keys)
        seq = visit_sequence(healthy[s], VISITS, 0.0, rng)
        out["s_false"] += bool(single_image_call(seq[0], s, THRESHOLD))
        out["r_false"] += bool(engine_call(seq, s, THRESHOLD))

        s, condition = rng.choice(disease_keys)
        seq = visit_sequence(diseased[(s, condition)], VISITS, 0.0, rng)
        single = single_image_call(seq[0], s, THRESHOLD)
        repeat = engine_call(seq, s, THRESHOLD)
        out["s_true"] += condition in single
        out["r_true"] += condition in repeat
        out["s_wrong"] += bool(single - {condition})
        out["r_wrong"] += bool(repeat - {condition})

    return {k: v / PLANTS for k, v in out.items()}


def bootstrap(records):
    """Resample the test images themselves, so the interval reflects the small image pools."""
    rng = random.Random(2026)
    rows = []
    for b in range(BOOTSTRAPS):
        sample = [rng.choice(records) for _ in records]
        diseased, healthy = image_pools(sample)
        rows.append(paired_rates(diseased, healthy, rng))
        if b % 50 == 0:
            print("bootstrap", b, flush=True)

    def summary(key):
        values = sorted(r[key] for r in rows)
        return {
            "mean": sum(values) / len(values),
            "ci95": [values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]],
        }

    result = {k: summary(k) for k in rows[0]}
    for name, a, b in (("false", "s_false", "r_false"), ("true", "s_true", "r_true"), ("wrong", "s_wrong", "r_wrong")):
        diffs = sorted(r[b] - r[a] for r in rows)
        result[f"diff_{name}"] = {
            "mean": sum(diffs) / len(diffs),
            "ci95": [diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]],
            "share_below_zero": sum(d < 0 for d in diffs) / len(diffs),
        }
    result["settings"] = {"bootstraps": BOOTSTRAPS, "plants_per_group": PLANTS, "visits": VISITS, "threshold": THRESHOLD}
    return result


def style():
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.6,
        "lines.linewidth": 1.2,
        "lines.markersize": 3.5,
        "legend.frameon": False,
        "figure.dpi": 300,
    })


def figure_tradeoff(e3):
    fig, ax = plt.subplots(figsize=(3.3, 2.3))
    for method, label, marker, color in (
        ("single", "Single image", "s", "#b5482f"),
        ("repeat", "Repeat sighting (3 visits)", "o", "#1f6f54"),
    ):
        rows = sorted((r for r in e3["sweep"] if r["method"] == method), key=lambda r: r["threshold"])
        x = [100 * r["wrong_condition_rate"] for r in rows]
        y = [100 * r["true_detection_rate"] for r in rows]
        ax.plot(x, y, marker=marker, color=color, label=label)
    ax.set_xlabel("Wrong-condition diagnoses (% of diseased plants)")
    ax.set_ylabel("Correct diagnoses (%)")
    ax.legend(loc="lower right")
    ax.grid(alpha=0.25, linewidth=0.4)
    fig.tight_layout(pad=0.3)
    fig.savefig(FIGURES / "tradeoff.png", dpi=300)
    plt.close(fig)


def figure_correlation(e3):
    rows = e3["correlation"]
    rho = [r["rho"] for r in rows]
    fig, ax = plt.subplots(figsize=(3.3, 2.1))
    wrong = [100 * r["wrong_condition_rate"] for r in rows]
    low = [w - 100 * r["wrong_condition_ci"][0] for w, r in zip(wrong, rows)]
    high = [100 * r["wrong_condition_ci"][1] - w for w, r in zip(wrong, rows)]
    ax.errorbar(rho, wrong, yerr=[low, high], marker="o", color="#1f6f54", capsize=2, label="Repeat sighting, 3 visits")
    single = next(r for r in e3["main"] if r["method"] == "single" and r["threshold"] == 0.60)
    ax.axhline(100 * single["wrong_condition_rate"], color="#b5482f", linestyle="--", linewidth=0.9, label="Single image")
    ax.set_xlabel("Probability a visit repeats the previous view")
    ax.set_ylabel("Wrong-condition diagnoses (%)")
    ax.set_ylim(0, 30)
    ax.legend(loc="lower right")
    ax.grid(alpha=0.25, linewidth=0.4)
    fig.tight_layout(pad=0.3)
    fig.savefig(FIGURES / "correlation.png", dpi=300)
    plt.close(fig)


def figure_per_class(e1):
    rows = sorted(e1["per_class_ap50_at_800"].items(), key=lambda kv: kv[1])
    fig, ax = plt.subplots(figsize=(3.3, 3.5))
    healthy = {m["name"]: m["is_healthy"] for m in CLASS_METADATA.values()}
    names = [k.replace("Bell_pepper", "Bell pepper").replace("Soyabean", "Soybean") for k, _ in rows]
    values = [v for _, v in rows]
    colors = ["#1f6f54" if healthy[k] else "#b5482f" for k, _ in rows]
    ax.barh(names, values, color=colors, height=0.72)
    ax.set_xlim(0, 1)
    ax.set_xlabel("AP@0.5")
    ax.tick_params(axis="y", labelsize=5.8, length=0)
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    fig.tight_layout(pad=0.3)
    fig.savefig(FIGURES / "per_class.png", dpi=300)
    plt.close(fig)


def main():
    if "--plots-only" not in sys.argv:
        records = json.loads((RESULTS / "detections_640.json").read_text())
        result = bootstrap(records)
        (RESULTS / "e5_paired_bootstrap.json").write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k.startswith("diff") or k in ("s_true", "r_true")}, indent=1))

    style()
    e3 = json.loads((RESULTS / "e3_repeat_sighting.json").read_text())
    e1 = json.loads((RESULTS / "e1_accuracy.json").read_text())
    figure_tradeoff(e3)
    figure_correlation(e3)
    figure_per_class(e1)
    print("figures done", flush=True)


if __name__ == "__main__":
    main()
