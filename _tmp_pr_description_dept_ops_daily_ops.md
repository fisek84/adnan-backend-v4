Title:
- Dept Ops: Daily Ops Brief + deterministic read_only.query ops modes (no new tools)

Summary:
- `read_only.query` dobija 3 deterministička ops moda: `ops.daily_brief`, `ops.snapshot_health`, `ops.kpi_weekly_summary_preview` (lokalni izvori, stabilan output shape).
- Dodani ops SSOT job template-i `JT-OPS-02` i `JT-OPS-03` (samo `read_only.query`).
- `dept_ops` output je standardizovan na “Daily Ops Brief” i uvijek uključuje konkretne Notion proposals (`create_task`, `create_page`) kao proposal-only bundle.
- `JobRunner` metadata podržava opcionalni passthrough `emit_handoff_log` (default ostaje `False`).
- Dodani primjer inputs fajlovi za JT-OPS-02/03 + kratka runbook napomena o notifikaciji i planned-tool blockingu.

Non-goals / Explicitly NOT changed:
- Core loop nije mijenjan (AgentRouterService, ExecutionOrchestrator flow, approval state machine).
- Nema novih agenata, nema novih tool IDs, nema eksternal integracija.
- Planned tools ostaju neizvršivi.

Audit & Proof (file:line):
- Dept Ops je restricted na `read_only.query` only (no `analysis.run`): [config/agents.json](config/agents.json#L212-L224)
- Planned/non-MVP tools su hard-blocked sa `reason="tool_not_executable"`: [services/execution_orchestrator.py](services/execution_orchestrator.py#L564-L612)
- Ops job template-i postoje i koriste samo `read_only.query` (JT-OPS-02/03 dodani): [config/job_templates.json](config/job_templates.json#L55-L110)
- `read_only.query` ops modovi su deterministički + local-only: [services/tool_runtime_executor.py](services/tool_runtime_executor.py#L85-L235)
- `dept_ops` generiše “Daily Ops Brief” + proposal-only Notion komande (`dry_run=True`, `requires_approval=True`): [services/department_agents.py](services/department_agents.py#L150-L223) i [services/department_agents.py](services/department_agents.py#L273-L336)
- `emit_handoff_log` passthrough u `JobRunner` metadata: [services/job_runner.py](services/job_runner.py#L240-L270)

Behavior / UX:
- CEO dobije tekst u standardnom dept formatu (4 sekcije), gdje “Recommendation” sadrži “Daily Ops Brief” header i stabilan brief skeleton; “Proposed Actions” sadrži proposal bundle.
- Proposal bundle za ops uvijek uključuje Notion proposals (`create_task`, `create_page`) sa `dry_run=True` i `requires_approval=True` (nema auto-izvršavanja).
- Nijedan Notion write se ne izvršava bez `approval_id`; `dept_ops` je proposal-only.
- “notification” znači: chat output (brief + proposals), plus opcionalno handoff:* artefakt (task/page) kada `emit_handoff_log=True` može proći do postojećeg orchestrator hook-a.

How to run:
- Example inputs files (repo):
  - `.\docs\examples\inputs_ops_daily_brief.json`
  - `.\docs\examples\inputs_ops_snapshot_health.json`

- JT-OPS-02 (start/resume):

  Start (kreira approvals preko `/api/execute/raw`):

  python scripts\jobrunner_cli.py start --template JT-OPS-02 --job-id ops_daily_001 --initiator ceo --inputs-json .\docs\examples\inputs_ops_daily_brief.json

  Resume (approve + execute preko `/api/ai-ops/approval/approve`):

  python scripts\jobrunner_cli.py resume --job-id ops_daily_001 --initiator ceo --approvals-json .\_job_ops_daily_001_pending_approvals.json

- JT-OPS-03 (start/resume):

  Start:

  python scripts\jobrunner_cli.py start --template JT-OPS-03 --job-id ops_snap_001 --initiator ceo --inputs-json .\docs\examples\inputs_ops_snapshot_health.json

  Resume:

  python scripts\jobrunner_cli.py resume --job-id ops_snap_001 --initiator ceo --approvals-json .\_job_ops_snap_001_pending_approvals.json

- **Napomena: `emit_handoff_log` je trenutno CLI-inert dok se CLI payload ne proširi da forward-uje `emit_handoff_log` u `/api/execute/raw` `metadata`.** (Passthrough postoji u in-process `JobRunner` putanji: [services/job_runner.py](services/job_runner.py#L240-L270))

Safety / Governance:
- `dept_ops` može samo `read_only.query` (SSOT allowlist). Proof: [config/agents.json](config/agents.json#L212-L224)
- Proposed Notion actions su uvijek `dry_run=True` + `requires_approval=True` (proposal-only contract). Proof: [services/department_agents.py](services/department_agents.py#L150-L223)
- ExecutionOrchestrator blokira non-MVP tools kao `tool_not_executable`. Proof: [services/execution_orchestrator.py](services/execution_orchestrator.py#L564-L612)

Tests:
- Dodano:
  - [tests/test_read_only_query_ops_modes.py](tests/test_read_only_query_ops_modes.py#L1-L90)
  - [tests/test_dept_ops_ssot_restrictions.py](tests/test_dept_ops_ssot_restrictions.py#L1-L20)
- Rezultati:
  - `pytest -q`: `454 passed, 3 skipped`
  - `pre-commit run --all-files`: ruff (lint) PASS, ruff (format) PASS, mypy (local) PASS

Diff artifact:
- Workspace (lokalno): `_tmp_git_diff_dept_ops_daily_ops.txt` (gitignored zbog `_tmp*` pravila na Windows-u).
- U repou (za review): `docs/pr/dept-ops-daily-ops/git_diff_dept_ops_daily_ops.txt`

Mini map (file → intent):
- `services/tool_runtime_executor.py` → implementira determinističke `read_only.query` ops modove (daily brief / snapshot health / KPI weekly preview).
- `config/job_templates.json` → dodaje `JT-OPS-02` i `JT-OPS-03` (ops templates na `read_only.query`).
- `services/department_agents.py` → standardizuje `dept_ops` “Daily Ops Brief” + dodaje default proposal bundle (Notion proposals, proposal-only).
- `services/job_runner.py` → passthrough `emit_handoff_log` u step metadata (bez mijenjanja core loop-a).
- `tests/test_read_only_query_ops_modes.py` → testira determinističke output-e za ops modove.
- `tests/test_dept_ops_ssot_restrictions.py` → testira SSOT allowlist restrikciju za `dept_ops`.
- `docs/examples/inputs_ops_daily_brief.json` → primjer inputs za `query=ops.daily_brief`.
- `docs/examples/inputs_ops_snapshot_health.json` → primjer inputs za `query=ops.snapshot_health`.
- `README_RUNBOOK_OFL.md` → definiše “notifikaciju”, napominje CLI inertnost za `emit_handoff_log`, i opisuje planned-tool blocking.
