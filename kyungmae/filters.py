"""사용자 조건으로 경매 물건을 거르는 로직 (서버 검색 후 2차 필터)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .client import AuctionItem

# 선택해서 켤 수 있는 위험 물건 제외 항목.
# 이름 → 주소/용도/물건비고에서 찾을 문구
RISK_KEYWORDS: dict[str, list[str]] = {
    "대항력임차인": ["대항할 수 있는 임차인", "대항력있는 임차인", "대항력 있는 임차인"],
    "선순위권리": ["선순위", "인수되는", "매수인이 인수"],
    "지분매각": ["지분"],
    "유치권": ["유치권"],
    "법정지상권": ["법정지상권"],
    "대지권미등기": ["대지권미등기", "대지권 미등기", "대지권없음", "대지권 없음"],
    "토지별도등기": ["토지별도등기", "토지 별도등기"],
    "위반건축물": ["위반건축물"],
    "재매각": ["재매각", "매수보증금 20%", "매수보증금20%"],
    "분묘기지권": ["분묘"],
}


def _norm(text: str) -> str:
    return text.replace(" ", "")


def _contains_any(text: str, words: list[str]) -> bool:
    t = _norm(text)
    return any(_norm(w) in t for w in words)


@dataclass
class Watch:
    """알림 조건 하나. 여러 개를 등록할 수 있다."""

    name: str
    address_keywords: list[str] = field(default_factory=list)  # 하나라도 포함 (OR)
    usage_keywords: list[str] = field(default_factory=list)    # 하나라도 포함 (OR)
    usage_in_address: bool = False  # True 면 용도 키워드를 주소(건물명)에서도 찾음
    exclude_keywords: list[str] = field(default_factory=list)  # 주소/용도/비고에 있으면 제외
    exclude_risks: list[str] = field(default_factory=list)     # RISK_KEYWORDS 의 이름
    courts: list[str] = field(default_factory=list)            # 담당 법원 이름 일부 (OR)
    appraisal_min: int | None = None
    appraisal_max: int | None = None
    min_price_min: int | None = None
    min_price_max: int | None = None
    fail_count_min: int | None = None
    fail_count_max: int | None = None
    min_ratio: float | None = None  # 최저가/감정가(%) 이상만
    max_ratio: float | None = None  # 최저가/감정가(%) 이하만
    area_min: float | None = None   # 면적(㎡) 이상
    area_max: float | None = None   # 면적(㎡) 이하
    sale_within_days: int | None = None  # 매각기일이 오늘부터 N일 안인 것만

    def __post_init__(self) -> None:
        unknown = [r for r in self.exclude_risks if r not in RISK_KEYWORDS]
        if unknown:
            raise ValueError(
                f"watch '{self.name}' 의 exclude_risks 에 알 수 없는 항목: {unknown} "
                f"(사용 가능: {', '.join(RISK_KEYWORDS)})"
            )

    @classmethod
    def from_dict(cls, d: dict) -> "Watch":
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"watch '{d.get('name')}' 에 알 수 없는 항목: {sorted(unknown)}")
        return cls(**d)

    def matches(self, item: AuctionItem, today: date | None = None) -> bool:
        if self.address_keywords and not _contains_any(item.address, self.address_keywords):
            return False
        if self.usage_keywords:
            usage_text = f"{item.usage} {item.address}" if self.usage_in_address else item.usage
            if not _contains_any(usage_text, self.usage_keywords):
                return False
        if self.courts and not _contains_any(item.court, self.courts):
            return False

        full_text = f"{item.address} {item.usage} {item.note}"
        if self.exclude_keywords and _contains_any(full_text, self.exclude_keywords):
            return False
        for risk in self.exclude_risks:
            if _contains_any(full_text, RISK_KEYWORDS[risk]):
                return False

        def out_of(value: float, lo: float | None, hi: float | None) -> bool:
            return (lo is not None and value < lo) or (hi is not None and value > hi)

        if out_of(item.appraisal, self.appraisal_min, self.appraisal_max):
            return False
        if out_of(item.min_price, self.min_price_min, self.min_price_max):
            return False
        if out_of(item.fail_count, self.fail_count_min, self.fail_count_max):
            return False
        if out_of(item.ratio, self.min_ratio, self.max_ratio):
            return False
        if self.area_min is not None or self.area_max is not None:
            # 면적을 알 수 없는 물건은 조건을 확인할 수 없으므로 제외
            if not item.area_m2 or out_of(item.area_m2, self.area_min, self.area_max):
                return False
        if self.sale_within_days is not None:
            limit = ((today or date.today()) + timedelta(days=self.sale_within_days)).isoformat()
            if not item.sale_date or item.sale_date > limit:
                return False
        return True
