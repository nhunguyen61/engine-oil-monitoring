# Engine Oil Condition Report: 2026-09

## Summary
- Samples analysed: **36** from **8** units
- Results at **Critical**: 17, **Caution**: 6
- Statistical anomalies (sudden change vs the unit's own history): 4

## Units needing action

| Unit | Site | Parameter | Latest value | Limit status | Robust z | Samples flagged |
|---|---|---|---|---|---|---|
| HT-103 | Site A | k_ppm | 73.8 | Critical | 1.05 | 5 |
| HT-103 | Site A | na_ppm | 111.0 | Critical | 0.98 | 5 |
| HT-103 | Site A | water_ppm | 2885.0 | Critical | 0.79 | 5 |
| HT-204 | Site B | cu_ppm | 45.8 | Critical | 1.88 | 4 |
| HT-204 | Site B | pb_ppm | 34.4 | Critical | 1.8 | 4 |

## Interpretation (for the maintenance team to confirm)

- **HT-103**: Na/K/water pattern is consistent with a **coolant leak**.
- **HT-204**: Cu/Pb increase points to **bearing wear**.

## Trend: results outside limits, last 3 months

| Month | Results outside limits |
|---|---|
| 2026-07 | 16 |
| 2026-08 | 14 |
| 2026-09 | 23 |

## Data quality this month

- Fixes and rejections logged: 7 (see `data_quality_log.csv`)
  - inconsistent format: 2
  - missing unit_id: 2
  - exact duplicate record: 1
  - water reported in %: 1
  - missing result: 1

_Limits are indicative (see `reference/limits.csv`) and should be replaced with OEM or site-specific limits._