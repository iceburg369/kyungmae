"""이미 알린 물건을 기억해서 같은 물건을 매일 반복해서 알리지 않게 한다."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


class SeenStore:
    def __init__(self, path: str | Path, keep_days: int = 120):
        self.path = Path(path)
        self.keep_days = keep_days
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8") or "{}")

    @staticmethod
    def key(uid: str, min_price: int) -> str:
        # 유찰돼서 최저가가 내려가면 새 물건처럼 다시 알린다.
        return f"{uid}|{min_price}"

    def is_new(self, uid: str, min_price: int) -> bool:
        return self.key(uid, min_price) not in self._data

    def add(self, uid: str, min_price: int, sale_date: str) -> None:
        self._data[self.key(uid, min_price)] = {
            "notified": date.today().isoformat(),
            "sale_date": sale_date,
        }

    def prune(self) -> None:
        cutoff = (date.today() - timedelta(days=self.keep_days)).isoformat()
        self._data = {k: v for k, v in self._data.items() if v.get("notified", "") >= cutoff}

    def save(self) -> None:
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
