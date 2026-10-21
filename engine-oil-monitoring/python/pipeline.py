"""
Engine oil analysis pipeline: fetch -> flatten -> clean/validate -> limit flags ->
anomaly detection -> outputs for Power BI + monthly report.

Usage
-----
  python python/pipeline.py                 # read the mock API from local files
  python python/pipeline.py --source api    # call the hosted API over HTTP (follows 'next' links)
  python python/pipeline.py --month 2026-09 # month for the summary report (default: latest full month)

Outputs (folder: output/)
-------------------------
  samples_clean.csv      one row per valid sample (wide), used by Power BI
  results_long.csv       one row per sample x parameter, with limit status and anomaly flag
  data_quality_log.csv   every fix / rejection the pipeline made, with the reason
  quarantine.csv         records that could not be used (e.g. no unit_id)
  monthly_report_<YYYY-MM>.md
"""

import argparse
import json
import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / "mock_api" / "v1" / "samples"
API_FIRST_PAGE = ("https://raw.githubusercontent.com/nhunguyen61/engine-oil-monitoring/"
                  "main/mock_api/v1/samples/page_1.json")
OUT = ROOT / "output"
PARAMS = ["fe_ppm", "cu_ppm", "al_ppm", "cr_ppm", "pb_ppm", "si_ppm", "na_ppm",
          "k_ppm", "water_ppm", "visc_100c_cst", "tbn_mgkoh_g", "soot_pct"]

# Anomaly detection settings (robust z-score, Iglewicz & Hoaglin 1993)
WINDOW = 8          # previous samples of the same unit used as the baseline
MIN_HISTORY = 5     # need at least this many earlier samples before judging
Z_THRESHOLD = 3.5

log_rows = []


def log(sample_id, field, issue, action, before=None, after=None):
    log_rows.append({"sample_id": sample_id, "field": field, "issue": issue,
                     "action": action, "value_before": before, "value_after": after})


# ---------------------------------------------------------------- 1. Fetch
def fetch_local():
    pages = sorted(LOCAL_DIR.glob("page_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    return [r for p in pages for r in json.loads(p.read_text())["data"]]


def fetch_api(url=API_FIRST_PAGE):
    """Follow the 'next' link until it is null (same logic as the Power Query version)."""
    records = []
    while url:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = json.load(resp)
        records.extend(body["data"])
        url = body["links"]["next"]
    return records


# ---------------------------------------------------------------- 2. Flatten
def flatten(records):
    rows = []
    for r in records:
        row = {k: v for k, v in r.items() if k not in ("results", "units")}
        for p in PARAMS:
            row[p] = r.get("results", {}).get(p)
        row["water_unit"] = r.get("units", {}).get("water")
        row["visc_unit"] = r.get("units", {}).get("viscosity")
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. Clean
def parse_date(value):
    if value is None or pd.isna(value):
        return pd.NaT
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):     # Australian lab format dd/mm/yyyy
        return pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    return pd.NaT


def normalise_unit_id(u):
    if u is None or pd.isna(u):
        return None
    s = str(u).strip().upper()
    m = re.fullmatch(r"([A-Z]{2})-?(\d{3})", s)
    return f"{m.group(1)}-{m.group(2)}" if m else s


def clean(df, today):
    df = df.copy()

    # 3a. Exact duplicates (lab re-sent the same sample)
    dup_mask = df.duplicated(keep="first")
    for sid in df.loc[dup_mask, "sample_id"]:
        log(sid, "*", "exact duplicate record", "dropped")
    df = df[~dup_mask]
    # Same sample_id but different content -> keep first, flag for lab follow-up
    conflict = df.duplicated(subset="sample_id", keep="first")
    for sid in df.loc[conflict, "sample_id"]:
        log(sid, "sample_id", "same sample_id with different values", "dropped; ask lab which is correct")
    df = df[~conflict]

    # 3b. Unit IDs: trim, upper-case, restore hyphen
    for i, raw in df["unit_id"].items():
        fixed = normalise_unit_id(raw)
        if raw is not None and fixed != raw:
            log(df.at[i, "sample_id"], "unit_id", "inconsistent format", "standardised", raw, fixed)
        df.at[i, "unit_id"] = fixed

    # 3c. Dates
    df["received_date"] = df["received_date"].map(parse_date)
    raw_dates = df["sample_date"].copy()
    df["sample_date"] = df["sample_date"].map(parse_date)
    df["sample_date_imputed"] = False
    for i in df.index:
        sid, raw, d, rec = df.at[i, "sample_id"], raw_dates[i], df.at[i, "sample_date"], df.at[i, "received_date"]
        if isinstance(raw, str) and "/" in raw and pd.notna(d):
            log(sid, "sample_date", "dd/mm/yyyy text format", "converted to ISO date", raw, d.date().isoformat())
        problem = None
        if pd.isna(d):
            problem = "unparseable or missing"
        elif d.year < 2000:
            problem = "placeholder date (1900-01-01)"
        elif d > today:
            problem = "date in the future"
        elif pd.notna(rec) and d > rec:
            problem = "sample_date after received_date"
        if problem:
            # Typical transit is 2-6 days, so received_date - 3 days is a safe estimate for trending.
            new = rec - pd.Timedelta(days=3) if pd.notna(rec) else pd.NaT
            df.at[i, "sample_date"] = new
            df.at[i, "sample_date_imputed"] = True
            log(sid, "sample_date", problem, "imputed as received_date - 3 days; confirm with site",
                raw, None if pd.isna(new) else new.date().isoformat())

    # 3d. Units of measure
    for i in df.index[df["water_unit"] == "%"]:
        before = df.at[i, "water_ppm"]
        df.at[i, "water_ppm"] = round(before * 10000)
        log(df.at[i, "sample_id"], "water_ppm", "water reported in %", "converted % to ppm (x10,000)", before, df.at[i, "water_ppm"])
    for i in df.index[df["visc_unit"] == "cSt@40C"]:
        # 40C -> 100C needs the oil's viscosity index; converting would be a guess, so remove it.
        log(df.at[i, "sample_id"], "visc_100c_cst", "viscosity reported at 40C, not 100C",
            "set to blank; request 100C result from lab", df.at[i, "visc_100c_cst"], None)
        df.at[i, "visc_100c_cst"] = np.nan
    df = df.drop(columns=["water_unit", "visc_unit"])

    # 3e. Missing values
    for p in PARAMS:
        for sid in df.loc[df[p].isna() & ~df["sample_id"].isin(
                [r["sample_id"] for r in log_rows if r["field"] == p]), "sample_id"]:
            log(sid, p, "missing result", "left blank (not treated as zero)")

    # 3f. Records that cannot be used at all go to quarantine
    no_unit = df["unit_id"].isna()
    for sid in df.loc[no_unit, "sample_id"]:
        log(sid, "unit_id", "missing unit_id", "quarantined; cannot link to equipment")
    quarantine = df[no_unit].copy()
    df = df[~no_unit].copy()

    df["sample_month"] = df["sample_date"].dt.to_period("M").astype(str)
    return df.sort_values(["unit_id", "sample_date"]).reset_index(drop=True), quarantine


# ---------------------------------------------------------------- 4. Limits + anomalies
def to_long(df, limits):
    long = df.melt(id_vars=["sample_id", "unit_id", "equipment_type", "site", "sample_date",
                            "sample_month", "oil_hours"],
                   value_vars=PARAMS, var_name="parameter", value_name="value").dropna(subset=["value"])

    def status(row):
        worst = "Normal"
        for _, lim in limits[limits["parameter"] == row["parameter"]].iterrows():
            v = row["value"]
            if lim["direction"] == "high":
                if v >= lim["critical"]:
                    return "Critical"
                if v >= lim["caution"]:
                    worst = "Caution"
            else:
                if v <= lim["critical"]:
                    return "Critical"
                if v <= lim["caution"]:
                    worst = "Caution"
        return worst

    long["limit_status"] = long.apply(status, axis=1)
    return long


def robust_z(series):
    """Compare each value with the median of the unit's previous WINDOW samples."""
    prev = series.shift(1)
    med = prev.rolling(WINDOW, min_periods=MIN_HISTORY).median()
    mad = prev.rolling(WINDOW, min_periods=MIN_HISTORY).apply(
        lambda x: np.median(np.abs(x - np.median(x))), raw=True)
    # Floor the spread so a very stable history does not turn tiny changes into "anomalies":
    # at least 15% of the baseline median (roughly lab repeatability for spectrometry).
    mad = np.maximum(mad, 0.15 * med.abs() / 0.6745)
    return 0.6745 * (series - med) / mad


def add_anomalies(long):
    long = long.sort_values(["unit_id", "parameter", "sample_date"]).copy()
    long["robust_z"] = long.groupby(["unit_id", "parameter"])["value"].transform(robust_z).round(2)
    # Only the harmful direction counts: a high-side parameter that suddenly rises,
    # or viscosity / TBN that suddenly drops. Viscosity can fail both ways.
    low_side = long["parameter"].isin(["tbn_mgkoh_g"])
    both = long["parameter"].isin(["visc_100c_cst"])
    z = long["robust_z"]
    long["is_anomaly"] = np.where(both, z.abs() >= Z_THRESHOLD,
                          np.where(low_side, z <= -Z_THRESHOLD, z >= Z_THRESHOLD))
    return long


# ---------------------------------------------------------------- 5. Monthly report
def monthly_report(month, clean_df, long, dq, quarantine):
    m = long[long["sample_month"] == month]
    samples = clean_df[clean_df["sample_month"] == month]
    flagged = m[(m["limit_status"] != "Normal") | m["is_anomaly"]].copy()

    lines = [f"# Engine Oil Condition Report: {month}", "",
             "## Summary",
             f"- Samples analysed: **{len(samples)}** from **{samples['unit_id'].nunique()}** units",
             f"- Results at **Critical**: {int((m['limit_status'] == 'Critical').sum())}, "
             f"**Caution**: {int((m['limit_status'] == 'Caution').sum())}",
             f"- Statistical anomalies (sudden change vs the unit's own history): {int(m['is_anomaly'].sum())}",
             "", "## Units needing action", ""]

    if flagged.empty:
        lines.append("No units outside limits this month.")
    else:
        rank = {"Critical": 0, "Caution": 1, "Normal": 2}
        flagged["rank"] = flagged["limit_status"].map(rank)
        lines += ["| Unit | Site | Parameter | Latest value | Limit status | Robust z | Samples flagged |",
                  "|---|---|---|---|---|---|---|"]
        for (unit, param), g in flagged.sort_values(["rank", "unit_id"]).groupby(["unit_id", "parameter"], sort=False):
            last = g.sort_values("sample_date").iloc[-1]
            worst = g.sort_values("rank").iloc[0]["limit_status"]
            lines.append(f"| {unit} | {last['site']} | {param} | {last['value']} | {worst} | "
                         f"{last['robust_z'] if pd.notna(last['robust_z']) else '-'} | {len(g)} |")
        lines += ["", "## Interpretation (for the maintenance team to confirm)", ""]
        units = flagged.groupby("unit_id")["parameter"].apply(set)
        for unit, ps in units.items():
            hints = []
            if {"na_ppm", "k_ppm"} & ps or "water_ppm" in ps:
                hints.append("Na/K/water pattern is consistent with a **coolant leak**")
            if "si_ppm" in ps:
                hints.append("high Si (with Fe/Al) suggests **dirt ingestion**: check air intake and filters")
            if {"cu_ppm", "pb_ppm"} & ps:
                hints.append("Cu/Pb increase points to **bearing wear**")
            if "visc_100c_cst" in ps:
                hints.append("low viscosity suggests **fuel dilution**")
            if "fe_ppm" in ps and "si_ppm" not in ps:
                hints.append("rising Fe indicates **component wear**")
            if hints:
                lines.append(f"- **{unit}**: " + "; ".join(hints) + ".")

    # 3-month trend for context
    months = sorted(long["sample_month"].unique())
    idx = months.index(month)
    recent = months[max(0, idx - 2): idx + 1]
    trend = (long[long["sample_month"].isin(recent)]
             .assign(flag=lambda d: (d["limit_status"] != "Normal"))
             .groupby("sample_month")["flag"].sum())
    lines += ["", "## Trend: results outside limits, last 3 months", "",
              "| Month | Results outside limits |", "|---|---|"]
    lines += [f"| {k} | {int(v)} |" for k, v in trend.items()]

    q_month = quarantine[quarantine["received_date"].dt.to_period("M").astype(str) == month]
    dq_month = dq[dq["sample_id"].isin(samples["sample_id"]) | dq["sample_id"].isin(q_month["sample_id"])]
    lines += ["", "## Data quality this month", "",
              f"- Fixes and rejections logged: {len(dq_month)} (see `data_quality_log.csv`)"]
    for issue, n in dq_month["issue"].value_counts().items():
        lines.append(f"  - {issue}: {n}")
    lines += ["", "_Limits are indicative (see `reference/limits.csv`) and should be replaced with "
              "OEM or site-specific limits._"]
    return "\n".join(lines)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["local", "api"], default="local")
    ap.add_argument("--month", default=None)
    ap.add_argument("--today", default="2026-10-21", help="reference date for 'future date' checks")
    args = ap.parse_args()

    records = fetch_api() if args.source == "api" else fetch_local()
    raw = flatten(records)
    limits = pd.read_csv(ROOT / "reference" / "limits.csv")

    clean_df, quarantine = clean(raw, pd.Timestamp(args.today))
    long = add_anomalies(to_long(clean_df, limits))
    dq = pd.DataFrame(log_rows)

    OUT.mkdir(exist_ok=True)
    clean_df.to_csv(OUT / "samples_clean.csv", index=False)
    long.to_csv(OUT / "results_long.csv", index=False)
    dq.to_csv(OUT / "data_quality_log.csv", index=False)
    quarantine.to_csv(OUT / "quarantine.csv", index=False)

    month = args.month or sorted(clean_df["sample_month"].unique())[-2]  # latest *complete* month
    (OUT / f"monthly_report_{month}.md").write_text(monthly_report(month, clean_df, long, dq, quarantine))

    print(f"Raw records: {len(raw)} | clean samples: {len(clean_df)} | quarantined: {len(quarantine)}")
    print(f"Data quality log entries: {len(dq)}")
    print(dq["issue"].value_counts().to_string())
    print(f"Limit status:\n{long['limit_status'].value_counts().to_string()}")
    print(f"Anomalies: {int(long['is_anomaly'].sum())}")
    print(f"Report: output/monthly_report_{month}.md")


if __name__ == "__main__":
    main()
