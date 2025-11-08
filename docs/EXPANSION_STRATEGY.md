# Expansion strategy for supply chain planning / IBP (open items only)

This document focuses on outstanding expansion themes, excluding areas that are already covered (AGG/DET reconciliation v2, run persistence, job management, visualization, CI).

Last updated: 2025-09-06

## Outstanding themes (highlights)
- **Authentication/authorization & tenancy**: OIDC/OAuth2, RBAC, tenant isolation, audit trails.
- **Demand forecasting and consensus**: statistical/ML plug-ins, training/evaluation/freezing, consensus workflows.
- **Optimization (OR)**: LP formulations for replenishment (MEIO approximation), transportation, and production; finite-capacity CP/heuristics.
- **Hierarchies and multi-axis aggregation**: product/location hierarchies, columnar DWH integration, rollup APIs.
- **External integrations**: connectors for ERP/WMS/MES/MDM/forecasting platforms, CDC/ETL pipelines, data quality.
- **SRE/Security**: row-level controls, PII protection, SLA/DR/observability, cost optimization.

## Simplified roadmap
- **R1 (short-term)**
  - Implement OIDC/RBAC for authentication and authorization.
  - Deliver forecasting plug-ins (ETS/ARIMA/Prophet) with a `/forecast` API for training, inference, and evaluation.
  - Provide an OR-layer skeleton abstracting PuLP / OR-Tools.
- **R2 (mid-term)**
  - Build PoCs for replenishment/transport/production LPs and connect them to KPI tracking.
  - Enable hierarchical and multi-axis aggregation with DWH connectivity.
  - Ship external connectors (MDM/ERP) and data-quality tooling.
- **R3 (long-term)**
  - Add finite-capacity scheduling (CP or heuristics).
  - Launch IBP KPIs, consensus workflows, and financial bridging.
  - Strengthen SRE/security (SLA/DR, cost management, observability).

## Success metrics (examples)
- **Functionality**: forecast MAPE, LP cost-improvement rates, IBP dashboard coverage.
- **Performance**: P95 runtime for representative cases, DWH integration latency.
- **Operations**: authorization error rate, SLO attainment, recovery time, data-quality scores.

---
Note: Completed items such as AGG/DET reconciliation and run persistence are documented in the README and related guides.
