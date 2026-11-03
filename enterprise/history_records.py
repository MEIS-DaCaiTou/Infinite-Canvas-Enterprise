"""History metadata only; authorization stays in Gateway, media is never deleted here."""
import time

from enterprise.local_json import atomic_write_json, document_lock, read_json


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
    try:
        with document_lock(path):
            records = read_records(path)
            records.insert(0, record)
            atomic_write_json(path, records, indent=4)
    except OSError as exc:
        raise HistoryUnavailable('历史记录写入未完成，原文件已保留；请检查磁盘和权限。') from exc


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
