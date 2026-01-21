# ROUTE diff (ENABLE_EXTRA_ROUTERS off vs on)

- OFF dump: `C:/adnan-backend-v4/artifacts/extra_routers/routes_dump_off.json`
- ON dump: `C:/adnan-backend-v4/artifacts/extra_routers/routes_dump_on.json`

## Summary

- OFF routes (METHOD+PATH): 85
- ON routes (METHOD+PATH): 93
- NEW routes when ON: 8
- METHOD+PATH handler mismatches (OFF vs ON): 0

## New routes when ENABLE_EXTRA_ROUTERS=true

| Method | Path | Handler module | Handler name |
|---|---|---|---|
| POST | /api/adnan-ai/actions/ | routers.adnan_ai_action_router | ai_action_endpoint |
| GET | /api/adnan-ai/decision-engine | routers.adnan_ai_data_router | get_decision_engine |
| GET | /api/adnan-ai/identity | routers.adnan_ai_data_router | get_identity |
| GET | /api/adnan-ai/kernel | routers.adnan_ai_data_router | get_kernel |
| GET | /api/adnan-ai/mode | routers.adnan_ai_data_router | get_mode |
| GET | /api/adnan-ai/state | routers.adnan_ai_data_router | get_state |
| GET | /api/sop/get | routers.sop_query_router | get_sop |
| GET | /api/sop/list | routers.sop_query_router | list_sops |

## Collision check

- OK: 0 collisions (no shared METHOD+PATH changes handler between OFF and ON).
