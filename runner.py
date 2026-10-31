"""着色器工单后台轮询：周期性推进 burner_core 状态机（派单/验收）。

单例 + 守护线程；API 的"立即派单"直接调 burner_core.tick(force=True)，
与本线程共用 RLock。
"""

from __future__ import annotations

import threading

import burner_core

_INTERVAL = 10.0


class _Runner:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._desired = False
        self._stop_event = threading.Event()
        self._last_result: dict = {}

    def status(self) -> dict:
        with self._lock:
            return {
                "running": bool(self._desired and self._thread and self._thread.is_alive()),
                "lastTick": self._last_result,
            }

    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._desired = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="burner-runner", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._desired = False
            self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3)
        return self.status()

    def _loop(self) -> None:
        while self._desired:
            try:
                self._last_result = burner_core.tick()
            except Exception:
                self._last_result = {"action": "error"}
            self._stop_event.wait(_INTERVAL)


runner = _Runner()
