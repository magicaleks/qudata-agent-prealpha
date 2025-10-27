import sys
from functools import lru_cache
from logging import FileHandler, Formatter, StreamHandler, getLogger
from typing import Optional


class XLogger:

    def __init__(self, service_name: str) -> None:
        self._service_name = service_name
        self._logger = getLogger(service_name)
        self._setting()

    def _setting(self) -> None:
        self._logger.setLevel("DEBUG")
        self._logger.handlers.clear()

        filename = "logs.txt"
        file_handler = FileHandler(filename=filename, encoding="utf-8")
        console_handler = StreamHandler(stream=sys.stdout)
        
        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

        formatter = Formatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        for handler in self._logger.handlers:
            handler.setFormatter(formatter)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(
        self, message: str, exc: Optional[Exception] = None, exc_info: bool = True
    ) -> None:
        if exc:
            self._logger.error(message, exc_info=exc)
        else:
            self._logger.error(message, exc_info=exc_info)

    def critical(
        self,
        message: str,
        exc: Optional[Exception] = None,
        exc_info: bool = True,
    ):
        self._logger.critical(message, exc_info=exc_info)


@lru_cache
def get_logger(service_name: str) -> XLogger:
    return XLogger(service_name)
