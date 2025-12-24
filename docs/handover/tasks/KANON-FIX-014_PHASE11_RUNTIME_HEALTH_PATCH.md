# KANON-FIX-014 — Phase 11 — Runtime & Deploy Health Patch

## Kontext

- Sistem: Adnan.AI / Evolia OS
- Verzija: v1.0.6 (stable)
- ARCH_LOCK: True (dozvoljene samo PATCH promjene; nema arhitektonskih rezova)
- Release channel: `stable`
- Ovo je **formalizacija** runtime/deploy health promjena koje su već implementirane u kodu, da KANON bude usklađen sa stvarnim stanjem.

## Problem / Zašto je rađeno

Za produkcijski sistem koji radi preko API gateway-a, potrebno je imati:

1. Jasno razdvojen:
   - **liveness** signal (da li proces živi),
   - **readiness** signal (da li je sistem stvarno spreman da prima promet).
2. Determinističan **startup** koji:
   - inicijalizira sve core servise,
   - pokušava sync sa Notion (ali da taj dio nije fatalan za boot),
   - jasno označi kada je sistem READY.
3. Ispravno ponašanje `OPS_SAFE_MODE` feature-flaga:
   - da ne zavisi od implicitnih truthy/falsey stringova,
   - nego eksplicitno poštuje `"true"/"false"` semantiku iz ENV.
4. Health endpoint-e koje može koristiti:
   - lokalni operator (manualno provjeravanje),
   - CI/test skripte,
   - budući orchestrator (kontejner/orchestrator health probes).

Prije ovog patcha, ovo ponašanje nije bilo kompletno zaokruženo u jednom kanonskom gateway sloju sa lifespan modelom i čistim /health /ready semantikama.

## Scope (tačno šta je mijenjano)

### Modified files

- `gateway/gateway_server.py`

(Ovaj KANON-FIX pokriva isključivo runtime/deploy health patch u gateway sloju; ne mijenja širu arhitekturu niti druge servise.)

## Implementacija (šta je urađeno)

### 1) Lifespan startup umjesto klasičnog @startup

Uveden je **FastAPI lifespan** kontekst:

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    global _BOOT_READY, _BOOT_ERROR

    _BOOT_READY = False
    _BOOT_ERROR = None

    try:
        # Core bootstrap (fatal ako ovdje pukne)
        bootstrap_application()

        # Notion snapshot sync — nije fatalno za boot, samo warning
        try:
            from services.notion_service import get_notion_service

            notion_service = get_notion_service()
            await notion_service.sync_knowledge_snapshot()
        except Exception as exc:  # noqa: BLE001
            _BOOT_ERROR = f"notion_sync_failed: {exc}"
            logger.warning("Notion knowledge snapshot sync failed: %s", exc)

        _BOOT_READY = True
        logger.info("✅ System boot completed. READY.")
        yield
    finally:
        _BOOT_READY = False
        logger.info("🛑 System shutdown — boot_ready=False.")
