# services/decision_engine/test_execution_engine.py
#
# NOTE:
# This file lives under `services/` but its historical name matches pytest's
# default discovery patterns (test_*.py).
#
# This class is a small helper/harness, not an actual pytest test case.
# To avoid PytestCollectionWarning (and keep CI output clean), the class name
# must not match pytest's test-class pattern.


class ExecutionEngineHarness:
    def __init__(self, decision_service):
        self.svc = decision_service

    def _run_single(self, text: str) -> dict:
        try:
            result = self.svc.process_ceo_instruction(text)
            return {"input": text, "success": True, "output": result}
        except Exception as e:
            return {"input": text, "success": False, "error": str(e)}

    def run_batch(self, tests: list) -> dict:
        results = []
        for t in tests:
            results.append(self._run_single(t))

        passed = sum(1 for r in results if r["success"])
        failed = len(results) - passed

        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
