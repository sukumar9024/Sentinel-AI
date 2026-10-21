"""Hourly retention with a regular heartbeat; detection never waits on maintenance."""

import logging
import os
import socket
import time
from .config import Settings
from .integrations import retention
from .models import database
from .worker import heartbeat


def run():
    settings = Settings()
    factory = database(settings.database_url)
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    name = f"maintenance:{socket.gethostname()}:{os.getpid()}"
    next_run = 0
    while True:
        try:
            if time.monotonic() >= next_run:
                retention(factory, settings)
                next_run = time.monotonic() + 3600
            heartbeat(factory, name)
        except Exception as error:
            logging.warning("Retention deferred (%s)", type(error).__name__)
            next_run = time.monotonic() + 60
        time.sleep(15)


if __name__ == "__main__":
    run()
