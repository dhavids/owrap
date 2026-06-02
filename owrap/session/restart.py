from ..base import BaseRunner
from .stop import StopRunner
from .start import StartRunner


class RestartRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None, research=None, force=False, session_id=None):
        if self.logger:
            self.logger.info("restart initiated research=%s force=%s session_id=%s", research or "none", force, session_id or "none")
        StopRunner(self.manager, self.logger).run(no_exit=True, force=force, target=session_id)
        StartRunner(self.manager, self.logger, allow_all=self.allow_all).run(
            shell_pid=shell_pid, session_file=session_file, research=research, session_id=session_id)
