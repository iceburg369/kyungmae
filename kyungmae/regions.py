"""지역 이름("대구", "부산 해운대구", "경기 수원시 영통구")을 검색 조건으로 바꾼다.

시도는 서버 검색(시도 코드)으로, 시군구 이하는 주소 글자로 거른다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import AuctionItem

# 짧은 이름 → (시도 코드 후보, 주소에 쓰이는 이름들)
# 강원·전북은 특별자치도 출범으로 코드가 바뀌어 새 코드부터 시도하고 결과가 없으면 옛 코드를 쓴다.
SIDO: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "서울": (("11",), ("서울특별시",)),
    "부산": (("26",), ("부산광역시",)),
    "대구": (("27",), ("대구광역시",)),
    "인천": (("28",), ("인천광역시",)),
    "광주": (("29",), ("광주광역시",)),
    "대전": (("30",), ("대전광역시",)),
    "울산": (("31",), ("울산광역시",)),
    "세종": (("36",), ("세종특별자치시",)),
    "경기": (("41",), ("경기도",)),
    "강원": (("51", "42"), ("강원특별자치도", "강원도")),
    "충북": (("43",), ("충청북도",)),
    "충남": (("44",), ("충청남도",)),
    "전북": (("52", "45"), ("전북특별자치도", "전라북도")),
    "전남": (("46",), ("전라남도",)),
    "경북": (("47",), ("경상북도",)),
    "경남": (("48",), ("경상남도",)),
    "제주": (("50",), ("제주특별자치도", "제주도")),
}


def _aliases() -> dict[str, str]:
    out: dict[str, str] = {}
    for short, (_, names) in SIDO.items():
        out[short] = short
        for n in names:
            out[n] = short
    # 흔히 쓰는 다른 표기
    out.update({"서울시": "서울", "부산시": "부산", "대구시": "대구", "인천시": "인천",
                "광주시": "광주", "대전시": "대전", "울산시": "울산", "세종시": "세종",
                "경기도": "경기", "강원도": "강원", "충청북도": "충북", "충청남도": "충남",
                "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남",
                "제주도": "제주"})
    return out


ALIASES = _aliases()


@dataclass(frozen=True)
class Region:
    sido: str                 # 짧은 시도 이름 (예: 대구)
    rest: tuple[str, ...] = ()  # 시군구 이하 (예: ("수성구",))

    @property
    def codes(self) -> tuple[str, ...]:
        return SIDO[self.sido][0]

    @property
    def label(self) -> str:
        return " ".join((self.sido, *self.rest))

    def matches(self, item: AuctionItem) -> bool:
        addr = item.address.replace(" ", "")
        if not any(n in addr for n in SIDO[self.sido][1]):
            return False
        return all(part in addr for part in self.rest)


def parse_region(text: str) -> Region:
    parts = text.split()
    if not parts:
        raise ValueError("빈 지역 이름")
    sido = ALIASES.get(parts[0])
    if sido is None:
        raise ValueError(
            f"알 수 없는 시도 '{parts[0]}' (사용 가능: {', '.join(SIDO)})"
        )
    return Region(sido, tuple(parts[1:]))


def parse_regions(value: str | list[str] | None) -> list[Region]:
    """'대구, 부산 해운대구' 같은 문자열이나 목록을 Region 목록으로."""
    if not value:
        return []
    items = value.split(",") if isinstance(value, str) else value
    return [parse_region(str(v).strip()) for v in items if str(v).strip()]
