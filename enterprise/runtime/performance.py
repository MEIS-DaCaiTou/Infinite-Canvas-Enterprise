"""Small process-local timing aggregates, emitted through existing runtime logs.

Names are supplied by code, never URLs, file names, users or request contents.
No business state, health decisions, admission limits or background file writes.
"""
import asyncio
from contextlib import contextmanager
from functools import wraps
import json
import logging
from threading import Lock
from time import perf_counter

_lock = Lock()
_samples = {}
logger = logging.getLogger('uvicorn.error.performance')
# The fixed runtime defaults to warning. Keep only this bounded diagnostic
# stream visible without enabling verbose HTTP/framework logs globally.


def observe(name, milliseconds, **counts):
    with _lock:
        row = _samples.setdefault(name, {'calls': 0, 'total_ms': 0, 'max_ms': 0})
        row['calls'] += 1
        row['total_ms'] += milliseconds
        row['max_ms'] = max(row['max_ms'], milliseconds)
        for key, value in counts.items():
            row[key] = row.get(key, 0) + value


@contextmanager
def measure(name):
    started = perf_counter()
    try:
        yield
    finally:
        observe(name, (perf_counter() - started) * 1000)


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            with measure(name):
                return fn(*args, **kwargs)
        return call
    return decorate


def drain():
    with _lock:
        rows = dict(_samples)
        _samples.clear()
    return {name: {key: round(value, 2) for key, value in row.items()} for name, row in rows.items()}


async def monitor(role, *, interval=.5, flush_seconds=60):
    logger.setLevel(logging.INFO)  # After the runtime applies uvicorn logging.
    last_flush = perf_counter()
    try:
        while True:
            started = perf_counter()
            await asyncio.sleep(interval)
            observe('event_loop_delay', max(0, (perf_counter()-started-interval)*1000))
            if perf_counter()-last_flush >= flush_seconds:
                logger.info('performance role=%s %s', role, json.dumps(drain(), separators=(',', ':')))
                last_flush = perf_counter()
    except asyncio.CancelledError:
        logger.info('performance role=%s shutdown %s', role, json.dumps(drain(), separators=(',', ':')))
        raise


async def startup_stage(name, fn, *, threaded=True):
    logger.setLevel(logging.INFO)
    started = perf_counter()
    try:
        result = await asyncio.to_thread(fn) if threaded else await fn()
    except BaseException:
        logger.info('startup_phase name=%s elapsed_ms=%.1f outcome=failed', name, (perf_counter()-started)*1000)
        raise
    counts = result if isinstance(result, dict) else {}
    counts = {key: value for key, value in counts.items() if isinstance(value, (int, float))}
    logger.info('startup_phase name=%s elapsed_ms=%.1f counts=%s', name, (perf_counter()-started)*1000, json.dumps(counts))
    return result
