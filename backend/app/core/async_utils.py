"""
Utility for running blocking (synchronous / CPU-bound) callables from async
code without stalling the event loop.

All CPU-heavy operations — pdfplumber, KeyBERT inference, dictionary scans —
must go through run_blocking() so FastAPI's event loop stays responsive.

Usage:
    from app.core.async_utils import run_blocking
    text = await run_blocking(extract_text_from_pdf, file_bytes)
"""
import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_blocking(fn: Callable[..., T], *args: Any) -> T:
    """
    Execute a synchronous callable in the default ThreadPoolExecutor.
    Uses asyncio.get_running_loop() (not the deprecated get_event_loop).
    """
    loop = asyncio.get_running_loop()
    # lambda captures args so positional-only callables work cleanly
    return await loop.run_in_executor(None, lambda: fn(*args))
