"""Viewport-keyed LRU so repeated analysis of the same effective viewport reuses the
prior result instead of rerunning imagery + vision + enrichment."""

from collections import OrderedDict


def viewport_key(latitude: float, longitude: float, buffer_m: int) -> tuple:
    # Normalise so tiny float differences for the same viewport don't miss the cache.
    return (round(latitude, 4), round(longitude, 4), int(buffer_m))


class ResultCache:
    def __init__(self, capacity: int = 64):
        self.capacity = capacity
        self._store: "OrderedDict[tuple, object]" = OrderedDict()

    def get(self, key: tuple):
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key: tuple, value) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self.capacity:
            self._store.popitem(last=False)
