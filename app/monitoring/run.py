import logging
import sys

from app.core.logging_config import setup_logging
from app.monitoring.monitor import run_monitor


def main() -> int:
    setup_logging()
    try:
        result = run_monitor()
    except Exception:
        logging.getLogger(__name__).exception("Scheduled health check failed.")
        return 1

    status = result["diagnosis"]["status"]
    logging.getLogger(__name__).info(
        "Scheduled health check finished with status=%s, alert_sent=%s",
        status,
        result["alert_sent"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
