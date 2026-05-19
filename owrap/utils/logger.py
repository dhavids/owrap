import logging
from pathlib import Path


def get_logger(name: str, log_path: str | Path | None = None, level: str = "INFO") -> logging.Logger:
    """Create a logger with an optional file handler.

    Args:
        name: Logger name.
        log_path: If given, attach a FileHandler writing to this path.
        level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    logger = logging.getLogger(name)
    level_val = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(level_val)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not logger.handlers:
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)

    return logger
