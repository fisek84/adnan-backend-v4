import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set

from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_service import discover_notion_db_registry_from_env


class NotionSyncService:
    # Warn-once guard for env var conflicts (avoid noisy logs during repeated refreshes)
    _ENV_DB_REGISTRY_CONFLICT_WARNED: Set[str] = set()

    def __init__(
        self,
        notion_service,
        goals_service,
        tasks_service,
        projects_service,
        goals_db_id,
        tasks_db_id,
        projects_db_id,
    ):
        self.notion = notion_service
        self.goals = goals_service
        self.tasks = tasks_service
        self.projects = projects_service

        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        self._delay = 0.25

        # Debounce task holders
        self._project_sync_task = None
        self._goal_sync_task = None
        self._task_sync_task = None

        # Logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # Last refresh diagnostics (used by refresh_snapshot read-only directive).
        # Must never include secrets.
        self.last_refresh_ok: Optional[bool] = None
        self.last_refresh_errors: List[Any] = []
        self.last_refresh_meta: Dict[str, Any] = {}

    # ------------------------------------------------------
    # DB REGISTRY (ENV)
    # ------------------------------------------------------
    @staticmethod
    def _discover_env_db_registry() -> List[Dict[str, str]]:
        """Discover all configured Notion databases from environment.

        SSOT:
        - Prefer `NOTION_<KEY>_DB_ID` (canonical)
        - Support legacy alias `NOTION_<KEY>_DATABASE_ID` only as fallback

        If both are set and differ, emit a WARNING once per key
        with both values and the chosen (canonical) value.

        Returns list entries:
          {
            "env_name": str,
            "db_key": str,
            "db_id": str,
            "logical_name": str,
            "legacy_alias": "true"|"false",
            "source": "DB_ID"|"DATABASE_ID"|"OTHER",
          }
        """

        logger = logging.getLogger(__name__)
        db_ids, meta, _warnings = discover_notion_db_registry_from_env()

        # Stable ordering: prioritize core keys first, then alpha by key.
        core_keys = ["tasks", "projects", "goals"]
        all_keys = sorted(k for k in db_ids.keys() if isinstance(k, str) and k.strip())
        ordered_keys = core_keys + [k for k in all_keys if k not in set(core_keys)]

        out: List[Dict[str, str]] = []
        for db_key in ordered_keys:
            db_id = (db_ids.get(db_key) or "").strip()
            if not db_id:
                continue
            ent = meta.get(db_key) if isinstance(meta, dict) else None
            env_name = ent.get("env_name") if isinstance(ent, dict) else None
            legacy_alias = (
                bool(ent.get("legacy_alias")) if isinstance(ent, dict) else False
            )

            # Conflict guardrails: warn once per logical key when both vars exist and differ.
            logical = db_key.upper()
            canonical_raw = (os.getenv(f"NOTION_{logical}_DB_ID") or "").strip()
            legacy_raw = (os.getenv(f"NOTION_{logical}_DATABASE_ID") or "").strip()
            if canonical_raw and legacy_raw and canonical_raw != legacy_raw:
                if logical not in NotionSyncService._ENV_DB_REGISTRY_CONFLICT_WARNED:
                    NotionSyncService._ENV_DB_REGISTRY_CONFLICT_WARNED.add(logical)
                    logger.warning(
                        "notion_env_db_registry_conflict key=%s db_id=%s database_id=%s chosen=%s chosen_env=%s",
                        logical,
                        canonical_raw,
                        legacy_raw,
                        canonical_raw,
                        f"NOTION_{logical}_DB_ID",
                    )

            source = "OTHER"
            if isinstance(env_name, str):
                if env_name.endswith("_DB_ID"):
                    source = "DB_ID"
                elif env_name.endswith("_DATABASE_ID"):
                    source = "DATABASE_ID"

            out.append(
                {
                    "env_name": env_name or "",
                    "db_key": db_key,
                    "db_id": db_id,
                    "logical_name": logical,
                    "legacy_alias": "true" if legacy_alias else "false",
                    "source": source,
                }
            )

        return out

    # ------------------------------------------------------
    # INTERNAL DEBOUNCE WRAPPER
    # ------------------------------------------------------
    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------
    # PROJECT SYNC DEBOUNCE
    # ------------------------------------------------------
    async def debounce_projects_sync(self):
        loop = asyncio.get_running_loop()

        if self._project_sync_task and not self._project_sync_task.done():
            self._project_sync_task.cancel()

        self._project_sync_task = loop.create_task(
            self._debounce(self.sync_projects_up)
        )

    # ------------------------------------------------------
    # GOALS SYNC DEBOUNCE
    # ------------------------------------------------------
    async def debounce_goals_sync(self):
        loop = asyncio.get_running_loop()

        if self._goal_sync_task and not self._goal_sync_task.done():
            self._goal_sync_task.cancel()

        self._goal_sync_task = loop.create_task(self._debounce(self.sync_goals_up))

    # ------------------------------------------------------
    # TASKS SYNC DEBOUNCE
    # ------------------------------------------------------
    async def debounce_tasks_sync(self):
        loop = asyncio.get_running_loop()

        if self._task_sync_task and not self._task_sync_task.done():
            self._task_sync_task.cancel()

        self._task_sync_task = loop.create_task(self._debounce(self.sync_tasks_up))

    # ------------------------------------------------------
    # SYNC METHODS (REQUIRED BY ROUTERS)
    # ------------------------------------------------------
    async def sync_tasks_up(self):
        self.logger.info("Sync tasks → Notion START")
        return True

    async def sync_goals_up(self):
        self.logger.info("Sync goals → Notion START")
        return True

    async def sync_projects_up(self):
        self.logger.info("Sync projects → Notion START")
        return True

    async def sync_all_up(self):
        """
        Required by /sync/all/up router.
        Combines all three sync operations.
        """
        self.logger.info("Sync ALL → Notion (goals + tasks + projects)")
        await self.sync_goals_up()
        await self.sync_tasks_up()
        await self.sync_projects_up()
        return True

    # ------------------------------------------------------
    # LOAD PROJECTS FROM NOTION → BACKEND (REQUIRED BY main.py)
    # ------------------------------------------------------
    async def load_projects_into_backend(self):
        self.logger.info("📥 Loading projects from Notion into backend...")

        response = await self.notion.query_database(self.projects_db_id)

        if not response.get("ok"):
            self.logger.error("Failed to load projects from Notion")
            return

        pages = response["data"]["results"]

        for page in pages:
            mapped = self.map_project_page(page)
            if not mapped:
                continue

            project_id = mapped["id"]

            # If backend already has this project → update tasks
            if project_id in self.projects.projects:
                self.projects.projects[project_id].tasks = mapped["tasks"]
                continue

            # Otherwise create new project backend-side
            self.projects.create_project(
                data=self.projects.to_create_model(mapped),
                forced_id=project_id,
                notion_id=mapped["notion_id"],
            )

        self.logger.info(f"📁 Loaded {len(pages)} projects from Notion → backend OK")

    # ------------------------------------------------------
    # MAP NOTION PROJECT PAGE → PYTHON STRUCTURE
    # ------------------------------------------------------
    def map_project_page(self, page):
        props = page.get("properties", {})

        def safe(name, kind):
            prop = props.get(name)
            if not prop:
                return None

            try:
                if kind == "title":
                    return prop["title"][0]["plain_text"] if prop["title"] else ""
                if kind == "text":
                    return (
                        prop["rich_text"][0]["plain_text"] if prop["rich_text"] else ""
                    )
                if kind == "select":
                    return prop["select"]["name"] if prop["select"] else None
                if kind == "date":
                    return prop["date"]["start"] if prop["date"] else None
                if kind == "relation":
                    rel = prop.get("relation") or []
                    return [r["id"].replace("-", "") for r in rel]
            except Exception:
                return None

            return None

        title = safe("Name", "title") or safe("Project Name", "title")
        if not title:
            return None

        return {
            "id": page["id"].replace("-", ""),
            "notion_id": page["id"],
            "title": title,
            "description": safe("Description", "text"),
            "status": safe("Status", "select") or "Active",
            "category": safe("Category", "select"),
            "priority": safe("Priority", "select"),
            "start_date": safe("Start Date", "date"),
            "deadline": safe("Target Deadline", "date"),
            "project_type": safe("Project Type", "select"),
            "summary": safe("Summary", "text"),
            "next_step": safe("Next Step", "text"),
            "primary_goal_id": (
                safe("Primary Goal", "relation")[0]
                if safe("Primary Goal", "relation")
                else None
            ),
            "parent_id": (
                safe("Parent Project", "relation")[0]
                if safe("Parent Project", "relation")
                else None
            ),
            "agents": safe("Agent Exchange DB", "relation") or [],
            "tasks": safe("Tasks DB", "relation") or [],
            "handled_by": safe("Handled By", "text"),
            "progress": 0,
        }

    # ------------------------------------------------------
    # FAZA 1 — READ-ONLY KNOWLEDGE SNAPSHOT
    # ------------------------------------------------------
    async def sync_knowledge_snapshot(self) -> bool:
        """
        Notion → KnowledgeSnapshotService

        - Read-only
        - MUST NOT raise (best-effort)
        """
        self.logger.info("🧠 Syncing Notion knowledge snapshot (ALL configured DBs)...")

        # Reset per-call diagnostics.
        self.last_refresh_ok = None
        self.last_refresh_errors = []
        self.last_refresh_meta = {}

        registry = self._discover_env_db_registry()
        db_keys = [r.get("db_key") for r in registry if isinstance(r, dict)]
        db_keys = [k for k in db_keys if isinstance(k, str) and k.strip()]

        t0 = time.monotonic()
        try:
            snapshot = await self.notion.build_knowledge_snapshot(db_keys=db_keys)
        except Exception as exc:
            self.logger.exception(
                "Knowledge snapshot sync failed (best-effort): %s", exc
            )

            self.last_refresh_ok = False
            self.last_refresh_errors = [
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            ]
            self.last_refresh_meta = {
                "ok": False,
                "error": str(exc),
                "db_registry": registry,
                "refresh_duration_ms": int(round((time.monotonic() - t0) * 1000.0)),
            }
            return False

        if not snapshot or not isinstance(snapshot, dict):
            self.logger.warning("⚠️ Knowledge snapshot empty or failed")

            self.last_refresh_ok = False
            self.last_refresh_errors = ["empty_snapshot"]
            self.last_refresh_meta = {
                "ok": False,
                "error": "empty_snapshot",
                "db_registry": registry,
                "refresh_duration_ms": int(round((time.monotonic() - t0) * 1000.0)),
            }
            return False

        # Attach registry for debugging/observability (no secrets).
        try:
            meta = (
                snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
            )
            meta["db_registry"] = registry
            meta["refresh_duration_ms"] = int(round((time.monotonic() - t0) * 1000.0))
            snapshot["meta"] = meta
        except Exception:
            pass

        # Determine success strictly from meta.ok + meta.errors.
        try:
            meta_out = (
                snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
            )
            ok_meta = bool(meta_out.get("ok") is True)
            errors_out = (
                meta_out.get("errors")
                if isinstance(meta_out.get("errors"), list)
                else []
            )
            ok = bool(ok_meta and not errors_out)
        except Exception:
            ok = False
            meta_out = {}
            errors_out = []

        self.last_refresh_ok = bool(ok)
        self.last_refresh_errors = (
            list(errors_out) if isinstance(errors_out, list) else []
        )
        self.last_refresh_meta = dict(meta_out) if isinstance(meta_out, dict) else {}

        # Structured logs per DB
        try:
            meta0 = (
                snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
            )
            stats = (
                meta0.get("db_stats") if isinstance(meta0.get("db_stats"), dict) else {}
            )
            succeeded = 0
            failed = 0
            for r in registry:
                db_key = r.get("db_key")
                st = stats.get(db_key) if isinstance(db_key, str) else None
                if not isinstance(st, dict):
                    continue
                ok_db = bool(st.get("ok") is True)
                if ok_db:
                    succeeded += 1
                    self.logger.info(
                        "snapshot_refresh_db_ok key=%s env=%s source=%s db_id=%s count=%s duration_ms=%s",
                        r.get("db_key"),
                        r.get("env_name"),
                        r.get("source"),
                        r.get("db_id"),
                        st.get("count"),
                        st.get("duration_ms"),
                    )
                else:
                    failed += 1
                    self.logger.warning(
                        "snapshot_refresh_db_fail key=%s env=%s source=%s db_id=%s error=%s duration_ms=%s",
                        r.get("db_key"),
                        r.get("env_name"),
                        r.get("source"),
                        r.get("db_id"),
                        st.get("error"),
                        st.get("duration_ms"),
                    )

            self.logger.info(
                "snapshot_refresh_summary total_dbs=%s succeeded=%s failed=%s duration_ms=%s",
                len(registry),
                succeeded,
                failed,
                int(round((time.monotonic() - t0) * 1000.0)),
            )
        except Exception:
            pass

        # STRICT: do NOT overwrite SSOT snapshot on refresh failure.
        if not ok:
            self.logger.warning(
                "⚠️ Knowledge snapshot refresh failed (no overwrite). errors=%s",
                len(self.last_refresh_errors)
                if isinstance(self.last_refresh_errors, list)
                else 0,
            )
            return False

        try:
            KnowledgeSnapshotService.update_snapshot(snapshot)
        except Exception as exc:
            self.logger.exception(
                "KnowledgeSnapshotService.update_snapshot failed: %s", exc
            )
            self.last_refresh_ok = False
            self.last_refresh_errors = [
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            ]
            return False

        self.logger.info("✅ Knowledge snapshot synced")
        return True
