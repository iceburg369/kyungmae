"""대법원 법원경매정보(courtauction.go.kr) 물건 검색 클라이언트.

2024년 개편된 사이트는 WebSquare 화면 뒤에서 JSON API(`*.on`)를 호출한다.
이 모듈은 '물건상세검색' 화면이 사용하는 검색 API를 그대로 호출한다.
사이트 구조가 바뀌면 config.yaml 의 `search.extra_params` 로 요청 필드를
덮어쓰거나, `--dump` 옵션으로 원본 응답을 확인해 필드명을 맞추면 된다.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.courtauction.go.kr"
INDEX_PATH = "/pgj/index.on"
SEARCH_PATH = "/pgj/pgjsearch/searchControllerMain.on"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


@dataclass
class AuctionItem:
    """검색 결과 한 건(물건 단위)."""

    case_no: str          # 사건번호 (예: 2024타경12345)
    item_no: str          # 물건번호
    court: str            # 담당 법원
    address: str          # 소재지
    usage: str            # 용도 (아파트, 다세대, 대지 ...)
    appraisal: int        # 감정평가액
    min_price: int        # 최저매각가격
    fail_count: int       # 유찰횟수
    sale_date: str        # 매각기일 (YYYY-MM-DD)
    area: str = ""        # 면적 등 비고
    note: str = ""        # 물건비고 / 특수조건
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def uid(self) -> str:
        return f"{self.court}|{self.case_no}|{self.item_no}"

    @property
    def area_m2(self) -> float:
        """면적(㎡). 여러 개면 가장 큰 값, 알 수 없으면 0."""
        nums = [float(n) for n in re.findall(r"([\d.]+)\s*㎡", self.area)]
        if nums:
            return max(nums)
        try:
            return float(self.raw.get("maxArea") or 0)
        except ValueError:
            return 0.0

    @property
    def ratio(self) -> float:
        """최저가 / 감정가 (%)."""
        return (self.min_price / self.appraisal * 100) if self.appraisal else 0.0


def _first(raw: dict, *keys: str, default: Any = "") -> Any:
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return v
    return default


def _to_int(v: Any) -> int:
    if v in (None, ""):
        return 0
    try:
        return int(float(str(v).replace(",", "").strip()))
    except ValueError:
        return 0


def _clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def _fmt_date(v: Any) -> str:
    s = str(v or "").strip().replace(".", "").replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(v or "")


def parse_item(raw: dict) -> AuctionItem:
    """API 응답의 한 행을 AuctionItem 으로 변환한다.

    필드명이 화면/버전에 따라 조금씩 달라서 후보 키를 여러 개 둔다.
    """
    return AuctionItem(
        case_no=str(_first(raw, "srnSaNo", "csNo", "saNo", "userCsNo")),
        item_no=str(_first(raw, "maemulSer", "dspslGdsSeq", "mokmulSer", default="1")),
        court=str(_first(raw, "jiwonNm", "cortOfcNm", "boNm")),
        address=str(_first(raw, "printSt", "bgPlaceRdAllAddr", "hjguRd", "daepyoLotnoAddr", "addr")),
        usage=str(_first(raw, "dspslUsgNm", "sclDspslGdsLstUsgNm", "mulJinyn", "usgNm")),
        appraisal=_to_int(_first(raw, "gamevalAmt", "aeeEvlAmt")),
        min_price=_to_int(_first(raw, "minmaePrice", "lwsDspslPrc", "notifyMinmaePrice1")),
        fail_count=_to_int(_first(raw, "yuchalCnt", "flbdNcnt", default=0)),
        sale_date=_fmt_date(_first(raw, "maeGiil", "dspslDxdyYmd", "dxdyYmd")),
        area=_clean(_first(raw, "pjbBuldList", "areaList", "objctArDts")),
        note=_clean(_first(raw, "mulBigo", "dspslGdsRmk", "rmk")),
        raw=raw,
    )


# 사이트가 허용하는 페이지 크기 (5, 100 등은 400 오류)
ALLOWED_PAGE_SIZES = (10, 20, 40)


class CourtAuctionClient:
    def __init__(
        self,
        timeout: float = 20.0,
        delay: float = 1.0,
        page_size: int = 40,
        retries: int = 3,
        retry_wait: float = 10.0,
    ):
        if page_size not in ALLOWED_PAGE_SIZES:
            raise ValueError(f"page_size 는 {ALLOWED_PAGE_SIZES} 중 하나여야 합니다: {page_size}")
        self.retries = retries
        self.retry_wait = retry_wait
        self.timeout = timeout
        self.delay = delay  # 페이지 요청 사이 대기(초) – 서버 부담을 줄이기 위함
        self.page_size = page_size
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Origin": BASE_URL,
                "Referer": BASE_URL + INDEX_PATH,
            }
        )
        self._warmed_up = False

    def _warm_up(self) -> None:
        """첫 페이지를 열어 세션 쿠키(JSESSIONID 등)를 받는다."""
        if self._warmed_up:
            return
        try:
            self.session.get(BASE_URL + INDEX_PATH, timeout=self.timeout)
        except requests.RequestException as e:  # 쿠키 없이도 동작하는 경우가 있어 경고만
            log.warning("메인 페이지 접속 실패(계속 진행): %s", e)
        self._warmed_up = True

    @staticmethod
    def build_criteria(
        days_ahead: int = 14,
        sido_code: str = "",
        sigungu_code: str = "",
        court_code: str = "",
        usage_large: str = "",
        usage_mid: str = "",
        usage_small: str = "",
        appraisal_min: int | None = None,
        appraisal_max: int | None = None,
        min_price_min: int | None = None,
        min_price_max: int | None = None,
        fail_count_min: int | None = None,
        fail_count_max: int | None = None,
        today: date | None = None,
        extra: dict | None = None,
    ) -> dict:
        today = today or date.today()

        def s(v: Any) -> str:
            return "" if v is None else str(v)

        criteria = {
            "rletDspslSpcCondCd": "",
            "bidDvsCd": "000331",            # 기일입찰
            "mvprpRletDvsCd": "00031R",      # 부동산
            "cortAuctnSrchCondCd": "0004601",
            "rprsAdongSdCd": sido_code,
            "rprsAdongSggCd": sigungu_code,
            "rprsAdongEmdCd": "",
            "rdnmSdCd": "",
            "rdnmSggCd": "",
            "rdnmNo": "",
            "mvprpDspslPlcAdongSdCd": "",
            "mvprpDspslPlcAdongSggCd": "",
            "mvprpDspslPlcAdongEmdCd": "",
            "rdDspslPlcAdongSdCd": "",
            "rdDspslPlcAdongSggCd": "",
            "rdDspslPlcAdongEmdCd": "",
            "cortOfcCd": court_code,
            "jdbnCd": "",
            "execrOfcDvsCd": "",
            "lclDspslGdsLstUsgCd": usage_large,
            "mclDspslGdsLstUsgCd": usage_mid,
            "sclDspslGdsLstUsgCd": usage_small,
            "cortAuctnMbrsId": "",
            "aeeEvlAmtMin": s(appraisal_min),
            "aeeEvlAmtMax": s(appraisal_max),
            "lwsDspslPrcRateMin": "",
            "lwsDspslPrcRateMax": "",
            "flbdNcntMin": s(fail_count_min),
            "flbdNcntMax": s(fail_count_max),
            "objctArDtsMin": "",
            "objctArDtsMax": "",
            "mvprpArtclKndCd": "",
            "mvprpArtclNm": "",
            "mvprpAtchmPlcTypCd": "",
            "notifyLoc": "off",
            "lafjOrderBy": "",
            "pgmId": "PGJ151F01",
            "csNo": "",
            # 1 = 법원 기준 검색, 2 = 소재지(시도/시군구) 기준 검색.
            # 1 로 두면 시도 코드는 무시되고 전국 결과가 나온다.
            "cortStDvs": "2" if (sido_code or sigungu_code) else "1",
            "statNum": 1,
            "bidBgngYmd": today.strftime("%Y%m%d"),
            "bidEndYmd": (today + timedelta(days=days_ahead)).strftime("%Y%m%d"),
            "dspslDxdyYmd": "",
            "fstDspslHm": "",
            "scndDspslHm": "",
            "thrdDspslHm": "",
            "fothDspslHm": "",
            "dspslPlcNm": "",
            "lwsDspslPrcMin": s(min_price_min),
            "lwsDspslPrcMax": s(min_price_max),
            "grbxTypCd": "",
            "gdsVendNm": "",
            "fuelKndCd": "",
            "carMdyrMax": "",
            "carMdyrMin": "",
            "carMdlNm": "",
            "sideDvsCd": "",
        }
        if extra:
            criteria.update(extra)
        return criteria

    def search_page(self, criteria: dict, page_no: int) -> tuple[list[dict], int]:
        """한 페이지 검색. (원본 행 목록, 전체 건수) 반환."""
        self._warm_up()
        body = {
            "dma_pageInfo": {
                "pageNo": page_no,
                "pageSize": self.page_size,
                "bfPageNo": "",
                "startRowNo": "",
                "totalCnt": "",
                "totalYn": "Y",
                "groupTotalCount": "",
            },
            "dma_srchGdsDtlSrchInfo": criteria,
        }
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "SC-Userid": "NONUSER",
            "SC-Pgmid": "PGJ151F01",
            "submissionid": "mf_wfm_mainFrame_sbm_selectGdsDtlSrch",
        }
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.post(
                    BASE_URL + SEARCH_PATH, json=body, headers=headers, timeout=self.timeout
                )
                # 요청이 몰리면 400 + "잠시 후 다시 이용해 주십시오" 를 돌려준다.
                if resp.status_code >= 500 or (resp.status_code == 400 and "잠시 후" in resp.text):
                    raise requests.HTTPError(f"{resp.status_code}: {resp.text[:200]}", response=resp)
                resp.raise_for_status()
                return extract_rows(resp.json())
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                retryable = status is None or status >= 500 or "잠시 후" in str(e)
                if attempt >= self.retries or not retryable:
                    raise
                wait = self.retry_wait * (attempt + 1)
                log.warning("검색 요청 실패(%s), %.0f초 후 재시도 %d/%d", e, wait, attempt + 1, self.retries)
                time.sleep(wait)
        raise AssertionError("unreachable")

    def search(self, criteria: dict, max_pages: int = 50) -> Iterator[dict]:
        """모든 페이지를 순회하며 원본 행을 하나씩 돌려준다."""
        page = 1
        seen = 0
        while page <= max_pages:
            rows, total = self.search_page(criteria, page)
            log.info("page %d: %d건 (전체 %d건)", page, len(rows), total)
            yield from rows
            seen += len(rows)
            if not rows or seen >= total:
                break
            page += 1
            time.sleep(self.delay)


def extract_rows(payload: dict) -> tuple[list[dict], int]:
    """응답 JSON 에서 결과 목록과 전체 건수를 꺼낸다."""
    if payload.get("status") not in (None, 200, "200") and "errors" in payload:
        raise RuntimeError(f"검색 API 오류: {payload.get('message') or payload.get('errors')}")
    data = payload.get("data", payload) or {}
    rows = data.get("dlt_srchResult") or []
    page_info = data.get("dma_pageInfo") or {}
    total = _to_int(page_info.get("totalCnt")) or len(rows)
    return rows, total
