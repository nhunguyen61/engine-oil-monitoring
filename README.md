# Engine Oil Condition Monitoring: Lab API → Power BI

An end-to-end pipeline that pulls engine oil analysis results from a laboratory REST API, cleans and validates them, flags results outside limits, detects unusual changes before they breach limits, and produces a monthly condition report.

The lab API is **simulated**: no public oil-analysis API exists. `generator/` creates a paginated JSON API (hosted here on GitHub) with realistic data-quality problems injected on purpose. The data covers 8 mining units (haul trucks, excavators, a loader), 50 weeks, and 412 records.

![Early warning example](docs/img/early_warning.png)

*Anomaly detection flagged HT-204's bearing wear **2 weeks** before the caution limit was breached, and HT-103's coolant leak **2 weeks** earlier as well.*

---

## What it does

| Step | Where | Detail |
|---|---|---|
| 1. Ingest | Power Query `fnGetPage`, `RawSamples` / `python/pipeline.py` | Reads `meta.total_pages`, fetches every page, flattens nested JSON |
| 2. Clean & validate | Power Query `Samples` / Python `clean()` | Duplicates, unit-ID formats, two date formats, invalid dates, unit-of-measure errors, missing fields |
| 3. Limits | DAX `Limit Status` / Python `to_long()` | Caution / Critical against `reference/limits.csv` (high- and low-side) |
| 4. Anomaly detection | DAX `Robust Z`, `Is Anomaly` / Python `add_anomalies()` | Each result compared with the same unit's previous 8 samples |
| 5. Report | Power BI report + `output/monthly_report_YYYY-MM.md` | Units needing action, likely cause, 3-month trend, data quality |

## Data quality rules

Every fix is written to `output/data_quality_log.csv` with the before/after values. Nothing is changed silently.

| Problem from the lab | Rule | Count in mock data |
|---|---|---|
| Exact duplicate record (re-sent sample) | Drop; keep first | 12 |
| Same `sample_id`, different values | Drop second, ask lab which is correct | 0 |
| `unit_id` as `ht-103`, ` HT-103 `, `HT103` | Trim, upper-case, restore hyphen | 15 |
| `unit_id` missing | **Quarantine** (cannot link to equipment) | 5 |
| `sample_date` as `dd/mm/yyyy` text | Parse as Australian format | 5 |
| Placeholder `1900-01-01`, future date, or after `received_date` | Impute `received_date − 3 days`, flag `sample_date_imputed` | 11 |
| Water reported in % | Convert to ppm (×10,000) | 10 |
| Viscosity reported at 40 °C | **Blank it** and request the 100 °C result. Converting needs the viscosity index, so any conversion would be a guess | 6 |
| Missing result (e.g. Fe) | Leave blank; never treat as 0 | 12 |

## Anomaly detection method

Fixed limits only fire once a problem is already serious. The anomaly check asks a different question: *is this result unusual for this particular unit?*

- **Baseline:** median of the unit's previous 8 results for that parameter (at least 5 needed).
- **Score:** robust z = 0.6745 × (value − median) / MAD (Iglewicz & Hoaglin, 1993). Median and MAD are used instead of mean and SD so that one bad past sample doesn't distort the baseline.
- **Noise floor:** MAD is floored at 15% of the median. Without it, a very stable history turns small lab noise into false alarms. This floor cut flags from 147 to 27.
- **Direction:** only harmful changes count (wear metals up, TBN down, viscosity either way).
- **Threshold:** |z| ≥ 3.5.

**Results on the mock data:** all four injected faults (coolant leak, dust ingestion, bearing wear, fuel dilution) were caught. 12 anomaly flags fired while results were still inside limits: 11 were genuine early warnings on real faults and 1 (LD-401 water, 670 ppm) was a false positive.

**Known limitation:** during a sustained trend the baseline catches up, so anomaly flags stop after a few samples. This is intended: by then the result is outside fixed limits and the limit check takes over. The two checks are designed to work together.

## Power BI setup

1. Power BI Desktop → *Transform data* → *New source → Blank query* → *Advanced editor*.
2. Paste each file from `powerquery/` in order, naming each query after its file (`fnGetPage`, `RawSamples`, `Samples`, `ResultsLong`, `Quarantine`, `Limits`).
3. Create a `Date` table and relationships as listed at the top of `dax/measures_and_columns.dax`, then add the columns and measures from that file.
4. Suggested pages: **Status board** (unit × parameter matrix coloured by `Limit Status`), **Trends** (line per parameter with limit lines and anomaly markers), **Data quality** (`Quarantined Records`, `Imputed Sample Dates`, `Days Since Last Received`).

**Scheduled refresh:** `fnGetPage` keeps the base URL static and passes the page through `RelativePath`. Power BI Service refuses to refresh `Web.Contents` calls with a URL built by string concatenation ("dynamic data source"), so this matters for a live feed.

**Real lab API:** add the API key with `ApiKeyName` (or a header) and store it in the data source credentials, never in query text. Pagination may use `next` links or offsets instead of `total_pages`; only `RawSamples` needs to change.

## Run the Python version

```bash
pip install -r requirements.txt
python generator/generate_mock_api.py      # rebuild the mock API (optional)
python python/pipeline.py                   # local files
python python/pipeline.py --source api      # call the hosted API
python python/pipeline.py --month 2026-08   # report for a specific month
```

The Python pipeline applies the same rules as Power Query, so the two outputs can be reconciled. It is also a fallback if the Power BI refresh fails.

## Handover notes

- **Monthly routine (~5 h/month):** check `Days Since Last Received` (feed health) → review `Quarantine` and the data quality log, send open issues to the lab → review units needing action → export the report and send it by the deadline.
- **If the feed breaks:** look at the `RawSamples` error message first. The HTTP status is surfaced (404 = endpoint changed, 401/403 = key expired, 429 = rate limit, so retry later).
- **Changing limits:** edit `reference/limits.csv` only. Nothing is hard-coded in Power Query or DAX.
- **Limits are indicative** general diesel-engine values. Replace them with OEM or site-specific limits before any operational use.
- **Interpretation hints** in the report (coolant leak, dirt ingestion, bearing wear, fuel dilution) are standard oil-analysis patterns. They are prompts for the maintenance team to check, not diagnoses.

## Repo structure

```
generator/        mock lab API generator
mock_api/v1/      paginated JSON (the "API")
reference/        limits.csv
powerquery/       M queries for Power BI
dax/              calculated columns and measures
python/           pipeline.py (reference implementation)
output/           cleaned data, data quality log, monthly reports
docs/img/         charts
```

---
*Author: Nhu (Julie) Nguyen, Master of Business Analytics, University of Wollongong*
