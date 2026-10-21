// RawSamples: pulls every page from the API and flattens the nested JSON into a table.
// Reads meta.total_pages from page 1, then requests pages 2..N.
// No cleaning happens here, so this query always shows exactly what the lab sent.

let
    FirstPage  = fnGetPage(1),
    TotalPages = FirstPage[meta][total_pages],
    OtherPages = List.Transform({2..TotalPages}, each fnGetPage(_)),
    AllPages   = {FirstPage} & OtherPages,
    AllRecords = List.Combine(List.Transform(AllPages, each _[data])),
    AsTable    = Table.FromRecords(AllRecords, null, MissingField.UseNull),

    // Nested "results" record -> one column per parameter.
    // MissingField.UseNull handles records where the lab left a field out entirely.
    Params = {"fe_ppm","cu_ppm","al_ppm","cr_ppm","pb_ppm","si_ppm","na_ppm","k_ppm",
              "water_ppm","visc_100c_cst","tbn_mgkoh_g","soot_pct"},
    ExpandResults = Table.ExpandRecordColumn(AsTable, "results", Params, Params),
    ExpandUnits   = Table.ExpandRecordColumn(ExpandResults, "units",
                        {"water","viscosity"}, {"water_unit","visc_unit"}),

    Typed = Table.TransformColumnTypes(ExpandUnits,
        {{"sample_id", type text}, {"unit_id", type text}, {"equipment_type", type text},
         {"engine_model", type text}, {"site", type text}, {"component", type text},
         {"oil_grade", type text}, {"sample_date", type text}, {"received_date", type date},
         {"oil_hours", Int64.Type}, {"water_unit", type text}, {"visc_unit", type text}}
        & List.Transform(Params, each {_, type number}))
in
    Typed
