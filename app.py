"""Start Float with `python app.py` (NFR-01). Configuration comes from the environment or .env."""

import logging
import sys

import uvicorn

from app.config import ConfigError, load_settings
from app.main import create_app


def configure_logging() -> None:
    """Send Float's one-line-per-request log (NFR-10) to stderr next to Uvicorn's own output."""
    logger = logging.getLogger("float")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"Float configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    configure_logging()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.port,
        workers=1,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
