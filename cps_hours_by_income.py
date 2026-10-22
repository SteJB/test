"""Average hours worked by income level, from the CPS ASEC public-use file.

Produces two charts:
  1. Households: total usual weekly hours worked by all household members,
     by total household income (households with at least one worker).
  2. Individuals: usual weekly hours worked, by total personal income
     (people who worked at some point last year).

Hours and income both refer to the previous calendar year, so the ASEC
released in year Y describes work and income in Y-1.

Usage:
    python cps_hours_by_income.py                  # downloads ASEC 2025
    python cps_hours_by_income.py --year 2024
    python cps_hours_by_income.py --zip path/to/asecpub25csv.zip
"""

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.ticker import MaxNLocator

URL = "https://www2.census.gov/programs-surveys/cps/datasets/{year}/march/asecpub{yy}csv.zip"

HH_COLS = ["H_SEQ", "H_HHTYPE", "HTOTVAL", "HSUP_WGT"]
PERSON_COLS = ["PH_SEQ", "PTOTVAL", "HRSWK", "WKSWORK", "MARSUPWT"]

# Income brackets: (lower bound, label). The last bracket is open-ended.
HH_BINS = [
    (-np.inf, "Under $25k"),
    (25_000, "$25–50k"),
    (50_000, "$50–75k"),
    (75_000, "$75–100k"),
    (100_000, "$100–150k"),
    (150_000, "$150–200k"),
    (200_000, "$200–300k"),
    (300_000, "$300k+"),
]
PERSON_BINS = [
    (-np.inf, "Under $10k"),
    (10_000, "$10–25k"),
    (25_000, "$25–50k"),
    (50_000, "$50–75k"),
    (75_000, "$75–100k"),
    (100_000, "$100–150k"),
    (150_000, "$150–200k"),
    (200_000, "$200k+"),
]

# Chart tokens (light surface).
SURFACE = "#fcfcfb"
SERIES = "#2a78d6"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
TEXT_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"


def fetch_zip(year, cache_dir):
    yy = f"{year % 100:02d}"
    path = cache_dir / f"asecpub{yy}csv.zip"
    if not path.exists():
        url = URL.format(year=year, yy=yy)
        print(f"Downloading {url}", file=sys.stderr)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
        tmp.rename(path)
    return path


def read_member(zf, prefix, cols):
    """Read one of hhpubYY.csv / pppubYY.csv from the ASEC zip."""
    names = [n for n in zf.namelist() if Path(n).name.lower().startswith(prefix) and n.lower().endswith(".csv")]
    if not names:
        raise SystemExit(f"No {prefix}*.csv in zip (found: {zf.namelist()})")
    with zf.open(names[0]) as f:
        header = pd.read_csv(io.TextIOWrapper(f), nrows=0).columns
    missing = set(cols) - set(header)
    if missing:
        raise SystemExit(f"{names[0]} is missing columns {sorted(missing)}")
    with zf.open(names[0]) as f:
        return pd.read_csv(f, usecols=cols)


def load(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        hh = read_member(zf, "hhpub", HH_COLS)
        pp = read_member(zf, "pppub", PERSON_COLS)
    # Interviewed households only; non-interview records carry no people.
    hh = hh[hh["H_HHTYPE"] == 1]
    # HRSWK is 0 for people who did not work last year (or are not in universe).
    pp["worked"] = pp["HRSWK"] > 0
    pp["annual_hours"] = pp["HRSWK"] * pp["WKSWORK"]
    return hh, pp


def bracket(values, bins):
    edges = [lo for lo, _ in bins] + [np.inf]
    labels = [label for _, label in bins]
    return pd.cut(values, edges, labels=labels, right=False)


def weighted_summary(df, value_cols, weight, group):
    def agg(g):
        w = g[weight]
        out = {f"mean_{c}": np.average(g[c], weights=w) if w.sum() > 0 else np.nan for c in value_cols}
        out["n_unweighted"] = len(g)
        out["weighted_count"] = w.sum()
        return pd.Series(out)

    out = df.groupby(group, observed=False)[value_cols + [weight]].apply(agg).reset_index()
    return out.astype({"n_unweighted": int})


def household_table(hh, pp):
    workers = pp[pp["worked"]]
    totals = workers.groupby("PH_SEQ").agg(
        weekly_hours=("HRSWK", "sum"),
        annual_hours=("annual_hours", "sum"),
        n_workers=("HRSWK", "size"),
    )
    df = hh.merge(totals, left_on="H_SEQ", right_index=True, how="left")
    df[["weekly_hours", "annual_hours", "n_workers"]] = df[["weekly_hours", "annual_hours", "n_workers"]].fillna(0)
    df["income_bin"] = bracket(df["HTOTVAL"], HH_BINS)

    cols = ["weekly_hours", "annual_hours", "n_workers"]
    with_workers = weighted_summary(df[df["n_workers"] > 0], cols, "HSUP_WGT", "income_bin")
    everyone = weighted_summary(df, cols, "HSUP_WGT", "income_bin")
    everyone = everyone.add_suffix("_all_households").rename(columns={"income_bin_all_households": "income_bin"})
    return with_workers.merge(everyone, on="income_bin")


def person_table(pp):
    df = pp[pp["worked"]].copy()
    df["income_bin"] = bracket(df["PTOTVAL"], PERSON_BINS)
    return weighted_summary(df, ["HRSWK", "annual_hours"], "MARSUPWT", "income_bin").rename(
        columns={"mean_HRSWK": "mean_weekly_hours"}
    )


def column_path(x0, x1, top, rx, ry):
    """Column with rounded top corners and a square base (cubic-Bezier corners)."""
    k = 1 - 0.5523  # control-point offset for a quarter circle
    verts = [
        (x0, 0), (x0, top - ry),
        (x0, top - ry * k), (x0 + rx * k, top), (x0 + rx, top),
        (x1 - rx, top),
        (x1 - rx * k, top), (x1, top - ry * k), (x1, top - ry),
        (x1, 0), (x0, 0),
    ]
    C = MplPath.CURVE4
    codes = [MplPath.MOVETO, MplPath.LINETO, C, C, C, MplPath.LINETO, C, C, C, MplPath.LINETO, MplPath.CLOSEPOLY]
    return MplPath(verts, codes)


def column_chart(labels, values, title, subtitle, xlabel, source, path):
    """Single-series column chart: thin columns, 4px rounded caps, values on the caps."""
    dpi = 100
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=dpi)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.83, bottom=0.19)

    n = len(values)
    ymax = np.nanmax(values) * 1.15
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_ylim(0, ymax)

    # Convert pixel specs (24px column, 4px corner radius) to data units.
    bbox = ax.get_window_extent()
    px_per_x = bbox.width / (n - 0.4 + 0.6)
    px_per_y = bbox.height / ymax
    width = 24 / px_per_x
    rx, ry = 4 / px_per_x, 4 / px_per_y

    for i, v in enumerate(values):
        if not np.isfinite(v) or v <= 0:
            continue
        ax.add_patch(PathPatch(column_path(i - width / 2, i + width / 2, v, rx, min(ry, v)),
                               facecolor=SERIES, edgecolor="none", zorder=3))
        ax.text(i, v + 6 / px_per_y, f"{v:.1f}", ha="center", va="bottom", fontsize=10, color=TEXT_PRIMARY, zorder=4)

    ax.set_xticks(range(n), labels)
    ax.tick_params(axis="x", length=0, pad=8, labelsize=10, labelcolor=TEXT_SECONDARY)
    ax.tick_params(axis="y", length=0, pad=6, labelsize=10, labelcolor=TEXT_MUTED)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    ax.grid(axis="y", color=GRID, linewidth=1, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.spines["bottom"].set_linewidth(1)
    ax.set_xlabel(xlabel, fontsize=10, color=TEXT_SECONDARY, labelpad=10)
    ax.set_ylabel("Hours per week", fontsize=10, color=TEXT_SECONDARY, labelpad=8)

    fig.text(0.08, 0.93, title, fontsize=14, fontweight="bold", color=TEXT_PRIMARY)
    fig.text(0.08, 0.875, subtitle, fontsize=10, color=TEXT_SECONDARY)
    fig.text(0.08, 0.03, source, fontsize=8.5, color=TEXT_MUTED)
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2025, help="ASEC release year (income/hours refer to year-1)")
    parser.add_argument("--zip", type=Path, help="Use an already-downloaded asecpubYYcsv.zip")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    args = parser.parse_args()

    zip_path = args.zip or fetch_zip(args.year, args.data_dir)
    hh, pp = load(zip_path)
    ref_year = args.year - 1
    source = f"Source: Census Bureau, CPS ASEC {args.year} public-use file, weighted. Income and hours refer to {ref_year}."

    args.out_dir.mkdir(parents=True, exist_ok=True)
    hh_tab = household_table(hh, pp)
    pp_tab = person_table(pp)
    hh_tab.to_csv(args.out_dir / "hours_by_household_income.csv", index=False)
    pp_tab.to_csv(args.out_dir / "hours_by_individual_income.csv", index=False)

    column_chart(
        hh_tab["income_bin"].astype(str), hh_tab["mean_weekly_hours"].to_numpy(),
        title="Household hours worked by household income",
        subtitle="Average usual weekly hours, summed across all working members · households with at least one worker",
        xlabel=f"Total household income ({ref_year} dollars)",
        source=source, path=args.out_dir / "hours_by_household_income.png",
    )
    column_chart(
        pp_tab["income_bin"].astype(str), pp_tab["mean_weekly_hours"].to_numpy(),
        title="Hours worked by individual income",
        subtitle="Average usual weekly hours · people who worked last year",
        xlabel=f"Total personal income ({ref_year} dollars)",
        source=source, path=args.out_dir / "hours_by_individual_income.png",
    )

    pd.set_option("display.width", 160)
    print("Households with at least one worker:\n", hh_tab[["income_bin", "mean_weekly_hours", "mean_n_workers", "n_unweighted"]].round(1))
    print("\nIndividuals who worked:\n", pp_tab[["income_bin", "mean_weekly_hours", "n_unweighted"]].round(1))
    print(f"\nWrote charts and tables to {args.out_dir}/")


if __name__ == "__main__":
    main()
