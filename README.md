# Engine Oil Condition Monitoring

### Data Cleaning, Validation & Condition Monitoring with Python and Power BI

An end-to-end project that processes laboratory oil analysis data, flags results outside limits, detects unusual changes before they breach limits, and prepares the data for a Power BI condition monitoring dashboard.

**Project status:** Python pipeline, Power Query preparation and initial DAX measures completed. Power BI dashboard in progress.

> **Note:** All data in this project is **simulated**. No public oil analysis API exists, so `generator/generate_mock_api.py` creates a mock laboratory API with realistic data quality problems built in.

---

## 1. Project Overview

Engine oil analysis is used in condition-based maintenance to monitor equipment health. Lab results show wear metals, contamination and lubricant condition, which can reveal problems such as coolant leaks or bearing wear before a breakdown.

Raw lab data is often messy: duplicate records, missing values, inconsistent equipment IDs, wrong units and invalid dates. If these are not fixed, condition assessments become unreliable.

This project builds a repeatable workflow to clean and validate that data, flag abnormal results, and feed a Power BI dashboard.

## 2. Project Objectives

1. Extract and structure lab oil analysis data from a paginated mock API.
2. Clean and validate records before analysis, logging every change.
3. Standardise equipment IDs, dates and units of measurement.
4. Flag results that exceed caution and critical limits.
5. Detect unusual changes in each unit's results over time.
6. Prepare datasets and measures for Power BI reporting.
7. Produce a short monthly condition report.

## 3. Dataset Overview

| Item | Detail |
|---|---|
| Equipment | 8 units at 2 mine sites: 5 haul trucks, 2 excavators, 1 wheel loader |
| Period | Weekly samples, Nov 2025 – Oct 2026 |
| Records | 412 raw records (400 unique samples + 12 re-sent duplicates) |
| API format | 9 JSON pages of 50 records, each with a `next` link to the following page |

| Category | Fields |
|---|---|
| Equipment information | Unit ID, equipment type, engine model, site |
| Sample information | Sample ID, sample date, received date, oil hours |
| Wear metals | Fe, Cu, Al, Cr, Pb (ppm) |
| Contamination | Si, Na, K (ppm), water (ppm) |
| Oil condition | Viscosity at 100°C (cSt), TBN (mgKOH/g), soot (%) |

Four equipment faults were also built into the data so the detection methods can be tested against a known answer:

| Unit | Simulated fault | Parameters affected |
|---|---|---|
| HT-103 | Coolant leak (from June 2026) | Na, K, water rising |
| EX-302 | Dust ingestion (March–April 2026) | Si, Fe, Al spike |
| HT-204 | Bearing wear (from August 2026) | Cu, Pb rising |
| LD-401 | Fuel dilution (June–July 2026) | Viscosity dropping |

## 4. Data Processing Pipeline

The pipeline (`python/pipeline.py`) is written in Python using Pandas and NumPy.

### 4.1 Data Extraction

Records are read from the local mock API files, or over HTTP from the GitHub-hosted copy. The pipeline follows each page's `next` link until it is empty, then flattens the nested JSON (`results` and `units`) into one row per sample.

### 4.2 Data Cleaning and Validation

Every fix or exclusion is written to `data_quality_log.csv` with the value before and after. Nothing is changed silently.

| Issue | Rule applied | Log entries |
|---|---|---|
| Unit ID in different formats (`ht-103`, ` HT-103 `, `HT103`) | Trim, upper-case, restore the hyphen | 15 |
| Exact duplicate record | Drop, keep the first | 12 |
| Same sample ID with different values | Drop the second, flag for lab follow-up | 0 |
| Missing result (e.g. Fe) | Leave blank, never treat as zero | 12 |
| Water reported in % instead of ppm | Convert to ppm (× 10,000) | 10 |
| Viscosity reported at 40°C instead of 100°C | Remove the value and flag for lab follow-up. Converting needs the oil's viscosity index, so any conversion would be a guess | 6 |
| Sample date as `dd/mm/yyyy` text | Parse as Australian date format | 5 |
| Placeholder date (`1900-01-01`), future date, or sample date after received date | Estimate as received date − 3 days and mark `sample_date_imputed = True` | 11 |
| Missing unit ID | Move to `quarantine.csv`, as the record cannot be linked to equipment | 5 |

Result: 412 raw records → 395 clean samples + 5 quarantined (12 duplicates removed).

### 4.3 Threshold-Based Monitoring

Each result is compared with the limits in `reference/limits.csv`:

| Status | Meaning |
|---|---|
| Normal | Within limits |
| Caution | Reached the caution limit |
| Critical | Reached the critical limit |

Most parameters have upper limits only. TBN has a lower limit, and viscosity has both a lower limit (fuel dilution) and an upper limit (oxidation or soot).

The limits are indicative values for diesel engines, not manufacturer (OEM) limits. Changing limits only requires editing `limits.csv`.

### 4.4 Anomaly Detection

Fixed limits only trigger once a problem is already serious. The anomaly check asks a different question: *is this result unusual for this particular unit?*

Each result is compared with the same unit's previous results for that parameter using a rolling robust z-score:

robust z = 0.6745 × (value − median) / MAD

where the median and MAD (median absolute deviation) come from the previous 8 samples.

| Setting | Value | Reason |
|---|---|---|
| Rolling window | 8 previous samples | About two months of history |
| Minimum history | 5 samples | Not enough history means no judgement |
| Threshold | \|z\| ≥ 3.5 | Standard cut-off for robust z-scores (Iglewicz & Hoaglin, 1993) |
| Noise floor | MAD is at least 15% of the median | Stops very stable histories turning small lab noise into false alarms |
| Direction | Only harmful changes count | Wear metals and contaminants rising, TBN falling, viscosity either way |

Median and MAD are used instead of mean and standard deviation, so one bad past result does not distort the baseline.

Anomaly flags are prompts for further investigation, not a diagnosis.

## 5. Results

All four simulated faults were detected, and no limit flags were raised on healthy units.

| Unit | Fault | Detected by | Timing |
|---|---|---|---|
| HT-103 | Coolant leak | Anomaly, then limits | Anomaly on 1 Jun, about 2 weeks before K reached its caution limit (16 Jun) |
| HT-204 | Bearing wear | Anomaly, then limits | Anomaly on 12 Aug, 2 weeks before Pb reached its caution limit (26 Aug) |
| EX-302 | Dust ingestion | Limits and anomaly | Same sample (11 Mar), as the spike was sudden |
| LD-401 | Fuel dilution | Limits only (Caution) | The drop was too small for the anomaly check |

- **Early warnings:** 12 anomaly flags were raised while results were still within limits. 11 were on real faults, and 1 was a false positive (LD-401 water, 670 ppm).
- **Limitation:** during a long upward trend, the rolling baseline catches up, so anomaly flags stop after a few samples. By then the result is outside fixed limits, so the limit check takes over. The two methods are meant to be used together.

## 6. Power BI Data Preparation

### 6.1 Power Query

Power Query prepares the data for the Power BI model:

- Data ingestion and transformation
- Data type validation
- Consistent column structures
- Combining measurement data with reference limits

### 6.2 DAX Measures

DAX measures for the dashboard cover:

- Total samples
- Caution and Critical result counts
- Latest sample dates and latest values
- Equipment condition status
- Severity-based conditional formatting

These update based on the selected equipment units and parameters.

## 7. Data Outputs

| File | Description |
|---|---|
| `samples_clean.csv` | One row per valid sample |
| `results_long.csv` | One row per sample × parameter, with limit status, robust z-score and anomaly flag |
| `data_quality_log.csv` | Every fix and exclusion, with the reason and before/after values |
| `quarantine.csv` | Records excluded from the clean dataset |
| `monthly_report_YYYY-MM.md` | Monthly equipment condition summary |

## 8. Monthly Condition Reporting

The pipeline generates a monthly report covering:

- Number of samples analysed
- Caution and Critical results
- Anomalies
- Units needing action, with a likely cause (e.g. Na/K/water rising suggests a coolant leak)
- Results outside limits over the last 3 months
- Data quality issues for the month

The suggested causes are standard oil analysis patterns for the maintenance team to check, not diagnoses.

## 9. Tools and Technologies

| Tool | Purpose |
|---|---|
| Python (Pandas, NumPy) | Data extraction, cleaning, limit checks, anomaly detection |
| JSON / mock REST API | Simulated laboratory data source |
| Power Query | Data preparation within Power BI |
| DAX | Measures and monitoring logic |
| Power BI | Interactive reporting (in progress) |
| GitHub | Version control, documentation, hosting the mock API |

## 10. How to Run

```bash
pip install pandas numpy
```

Run the pipeline on the local mock API files:

```bash
python python/pipeline.py
```

Read the data over HTTP from the GitHub-hosted mock API:

```bash
python python/pipeline.py --source api
```

Create the report for a chosen month (default: the latest complete month):

```bash
python python/pipeline.py --month 2026-09
```

Optional: rebuild the mock data from scratch:

```bash
python generator/generate_mock_api.py
```

Outputs are saved in `output/`.

## 11. Repository Structure

```
generator/        script that creates the simulated lab data
mock_api/v1/      the mock API: 9 paginated JSON pages
reference/        limits.csv (caution and critical limits)
python/           pipeline.py (cleaning, limits, anomalies, report)
powerquery/       Power Query (M) scripts
dax/              DAX measures
output/           cleaned data, data quality log, quarantine, monthly report
```

## 12. Project Progress

| Task | Status |
|---|---|
| Mock API data extraction | Completed |
| Data cleaning and validation | Completed |
| Data quality logging | Completed |
| Threshold-based monitoring | Completed |
| Anomaly detection | Completed |
| Monthly report generation | Completed |
| Power Query data preparation | Completed |
| Initial DAX measures | Completed |
| Power BI dashboard | In progress |
| Dashboard validation and final presentation | Planned |

## 13. Next Steps

The Power BI report will have three pages:

- **Fleet Condition Overview:** condition of each unit, results outside limits, latest values
- **Equipment Trends:** results over time with limit lines, filtered by unit and parameter
- **Data Quality:** issues fixed, missing information and quarantined records

Dashboard screenshots will be added once the report is complete.

## 14. Author

**Nhu (Julie) Nguyen**
Master of Business Analytics, University of Wollongong
GitHub: [nhunguyen61](https://github.com/nhunguyen61)

Interests: data analytics, supply chain analytics, operations and business intelligence.
