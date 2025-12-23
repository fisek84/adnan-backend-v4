# services/decision_engine/operational_orchestration.py


class OperationalOrchestrationEngine:
    def __init__(self):
        pass

    def _required_fields_ok(self, command: dict) -> bool:
        payload = command.get("payload", {})
        entry = payload.get("entry", {}) or {}
        db_id = payload.get("database_id")

        if not db_id:
            return False

        name = str(entry.get("Name", "")).strip()
        status = str(entry.get("Status", "")).strip()
        priority = str(entry.get("Priority", "")).strip()

        if not name or not status or not priority:
            return False

        return True

    def _prepare_notion_payload(self, command: dict) -> dict:
        payload = command.get("payload", {}) or {}
        entry = payload.get("entry", {}) or {}

        relations = {
            "related_goals": command.get("related_goals", []),
            "related_projects": command.get("related_projects", []),
            "cross_related_goals": command.get("cross_related_goals", []),
            "cross_related_projects": command.get("cross_related_projects", []),
        }

        return {
            "type": "notion_command",
            "version": "1.0",
            "command": command.get("command"),
            "database_id": payload.get("database_id"),
            "entry": entry,
            "relations": relations,
            "options": {"upsert": False, "dry_run": False},
        }

    def _prepare_metadata(self, command: dict) -> dict:
        error_engine = command.get("error_engine", {}) or {}
        errors = error_engine.get("errors", []) or []

        execution_validated = len(errors) == 0
        required_fields_confirmed = self._required_fields_ok(command)

        return {
            "execution_validated": execution_validated,
            "required_fields_confirmed": required_fields_confirmed,
            "trust": command.get("trust", {}),
            "score": command.get("score"),
            "behavioral_filters": command.get("behavioral_filters", {}),
            "audit": command.get("audit", {}),
            "static_memory": command.get("static_memory_influence", {}),
            "dynamic_memory": command.get("dynamic_memory", {}),
            "contextual_links": command.get("contextual_links", {}),
            "cross_links": {
                "goals": command.get("cross_related_goals", []),
                "projects": command.get("cross_related_projects", []),
            },
            "expansion": command.get("expansion", {}),
            "autocorrect": command.get("autocorrect", {}),
            "sop_detected": command.get("sop_detected", None),
            "error_engine": error_engine,
        }

    def orchestrate(self, command: dict) -> dict:
        notion_part = self._prepare_notion_payload(command)
        metadata_part = self._prepare_metadata(command)

        notion_ready = (
            metadata_part["execution_validated"]
            and metadata_part["required_fields_confirmed"]
        )

        return {
            "notion_ready": notion_ready,
            "notion_command": notion_part,
            "metadata": metadata_part,
        }
