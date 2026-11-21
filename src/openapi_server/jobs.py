# server/src/openapi_server/jobs.py
#
# Background job, started by main.py when the app starts.
# Every ORDER_SWEEP_SECONDS (default 60) it settles PENDING orders whose hold has
# run out: CONFIRMED if the payment webhook reported success, CANCELLED otherwise.
# State is in memory, so each server process sweeps its own orders.

import asyncio
import logging
import os

from openapi_server.impl.orders_impl import settle_overdue_orders

SWEEP_SECONDS = float(os.environ.get("ORDER_SWEEP_SECONDS", "60"))

log = logging.getLogger(__name__)


async def run_order_sweeper(interval: float = None) -> None:
    interval = SWEEP_SECONDS if interval is None else interval
    while True:
        await asyncio.sleep(interval)
        try:
            settled = settle_overdue_orders()
            if settled:
                log.info("Settled %d overdue order(s)", settled)
        except Exception:  # one bad run must not stop the job
            log.exception("Order sweep failed")
