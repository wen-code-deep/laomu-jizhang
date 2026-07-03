from __future__ import annotations

import logging
import os

LOGGING_DISABLED = logging.CRITICAL + 1

LOG_MESSAGE_SEPARATOR = "-" * 50


def _create_debug_log_file_handler() -> logging.FileHandler | None:
    log_file_path = os.environ.get('JB_PYTHON_DEBUG_LOG_PATH', None)
    if not log_file_path:
        return None

    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s.%(msecs)d %(levelname)s - #%(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter)
    return file_handler


class DebuggerLogging:
    _debug_log_file_handler: logging.FileHandler | None = _create_debug_log_file_handler()

    @classmethod
    def create_logger(cls, name: str) -> logging.Logger:
        new_logger = logging.getLogger(name)
        new_logger.propagate = False
        if cls._debug_log_file_handler is not None:
            new_logger.addHandler(cls._debug_log_file_handler)
            new_logger.setLevel(cls._debug_log_file_handler.level)
        else:
            new_logger.disabled = True
            new_logger.setLevel(LOGGING_DISABLED)
        return new_logger
