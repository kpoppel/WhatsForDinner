"""Application logging setup shared by the API process."""

from __future__ import annotations

import logging


def configure_logging() -> None:
    """Configure the process-wide logging format and default level."""

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s level=%(levelname)s logger=%(name)s "
            "message=%(message)s"
        ),
    )
