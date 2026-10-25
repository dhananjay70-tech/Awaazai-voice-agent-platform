"""Logging setup. Never log passwords, tokens or other secrets."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    # No force=True: if a host (uvicorn, pytest, ...) already installed handlers, keep them.
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger().setLevel(level)
    # Keep SQLAlchemy and HTTP client internals quiet unless debugging.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
