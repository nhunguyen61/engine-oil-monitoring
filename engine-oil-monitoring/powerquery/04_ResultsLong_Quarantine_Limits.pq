// ===== ResultsLong =====
// One row per sample x parameter. This shape makes limits, trend charts and
// anomaly checks one generic calculation instead of 12 copies.
let
    Source   = Samples,
    Keep     = Table.SelectColumns(Source, {"sample_id","unit_id","equipment_type","site",
                 "sample_date","oil_hours","fe_ppm","cu_ppm","al_ppm","cr_ppm","pb_ppm",
                 "si_ppm","na_ppm","k_ppm","water_ppm","visc_100c_cst","tbn_mgkoh_g","soot_pct"}),
    Unpivot  = Table.UnpivotOtherColumns(Keep,
                 {"sample_id","unit_id","equipment_type","site","sample_date","oil_hours"},
                 "parameter", "value"),
    // Unpivot drops nulls automatically, so missing results are not treated as zero.
    Typed    = Table.TransformColumnTypes(Unpivot, {{"value", type number}})
in
    Typed


// ===== Quarantine =====
// Records excluded from analysis, kept so nothing disappears silently.
let
    Source = RawSamples,
    NoUnit = Table.SelectRows(Source, each [unit_id] = null),
    Reason = Table.AddColumn(NoUnit, "reason", each "missing unit_id", type text)
in
    Reason


// ===== Limits =====
// Indicative limits. Replace with OEM / site limits when available.
let
    Source  = Csv.Document(Web.Contents(
                "https://raw.githubusercontent.com/nhunguyen61/engine-oil-monitoring/main/",
                [RelativePath = "reference/limits.csv"]),
              [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed   = Table.TransformColumnTypes(Headers,
                {{"caution", type number}, {"critical", type number}})
in
    Typed
