// Samples: cleaned and validated sample table (one row per valid sample).
// Same rules as python/pipeline.py, so the two can be reconciled row for row.

let
    Source = RawSamples,
    Today  = Date.From(DateTime.LocalNow()),

    // 1. Exact duplicates (lab re-sent a sample), then any remaining repeated sample_id
    NoExactDups = Table.Distinct(Source),
    NoIdDups    = Table.Distinct(NoExactDups, {"sample_id"}),

    // 2. unit_id: trim, upper-case, restore the hyphen (ht103 -> HT-103)
    CleanUnit = Table.TransformColumns(NoIdDups, {{"unit_id", each
        if _ = null then null else
        let u = Text.Upper(Text.Trim(_))
        in  if Text.Contains(u, "-") then u
            else Text.Start(u, 2) & "-" & Text.Middle(u, 2), type text}}),

    // 3. sample_date arrives as text in two formats: yyyy-mm-dd and dd/mm/yyyy
    ParsedDate = Table.AddColumn(CleanUnit, "sample_date_parsed", each
        let t = [sample_date]
        in  if t = null then null
            else if Text.Contains(t, "/") then try Date.FromText(t, [Format = "dd/MM/yyyy"]) otherwise null
            else try Date.FromText(t, [Format = "yyyy-MM-dd"]) otherwise null, type date),

    // 4. Invalid dates: missing, placeholder (< 2000), future, or after received_date.
    //    Imputed as received_date - 3 days (typical transit 2-6 days) and flagged.
    DateFlag = Table.AddColumn(ParsedDate, "sample_date_issue", each
        let d = [sample_date_parsed]
        in  if d = null then "unparseable or missing"
            else if Date.Year(d) < 2000 then "placeholder date"
            else if d > Today then "date in the future"
            else if [received_date] <> null and d > [received_date] then "after received_date"
            else null, type text),
    FixedDate = Table.AddColumn(DateFlag, "sample_date_final", each
        if [sample_date_issue] = null then [sample_date_parsed]
        else Date.AddDays([received_date], -3), type date),
    ImputedFlag = Table.AddColumn(FixedDate, "sample_date_imputed",
        each [sample_date_issue] <> null, type logical),

    // 5. Units of measure
    //    Water in % -> ppm (x10,000).
    //    Viscosity at 40C cannot be converted to 100C without the viscosity index -> blank it.
    WaterPpm = Table.ReplaceValue(ImputedFlag,
        each [water_ppm], each if [water_unit] = "%" then [water_ppm] * 10000 else [water_ppm],
        Replacer.ReplaceValue, {"water_ppm"}),
    Visc100 = Table.ReplaceValue(WaterPpm,
        each [visc_100c_cst], each if [visc_unit] = "cSt@40C" then null else [visc_100c_cst],
        Replacer.ReplaceValue, {"visc_100c_cst"}),

    // 6. Records without unit_id cannot be linked to equipment -> excluded here,
    //    kept visible in the Quarantine query.
    HasUnit = Table.SelectRows(Visc100, each [unit_id] <> null),

    Tidy = Table.RemoveColumns(HasUnit, {"sample_date", "sample_date_parsed"}),
    Renamed = Table.RenameColumns(Tidy, {{"sample_date_final", "sample_date"}}),
    Final = Table.TransformColumnTypes(Renamed, {{"water_ppm", type number}, {"visc_100c_cst", type number}})
in
    Final
