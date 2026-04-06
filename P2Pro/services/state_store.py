from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional


class StateStore:
    """Ein sehr einfacher thread-sicherer Zustandscontainer.

    Er ist bewusst klein gehalten, damit wir ihn später sowohl für die Webapp
    als auch für gui_neu / viewer_app verwenden können.
    """

    def __init__(self, initial_state: Optional[Dict[str, Any]] = None):
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = deepcopy(initial_state or {})
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._revision = 0
        self._updated_at = time.time()

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            data = deepcopy(self._state)
            data["_revision"] = self._revision
            data["_updated_at"] = self._updated_at
            return data

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._state.get(key, default))

    def set(self, key: str, value: Any) -> Dict[str, Any]:
        return self.update({key: value})

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._state.update(deepcopy(patch))
            self._revision += 1
            self._updated_at = time.time()
            snapshot = self.get_state()
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:
                # Listener-Fehler dürfen den Rest nicht blockieren.
                pass
        return snapshot

    def subscribe(self, listener: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe
