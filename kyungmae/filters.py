"""사용자 조건으로 경매 물건을 거르는 로직 (서버 검색 후 2차 필터)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .client import AuctionItem


@dataclass
class Watch:
    """알림 조건 하나. 여러 개를 등록할 수 있다."""

    name: str
    address_keywords: list[str] = field(default_factory=list)  # 하나라도 포함 (OR)
    usage_keywords: list[str] = field(default_factory=list)    # 하나라도 포함 (OR)
    exclude_keywords: list[str] = field(default_factory=list)  # 주소/용도/비고에 있으면 제외
    appraisal_min: int | None = None
    appraisal_max: int | None = None
    min_price_min: int | None = None
    min_price_max: int | None = None
    fail_count_min: int | None = None
    max_ratio: float | None = None  # 최저가/감정가(%) 이하만

    @classmethod
    def from_dict(cls, d: dict) -> "Watch":
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"watch '{d.get('name')}' 에 알 수 없는 항목: {sorted(unknown)}")
        return cls(**d)

    def matches(self, item: AuctionItem) -> bool:
        def contains_any(text: str, words: list[str]) -> bool:
            t = text.replace(" ", "")
            return any(w.replace(" ", "") in t for w in words)

        if self.address_keywords and not contains_any(item.address, self.address_keywords):
            return False
        if self.usage_keywords and not contains_any(
            f"{item.usage} {item.address}", self.usage_keywords
        ):
            return False
        if self.exclude_keywords and contains_any(
            f"{item.address} {item.usage} {item.note}", self.exclude_keywords
        ):
            return False
        if self.appraisal_min is not None and item.appraisal < self.appraisal_min:
            return False
        if self.appraisal_max is not None and item.appraisal > self.appraisal_max:
            return False
        if self.min_price_min is not None and item.min_price < self.min_price_min:
            return False
        if self.min_price_max is not None and item.min_price > self.min_price_max:
            return False
        if self.fail_count_min is not None and item.fail_count < self.fail_count_min:
            return False
        if self.max_ratio is not None and item.ratio > self.max_ratio:
            return False
        return True
