# Demo script (about 5 minutes)

Before recording: `make up`, `make dagster`, `make app`, and set `ANTHROPIC_API_KEY` in `.env`.

1. **The data (30 s).** Streamlit **Overview**. "Public NYC sanitation data: 600k 311
   requests, 36 years of tonnage, weather. Loaded daily with dlt, modeled in dbt,
   orchestrated by Dagster."
2. **The catalog is the brain (60 s).** In OpenMetadata, open `fct_monthly_tonnage`:
   - Tier 1, owner, Sanitation domain, the data product.
   - The `diversion_rate` column linked to its glossary term.
   - The lineage tab: *NYC Open Data API endpoint → raw → staging → marts*, every edge
     stamped with the Dagster job, down to column level.
   - The Data Quality tab: dbt tests with results.
3. **Ask a question (45 s).** **Ask the analyst**: "Which borough had the highest
   diversion rate last month?" Open *How I got this*: a certified metric from the dbt
   Semantic Layer, the generated SQL, and the cost.
4. **Break it (90 s).** **Chaos lab**, choose `unit_change_tonnage` ("latest month
   published in pounds"), then **Inject and run transforms**. In Dagster, the run fails:
   `assert_tonnage_no_sudden_scale_change` catches a ~2000× jump. The failure sensor
   launches `incident_triage`. In **Incidents**, the agent names
   `raw_dsny.monthly_tonnage.refusetonscollected` as the root cause (category
   `unit_change`), with evidence queries, blast radius (Tier 1 scorecard) and a fix.
   **Restore**.
5. **Agents propose, humans approve (60 s).** Run `make steward`, then open
   **Approvals**: proposed `PII.Sensitive` on `incident_address` / `latitude` /
   `longitude`, new column descriptions, and glossary links, each with evidence.
   Approve one and show it live in OpenMetadata.
6. **Proof (30 s).** **Agent evals**: incident root-cause accuracy over 8 faults, analyst
   golden-set accuracy, steward PII precision/recall vs OpenMetadata's auto-classifier,
   and cost per run.
