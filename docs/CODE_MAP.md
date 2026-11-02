# Methods and code

| Method | Code | Input / output |
|---|---|---|
| Topology cuts | `src/ammonia_optimizer/superstructure.py` | superstructure.json -> candidates |
| Result schema | `src/ammonia_optimizer/schema.py` | candidates -> CSV/dictionary |
| Coupled feasibility | `src/ammonia_optimizer/feasibility.py` | conditions/thermo -> constraints |
| Physical result checks | `src/ammonia_optimizer/physics.py` | simulator results -> constraint report |
| COM lifecycle | `src/aspen_automation/session.py` | BKP copy -> independent session |
| Worker supervision | `reproduction/baseline/SOFC/18_Thermodynamic_Revision/campaign_controller.py` | job list -> bounded workers |
| Process coupling | same directory, `case_calculation.py` | settings + Aspen -> process state |
| Balance/utility accounting | same directory, `audits.py` | state -> residuals/net AC efficiency |
| SOFC model | `reproduction/baseline/SOFC/03_Model/` | SI inputs -> reduced stack model |

The legacy `aspen_gateway.py` uses optional py2aspen. The documented session
entry point uses pywin32; these adapters are not silently interchanged.
Final paper figure/table identifiers are not assigned until the manuscript and
its exact accepted result set are frozen.
