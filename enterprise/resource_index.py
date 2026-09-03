"""Bounded, metadata-invalidated JSON reference cache; never caches grants.

Callers must still query current ownership for every request. No background
scan, mutable sidecar, or import-time filesystem access is required.
"""

from collections import OrderedDict
from pathlib import Path
from threading import RLock


class ResourceReferenceIndex:
    def __init__(self, *, max_files=4096, max_references=100_000,
                 max_file_bytes=8 * 1024 * 1024, max_reference_chars=8 * 1024 * 1024):
        self.max_files = max_files
        self.max_references = max_references
        self.max_file_bytes = max_file_bytes
        self.max_reference_chars = max_reference_chars
        self._entries = OrderedDict()
        self._references = 0
        self._reference_chars = 0
        self._lock = RLock()

    @staticmethod
    def _fingerprint(path):
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def _discard(self, key):
        old = self._entries.pop(key, None)
        if old is not None:
            self._references -= len(old[2])
            self._reference_chars -= old[3]

    def matching_ids(self, paths, resource_url, load_json, extract_urls):
        result = set()
        with self._lock:
            for path in paths:
                path = Path(path)
                key = str(path.absolute())
                try:
                    fingerprint = self._fingerprint(path)
                    cached = self._entries.get(key)
                    if cached is not None and cached[0] == fingerprint:
                        self._entries.move_to_end(key)
                        _, identifier, urls, _weight = cached
                    else:
                        self._discard(key)
                        data = load_json(path)
                        if not isinstance(data, dict):
                            continue
                        identifier = str(data.get("id") or path.stem)
                        urls = frozenset(extract_urls(data))
                        # A concurrent save must not create a reusable stale entry.
                        if self._fingerprint(path) != fingerprint:
                            continue
                        weight = sum(len(url) for url in urls)
                        if (fingerprint[2] <= self.max_file_bytes and len(urls) <= self.max_references
                                and weight <= self.max_reference_chars):
                            self._entries[key] = (fingerprint, identifier, urls, weight)
                            self._references += len(urls)
                            self._reference_chars += weight
                            while (len(self._entries) > self.max_files or self._references > self.max_references
                                   or self._reference_chars > self.max_reference_chars):
                                self._discard(next(iter(self._entries)))
                    if identifier and resource_url in urls:
                        result.add(identifier)
                except (OSError, ValueError, TypeError):
                    self._discard(key)
        return result
