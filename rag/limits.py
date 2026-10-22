"""Bounds for a single-process personal deployment."""

import asyncio
from functools import partial
from threading import BoundedSemaphore

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_URL_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_CHARS = 2_000_000
MAX_CHUNKS_PER_SESSION = 10_000
MAX_DOCUMENTS_PER_SESSION = 20
MAX_SESSIONS = 50
MAX_ANSWER_TOKENS = 1024
_work_slots = BoundedSemaphore(1)


class ResourceLimitError(ValueError):
    pass


async def run_work(func, *args, **kwargs):
    if not _work_slots.acquire(blocking=False):
        raise ResourceLimitError("The server is busy. Please try again shortly.")

    def execute():
        try:
            return func(*args, **kwargs)
        finally:
            _work_slots.release()

    # A disconnected request must not free the slot while its thread still runs.
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, partial(execute))
    future.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    return await asyncio.shield(future)
