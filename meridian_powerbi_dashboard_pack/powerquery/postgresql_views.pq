// Meridian Commerce Power BI - PostgreSQL view imports
//
// PART 1 documents the queries EXACTLY as they are in the dashboard (.pbix).
// PART 2 is an optional parameterized version for other machines.
//
// Do not hardcode passwords or secrets in this file. Power BI stores credentials
// separately (Data source settings); none are inside the queries.
//
// The PBIX applies NO "Changed Type" step: column types come straight from the
// PostgreSQL view and were checked (timestamps, numerics, integers, booleans all correct).

// ============================================================================
// PART 1 - AS SHIPPED IN THE PBIX (server and database are hard-coded)
// Query name in the PBIX -> source view
// ============================================================================

// Query name: Tickets            (fact table, one row per ticket)
let
    Source = PostgreSQL.Database("localhost:5432", "meridian_commerce"),
    #"Navigation 1" = Source{[Schema = "public", Item = "vw_ticket_analytics"]}[Data]
in
    #"Navigation 1"

// Query name: public vw_classification_metrics     (single row, disconnected)
let
    Source = PostgreSQL.Database("localhost:5432", "meridian_commerce"),
    #"Navigation 1" = Source{[Schema = "public", Item = "vw_classification_metrics"]}[Data]
in
    #"Navigation 1"

// Query name: public vw_rule_decision_metrics      (single row, disconnected)
let
    Source = PostgreSQL.Database("localhost:5432", "meridian_commerce"),
    #"Navigation 1" = Source{[Schema = "public", Item = "vw_rule_decision_metrics"]}[Data]
in
    #"Navigation 1"

// Query name: public vw_response_metrics           (single row, disconnected)
let
    Source = PostgreSQL.Database("localhost:5432", "meridian_commerce"),
    #"Navigation 1" = Source{[Schema = "public", Item = "vw_response_metrics"]}[Data]
in
    #"Navigation 1"

// Query name: public vw_operational_metrics        (single row, disconnected; feeds the
//                                                   Operational Performance KPI cards)
let
    Source = PostgreSQL.Database("localhost:5432", "meridian_commerce"),
    #"Navigation 1" = Source{[Schema = "public", Item = "vw_operational_metrics"]}[Data]
in
    #"Navigation 1"

// The Date table is a DAX calculated table (see dax/measures.dax), not a Power Query table.
// KPI_Measures is a one-column helper table that only hosts the measures.

// ============================================================================
// PART 2 - OPTIONAL: PARAMETERIZED VERSION
// Create two text parameters first: ServerName ("localhost:5432") and DatabaseName
// ("meridian_commerce"). Then replace the hard-coded strings with the parameters.
// ============================================================================

// Query name: Tickets
let
    Source = PostgreSQL.Database(ServerName, DatabaseName),
    public_vw_ticket_analytics = Source{[Schema = "public", Item = "vw_ticket_analytics"]}[Data]
in
    public_vw_ticket_analytics

// (Same pattern for the four *_metrics views.)

// Optional explicit typing (not needed today; useful if the source ever changes types).
// Only worth adding if a refresh starts showing wrong types:
//   Table.TransformColumnTypes(public_vw_ticket_analytics, {
//       {"ticket_id", Int64.Type}, {"created_at", type datetime},
//       {"first_response_at", type datetime}, {"resolved_at", type datetime},
//       {"classification_confidence", type number}, {"sentiment_score", type number},
//       {"order_total_amount", type number}, {"delivery_delay_days", Int64.Type},
//       {"first_response_minutes", type number}, {"resolution_hours", type number},
//       {"rule_decision_hours", type number}, {"response_generation_hours", type number},
//       {"final_priority_score", Int64.Type}})

// ============================================================================
// OPTIONAL: Date table in Power Query instead of DAX (the dashboard uses the DAX version).
// If you use this, relate Date[Date] to a date-only column of Tickets[created_at].
// ============================================================================

// Query name: Date
let
    StartDate = Date.From(List.Min(Tickets[created_at])),
    EndDate = Date.From(List.Max(Tickets[created_at])),
    DayCount = Duration.Days(EndDate - StartDate) + 1,
    Dates = List.Dates(StartDate, DayCount, #duration(1, 0, 0, 0)),
    TableFromList = Table.FromList(Dates, Splitter.SplitByNothing(), {"Date"}),
    #"Changed Type" = Table.TransformColumnTypes(TableFromList, {{"Date", type date}}),
    #"Inserted Year" = Table.AddColumn(#"Changed Type", "Year", each Date.Year([Date]), Int64.Type),
    #"Inserted Quarter" = Table.AddColumn(#"Inserted Year", "Quarter", each Date.QuarterOfYear([Date]), Int64.Type),
    #"Inserted Month" = Table.AddColumn(#"Inserted Quarter", "Month", each Date.Month([Date]), Int64.Type),
    #"Inserted Month Name" = Table.AddColumn(#"Inserted Month", "Month Name", each Date.MonthName([Date]), type text),
    #"Inserted Day" = Table.AddColumn(#"Inserted Month Name", "Day", each Date.Day([Date]), Int64.Type),
    #"Inserted Day Name" = Table.AddColumn(#"Inserted Day", "Day Name", each Date.DayOfWeekName([Date]), type text),
    #"Inserted Is Weekend" = Table.AddColumn(#"Inserted Day Name", "Is Weekend", each Date.DayOfWeek([Date], Day.Monday) >= 5, type logical)
in
    #"Inserted Is Weekend"
