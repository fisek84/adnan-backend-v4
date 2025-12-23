from datetime import datetime, timezone


class TrashService:
    """
    Lightweight cleanup helper.
    Can be extended later to clear cache, temp data, or orphaned objects.
    """

    def __init__(self):
        self.last_cleared = None
        self.clear_count = 0

    def clear(self, description: str = "general cleanup") -> dict:
        """
        Performs a cleanup operation and returns metadata.
        In the future, attach real cleanup logic here.
        """
        now = datetime.now(timezone.utc).isoformat()

        self.last_cleared = now
        self.clear_count += 1

        return {
            "status": "success",
            "action": "trash_cleared",
            "description": description,
            "timestamp": now,
            "total_operations": self.clear_count,
        }

    def reset(self) -> dict:
        """
        Resets internal counters and state.
        """
        self.last_cleared = None
        self.clear_count = 0

        return {
            "status": "reset",
            "message": "TrashService internal state reset",
        }

    def stats(self) -> dict:
        """
        Returns diagnostic information about cleanup operations.
        """
        return {
            "last_cleared": self.last_cleared,
            "total_operations": self.clear_count,
        }
