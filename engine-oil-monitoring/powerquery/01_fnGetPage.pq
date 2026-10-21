// fnGetPage: calls one page of the lab API and returns the parsed JSON record.
//
// Why RelativePath: Power BI Service can only schedule-refresh Web.Contents calls whose
// base URL is static. Building the full URL with "&" works in Desktop but fails in the
// Service ("dynamic data source"). Keeping the base fixed and passing the page through
// RelativePath avoids that.
//
// For a real lab API, add authentication here, e.g.
//   Web.Contents(BaseUrl, [RelativePath = ..., Headers = [Accept = "application/json"],
//                          ApiKeyName = "api_key"])
// and enter the key in Power BI's data source credentials, never in the query text.

(PageNumber as number) as record =>
let
    BaseUrl  = "https://raw.githubusercontent.com/nhunguyen61/engine-oil-monitoring/main/",
    Response = Web.Contents(
        BaseUrl,
        [
            RelativePath   = "mock_api/v1/samples/page_" & Number.ToText(PageNumber) & ".json",
            Headers        = [Accept = "application/json"],
            ManualStatusHandling = {404, 429, 500}
        ]
    ),
    Status   = Value.Metadata(Response)[Response.Status],
    Result   = if Status = 200
               then Json.Document(Response)
               else error Error.Record("API error", "Page " & Number.ToText(PageNumber)
                                       & " returned HTTP " & Number.ToText(Status))
in
    Result
