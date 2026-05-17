from abc import ABC, abstractmethod
from typing import Optional


class BaseRunner(ABC):
    """Abstract base for owrap subcommand runners."""

    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    @abstractmethod
    def run(self, args) -> int:
        """Execute the runner's subcommand. Returns exit code."""
        ...

    def _get_server_url(self) -> Optional[str]:
        """Return the server URL from the manager, or None."""
        return self.manager.get_server_url()
