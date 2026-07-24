"""
Manah Backend — Background Summarization Job
Runs every 10 minutes via APScheduler.
"""
import asyncio

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from database import DB_PATH
from services.memory import get_sessions_needing_summary, run_summarization


async def _run_summarization_job() -> None:
    logger.info("[CRON] Running summarisation job…")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            sessions = await get_sessions_needing_summary(db)

            if not sessions:
                logger.info("[CRON] No sessions need summarisation.")
                return

            logger.info(f"[CRON] Found {len(sessions)} session(s) to summarise.")
            for s in sessions:
                try:
                    await run_summarization(db, s["sessionId"], s["userId"])
                    await asyncio.sleep(0.5)  # brief pause between sessions
                except Exception as err:
                    logger.error(f"[CRON] Failed to summarise session {s['sessionId']}: {err}")

            logger.info("[CRON] Summarisation job complete.")
    except Exception as err:
        logger.error(f"[CRON] Summarisation job error: {err}")


def start_summarization_job() -> AsyncIOScheduler:
    """Create, schedule, and start the APScheduler. Returns the scheduler instance."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_summarization_job,
        trigger="cron",
        minute="*/10",
        id="summarization_job",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[CRON] Summarisation job scheduled (every 10 minutes)")
    return scheduler
