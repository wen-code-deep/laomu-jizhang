import logging
import sys
from enum import Enum

from jb_debugger_logging import DebuggerLogging, LOGGING_DISABLED


class DiagnosticsLevel(Enum):
    DISABLED = 0
    ERRORS = 1
    VERBOSE = 2
    DEBUG = 3

    def to_logging_level(self) -> int:
        if self == DiagnosticsLevel.DISABLED:
            return LOGGING_DISABLED
        if self == DiagnosticsLevel.ERRORS:
            return logging.ERROR
        if self == DiagnosticsLevel.VERBOSE:
            return logging.INFO
        if self == DiagnosticsLevel.DEBUG:
            return logging.DEBUG
        raise ValueError(f'Unexpected diagnostics level {self.name}:{self.value}')


class LLDBLoggingRender:
    class _RenderLoggerStdoutFormatter(logging.Formatter):
        def __init__(self, render_logger_root_prefix: str):
            self._render_logger_root_prefix = render_logger_root_prefix
            super().__init__("[%(levelname)s][%(name)s] %(message)s")

        def format(self, record: logging.LogRecord) -> str:
            # Remove 'render.' prefix from children messages
            record.name = record.name.removeprefix(self._render_logger_root_prefix)
            return super().format(record)

    @staticmethod
    def _create_render_stdout_handler(formatter: logging.Formatter) -> logging.StreamHandler:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        return stdout_handler

    @staticmethod
    def _create_render_logger(logger_name: str, handler: logging.StreamHandler) -> logging.Logger:
        logger = DebuggerLogging.create_logger(logger_name)
        logger.addHandler(handler)
        return logger

    _render_logger_name = "render"
    _render_logger_prefix = f"{_render_logger_name}."
    _stdout_handler = _create_render_stdout_handler(_RenderLoggerStdoutFormatter(_render_logger_prefix))
    _render_logger = _create_render_logger(_render_logger_name, _stdout_handler)

    @classmethod
    def update_render_diagnostic_level(cls, diagnostic_level: DiagnosticsLevel):
        logging_level = diagnostic_level.to_logging_level()
        cls._stdout_handler.setLevel(logging_level)
        min_level = LOGGING_DISABLED
        for handler in cls._render_logger.handlers:
            if handler.level < min_level:
                min_level = handler.level
        cls._render_logger.setLevel(min_level)
        cls._render_logger.disabled = min_level == LOGGING_DISABLED

    @classmethod
    def get_render_logger(cls):
        return cls._render_logger
