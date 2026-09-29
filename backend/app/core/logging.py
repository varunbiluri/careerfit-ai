import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import get_settings


def setup_logging(level: str | None = None) -> None:
    settings = get_settings()
    log_level = (level or settings.log_level).upper()
    lvl = getattr(logging, log_level, logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(lvl)

    if not root.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    log_path = settings.log_file_path
    if not log_path:
        _quiet_noisy_loggers()
        return

    path = Path(log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.getLogger(__name__).warning("Could not create log directory for %s: %s", path, e)
        _quiet_noisy_loggers()
        return

    resolved = path.resolve()
    resolved_s = str(resolved)
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None):
            try:
                if Path(h.baseFilename).resolve() == resolved:
                    _quiet_noisy_loggers()
                    return
            except OSError:
                continue

    max_bytes = max(1, settings.log_file_max_mb) * 1024 * 1024
    fh = RotatingFileHandler(
        resolved_s,
        maxBytes=max_bytes,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    _quiet_noisy_loggers()


def _quiet_noisy_loggers() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
