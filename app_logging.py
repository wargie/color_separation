# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent / "Logs"
LOG_FILE = LOG_DIR / "app.log"


def setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not any(isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers):
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(file_handler)

    sys.excepthook = _log_unhandled_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = _log_thread_exception

    logging.getLogger(__name__).info("Logging initialized: %s", LOG_FILE)
    return LOG_FILE


def _log_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    logging.getLogger(__name__).critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
    logging.getLogger(__name__).critical(
        "Unhandled thread exception in %s",
        args.thread.name if args.thread else "unknown thread",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )

