"""
Generate a mock commercial-laboratory oil analysis API as static, paginated JSON.

Why static JSON: there is no free public API for engine-oil analysis results, so this
script simulates one. The files are served from GitHub (raw URLs), which lets Power BI
call them exactly like a real REST endpoint (Web.Contents + Json.Document + pagination).

Realistic data-quality problems are injected on purpose so the cleaning pipeline has
something to fix:
  - exact duplicate records (lab re-sends a sample)
  - missing fields (null unit_id, null Fe, missing viscosity)
  - unit errors (water reported in % instead of ppm; viscosity reported at 40C value)
  - date errors (sample_date after received_date, placeholder 1900-01-01, future dates,
    day/month swapped)
  - text inconsistency (unit IDs in different case / with spaces)

Run:  python generator/generate_mock_api.py
"""

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "mock_api" / "v1" / "samples"
PAGE_SIZE = 50
BASE_URL = "https://raw.githubusercontent.com/nhunguyen61/engine-oil-monitoring/main/mock_api/v1/samples"

# Fleet: haul trucks and excavators at two mine sites
UNITS = [
    ("HT-101", "Haul Truck", "Cummins QSK60", "Site A"),
    ("HT-102", "Haul Truck", "Cummins QSK60", "Site A"),
    ("HT-103", "Haul Truck", "Cummins QSK60", "Site A"),
    ("HT-204", "Haul Truck", "MTU 16V4000", "Site B"),
    ("HT-205", "Haul Truck", "MTU 16V4000", "Site B"),
    ("EX-301", "Excavator", "Cummins QSK50", "Site A"),
    ("EX-302", "Excavator", "Cummins QSK50", "Site B"),
    ("LD-401", "Wheel Loader", "Cat C18", "Site B"),
]

START = date(2025, 11, 3)
WEEKS = 50  # roughly one sample per unit per week


def base_reading(hours_on_oil, rng):
    """Normal engine oil readings; wear metals grow slowly with hours on oil."""
    h = hours_on_oil / 250
    return {
        "fe_ppm": round(max(1, rng.gauss(12 + 10 * h, 3)), 1),
        "cu_ppm": round(max(0.5, rng.gauss(4 + 2 * h, 1)), 1),
        "al_ppm": round(max(0.5, rng.gauss(3 + 1.5 * h, 0.8)), 1),
        "cr_ppm": round(max(0.1, rng.gauss(1 + 0.5 * h, 0.3)), 1),
        "pb_ppm": round(max(0.1, rng.gauss(2 + 1 * h, 0.6)), 1),
        "si_ppm": round(max(1, rng.gauss(8 + 3 * h, 2)), 1),
        "na_ppm": round(max(0.5, rng.gauss(4, 1)), 1),
        "k_ppm": round(max(0.1, rng.gauss(1.5, 0.4)), 1),
        "water_ppm": int(max(50, rng.gauss(350, 120))),
        "visc_100c_cst": round(rng.gauss(14.8 - 0.4 * h, 0.3), 2),
        "tbn_mgkoh_g": round(max(2, rng.gauss(10.5 - 2.0 * h, 0.4)), 2),
        "soot_pct": round(max(0, rng.gauss(0.3 + 0.4 * h, 0.1)), 2),
    }


def generate_records():
    rng = random.Random(7)
    records = []
    seq = 10000
    for u_idx, (unit, eq_type, engine, site) in enumerate(UNITS):
        oil_hours = 0
        for w in range(WEEKS):
            sample_date = START + timedelta(weeks=w, days=rng.randint(0, 2))
            oil_hours += rng.randint(110, 150)
            if oil_hours > 500:          # oil change every ~500 h
                oil_hours = rng.randint(110, 150)
            r = base_reading(oil_hours, rng)

            # --- Real faults (the signal the anomaly detection should find) ---
            # HT-103: progressive coolant leak from week 30 (Na, K, water rising)
            if unit == "HT-103" and w >= 30:
                k = w - 29
                r["na_ppm"] = round(r["na_ppm"] + 6 * k, 1)
                r["k_ppm"] = round(r["k_ppm"] + 4 * k, 1)
                r["water_ppm"] += 150 * k
            # EX-302: dust ingestion (air filter) weeks 18-22 -> Si + Fe/Al spike
            if unit == "EX-302" and 18 <= w <= 22:
                r["si_ppm"] = round(r["si_ppm"] + rng.uniform(25, 45), 1)
                r["fe_ppm"] = round(r["fe_ppm"] + rng.uniform(15, 30), 1)
                r["al_ppm"] = round(r["al_ppm"] + rng.uniform(4, 8), 1)
            # HT-204: bearing wear from week 40 -> Cu, Pb trending up
            if unit == "HT-204" and w >= 40:
                k = w - 39
                r["cu_ppm"] = round(r["cu_ppm"] + 5 * k, 1)
                r["pb_ppm"] = round(r["pb_ppm"] + 4 * k, 1)
            # LD-401: fuel dilution weeks 33-35 -> viscosity drops
            if unit == "LD-401" and 33 <= w <= 35:
                r["visc_100c_cst"] = round(r["visc_100c_cst"] - rng.uniform(2.0, 3.0), 2)

            seq += 1
            records.append({
                "sample_id": f"LAB-{seq}",
                "unit_id": unit,
                "equipment_type": eq_type,
                "engine_model": engine,
                "site": site,
                "component": "Engine",
                "oil_grade": "SAE 15W-40",
                "sample_date": sample_date.isoformat(),
                "received_date": (sample_date + timedelta(days=rng.randint(2, 6))).isoformat(),
                "oil_hours": oil_hours,
                "results": r,
                "units": {"water": "ppm", "viscosity": "cSt@100C"},
            })
    return records


def inject_errors(records):
    rng = random.Random(99)
    n = len(records)
    picks = lambda k: rng.sample(range(n), k)

    # 1) Missing fields
    for i in picks(8):
        records[i]["results"]["fe_ppm"] = None
    for i in picks(5):
        records[i]["unit_id"] = None
    for i in picks(4):
        records[i]["results"].pop("visc_100c_cst", None)

    # 2) Unit errors: water reported as %, viscosity reported at 40C
    for i in picks(10):
        ppm = records[i]["results"]["water_ppm"]
        records[i]["results"]["water_ppm"] = round(ppm / 10000, 3)   # value now in %
        records[i]["units"]["water"] = "%"
    for i in picks(6):
        if "visc_100c_cst" in records[i]["results"]:
            records[i]["results"]["visc_100c_cst"] = round(rng.uniform(105, 120), 1)  # 40C value
            records[i]["units"]["viscosity"] = "cSt@40C"

    # 3) Date errors
    for i in picks(4):
        records[i]["sample_date"] = "1900-01-01"            # placeholder date
    for i in picks(4):                                      # sample after received
        d = date.fromisoformat(records[i]["received_date"])
        records[i]["sample_date"] = (d + timedelta(days=rng.randint(3, 10))).isoformat()
    for i in picks(3):                                      # future date
        records[i]["sample_date"] = "2027-03-15"
    for i in picks(5):                                      # dd/mm/yyyy text format
        d = date.fromisoformat(records[i]["sample_date"]) if records[i]["sample_date"][:4] not in ("1900", "2027") else None
        if d:
            records[i]["sample_date"] = d.strftime("%d/%m/%Y")

    # 4) Inconsistent text in unit_id
    for i in picks(10):
        if records[i]["unit_id"]:
            u = records[i]["unit_id"]
            records[i]["unit_id"] = rng.choice([u.lower(), f" {u} ", u.replace("-", "")])

    # 5) Duplicates (lab re-sends the same sample)
    dups = [json.loads(json.dumps(records[i])) for i in picks(12)]
    records.extend(dups)

    rng.shuffle(records)
    return records


def write_pages(records):
    for f in OUT_DIR.glob("*.json"):
        f.unlink()
    pages = math.ceil(len(records) / PAGE_SIZE)
    for p in range(1, pages + 1):
        chunk = records[(p - 1) * PAGE_SIZE: p * PAGE_SIZE]
        body = {
            "meta": {
                "api_version": "1.0",
                "lab": "Mock Tribology Lab Pty Ltd (simulated)",
                "page": p,
                "page_size": PAGE_SIZE,
                "total_pages": pages,
                "total_records": len(records),
            },
            "links": {
                "self": f"{BASE_URL}/page_{p}.json",
                "next": f"{BASE_URL}/page_{p + 1}.json" if p < pages else None,
            },
            "data": chunk,
        }
        (OUT_DIR / f"page_{p}.json").write_text(json.dumps(body, indent=2))
    return pages


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recs = inject_errors(generate_records())
    pages = write_pages(recs)
    print(f"Wrote {len(recs)} records across {pages} pages to {OUT_DIR}")
