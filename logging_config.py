"""Application-wide logging configuration."""

import logging
import sys
import time


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging() -> None:
    """Route Python and dependency logs through one timestamped stderr handler."""
    root_logger = logging.getLogger()

    # Uvicorn and libraries such as Transformers install their own handlers.
    # Clear those handlers so records propagate through the application formatter.
    for logger in logging.root.manager.loggerDict.values():
        if not isinstance(logger, logging.Logger):
            continue
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = True

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        UTCFormatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    # Convert warnings.warn() output into records handled by the same root logger.
    logging.captureWarnings(True)
