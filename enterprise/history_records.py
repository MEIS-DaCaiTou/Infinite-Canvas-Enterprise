"""History metadata only; authorization stays in Gateway, media is never deleted here."""
from concurrent.futures import Future
import json
from threading import Condition
import time

from enterprise.local_json import atomic_write_json, document_lock, read_json
from enterprise.runtime import performance


class HistoryUnavailable(RuntimeError):
    pass


class HistoryDeleteDenied(RuntimeError):
    pass


def read_records(path):
    try:
        records = read_json(path)
    except FileNotFoundError:
        return []
    except (OSError, ValueError, TypeError) as exc:
        raise HistoryUnavailable('历史记录暂不可读，原文件已保留；请检查权限或恢复有效备份。') from exc
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise HistoryUnavailable('历史记录格式异常，原文件已保留；请检查或恢复有效备份。')
    return records


def append_record(path, record):
    """No implicit age/count eviction. Explicit retention policy is separate."""
    record.setdefault('timestamp', time.time())
    _prepend_records(path, [record])


@performance.timed('history.commit')
def _prepend_records(path, records):
    try:
        with document_lock(path):
            previous = read_records(path)
            atomic_write_json(path, [*reversed(records), *previous], indent=4)
    except OSError as exc:
        raise HistoryUnavailable('历史记录写入未完成，原文件已保留；请检查磁盘和权限。') from exc
    except (ValueError, TypeError) as exc:
        raise HistoryUnavailable('历史记录格式异常，原文件已保留；生成结果保留。') from exc


class HistoryWriter:
    """Share a commit among writers already waiting on the same upstream file."""

    def __init__(self, path):
        self.path = path
        self._condition = Condition()
        self._writing = False
        self._pending = []

    def append(self, record):
        record.setdefault('timestamp', time.time())
        try:
            # Validate each record before it can affect any other completion.
            json.dumps(record, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError) as exc:
            raise HistoryUnavailable('历史记录格式异常，本条未写入；生成结果保留。') from exc

        result = Future()
        with self._condition:
            self._pending.append((record, result))
            self._condition.wait_for(lambda: result.done() or not self._writing)
            if result.done():
                return result.result()
            self._writing = True
            batch, self._pending = self._pending, []

        try:
            _prepend_records(self.path, [item for item, _ in batch])
        except BaseException as exc:
            for _, receipt in batch:
                receipt.set_exception(exc)
        else:
            for _, receipt in batch:
                receipt.set_result(None)
        finally:
            with self._condition:
                self._writing = False
                self._condition.notify_all()
        return result.result()


def timestamp_matches(value, requested):
    try:
        return abs(float(value) - float(requested)) < 0.001
    except (ValueError, TypeError):
        return str(value) == str(requested)


def delete_matching(path, timestamp, can_delete=None):
    """Select and recheck ownership inside the same lease used by appends."""
    try:
        with document_lock(path):
            records = read_records(path)
            matches = [r for r in records if timestamp_matches(r.get('timestamp', 0), timestamp)]
            if not matches:
                return []
            if can_delete is not None and not can_delete(matches):
                raise HistoryDeleteDenied('历史记录不存在或无权限访问')
            remaining = [r for r in records if not timestamp_matches(r.get('timestamp', 0), timestamp)]
            atomic_write_json(path, remaining, indent=4)
            return matches
    except OSError as exc:
        raise HistoryUnavailable('历史记录删除未完成，原文件和素材保留；请检查磁盘和权限。') from exc
