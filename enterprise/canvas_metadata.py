"""Bounded light canvas projection; caller still authorizes every request.

The file is the fact source. Any replacement, deletion or metadata change
invalidates the projection; full canvas contents are never retained here.
"""
from collections import OrderedDict
from threading import Lock
from enterprise.collection_query import file_revision
from enterprise.runtime.performance import observe


class CanvasMetadata:
    def __init__(self, capacity=512):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.lock = Lock()

    def get(self, path, load):
        try:
            revision = file_revision(path)
        except OSError:
            # Preserve the original reader's missing/deleted/error semantics.
            return self.project(load())
        with self.lock:
            entry = self.entries.get(path)
            if entry and entry[0] == revision:
                self.entries.move_to_end(path)
                observe('canvas.meta_hit', 0)
                return dict(entry[1])
            self.entries.pop(path, None)
        data = self.project(load())
        observe('canvas.meta_miss', 0)
        try:
            unchanged = file_revision(path) == revision
        except OSError:
            unchanged = False
        if unchanged:
            with self.lock:
                self.entries[path] = (revision, data)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
        return dict(data)

    @staticmethod
    def project(canvas):
        return {key: canvas.get(key) for key in ('id', 'updated_at', 'title', 'icon', 'kind')}
