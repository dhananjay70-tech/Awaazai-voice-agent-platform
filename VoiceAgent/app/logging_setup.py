"""Logging setup. Never log API keys, audio, transcripts or conversation text."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"

# Third-party libraries that log request/frame CONTENT at DEBUG. `websockets` logs every frame it sends and receives
# (including the handshake's "Authorization: Token <API key>" header and transcript JSON), so even LOG_LEVEL=DEBUG
# must never turn that on. They stay at WARNING whatever level the application uses.
NOISY_THIRD_PARTY_LOGGERS = ("websockets", "httpx", "httpcore")


def configure_logging(level: str = "INFO") -> None:
    # No force=True: if a host (uvicorn, pytest, ...) already installed handlers, keep them.
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger().setLevel(level)
    for name in NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
