from services.state_service import StateService
from services.progress_service import ProgressService
from services.ai_command_service import AICommandService

class MasterEngine:
    def __init__(self):
        self.state = StateService()
        self.progress = ProgressService()
        self.ai = AICommandService()

    def status(self):
        return {'engine': 'master running'}

    def check_state(self):
        return {'state': self.state.status()}

    def check_progress(self):
        return {'progress': self.progress.compute()}

    def run_ai_command(self, payload: dict):
        return self.ai.process(payload)