import json
from datetime import date

from kyungmae import main as main_mod
from kyungmae.client import CourtAuctionClient, extract_rows, parse_item
from kyungmae.filters import Watch
from kyungmae.notifier import format_message, won
from kyungmae.store import SeenStore

RAW = {
    "srnSaNo": "2025타경1234",
    "maemulSer": "1",
    "jiwonNm": "서울중앙지방법원",
    "printSt": "서울특별시 강남구 대치동 123 은마아파트 101동 1004호",
    "dspslUsgNm": "아파트",
    "gamevalAmt": "2,000,000,000",
    "minmaePrice": "1600000000",
    "yuchalCnt": "1",
    "maeGiil": "20261020",
    "mulBigo": "",
}


def test_parse_item():
    item = parse_item(RAW)
    assert item.case_no == "2025타경1234"
    assert item.appraisal == 2_000_000_000
    assert item.min_price == 1_600_000_000
    assert item.fail_count == 1
    assert item.sale_date == "2026-10-20"
    assert item.ratio == 80


def test_extract_rows():
    payload = {"data": {"dlt_srchResult": [RAW, RAW], "dma_pageInfo": {"totalCnt": "57"}}}
    rows, total = extract_rows(payload)
    assert len(rows) == 2 and total == 57


def test_build_criteria_dates():
    c = CourtAuctionClient.build_criteria(days_ahead=7, sido_code="11", today=date(2026, 10, 5))
    assert c["bidBgngYmd"] == "20261005"
    assert c["bidEndYmd"] == "20261012"
    assert c["rprsAdongSdCd"] == "11"


def test_watch_matching():
    item = parse_item(RAW)
    assert Watch(name="a", address_keywords=["강남구"], usage_keywords=["아파트"]).matches(item)
    assert not Watch(name="b", address_keywords=["서초구"]).matches(item)
    assert not Watch(name="c", min_price_max=1_000_000_000).matches(item)
    assert not Watch(name="d", max_ratio=70).matches(item)
    assert not Watch(name="e", fail_count_min=2).matches(item)
    assert not Watch(name="f", exclude_keywords=["은마"]).matches(item)
    assert Watch(name="g", address_keywords=["강 남 구"]).matches(item)  # 공백 무시


def test_seen_store(tmp_path):
    path = tmp_path / "seen.json"
    s = SeenStore(path)
    assert s.is_new("x", 100)
    s.add("x", 100, "2026-10-20")
    s.save()
    s2 = SeenStore(path)
    assert not s2.is_new("x", 100)
    assert s2.is_new("x", 80)  # 가격이 내려가면 다시 알림


def test_format():
    assert won(1_600_000_000) == "16억원"
    assert won(350_000_000) == "3억 5,000만원"
    text = format_message({"테스트": [parse_item(RAW)]})
    assert "2025타경1234" in text and "80%" in text


def test_run_end_to_end(tmp_path, monkeypatch, capsys):
    def fake_search(self, criteria, max_pages=50):
        yield RAW

    monkeypatch.setattr(CourtAuctionClient, "search", fake_search)
    cfg = {
        "state_file": str(tmp_path / "seen.json"),
        "search": {"queries": [{"sido_code": "11"}, {"sido_code": "41"}]},
        "watches": [{"name": "강남 아파트", "address_keywords": ["강남구"]}],
        "notify": {"console": True},
    }
    assert main_mod.run(cfg) == 0
    out = capsys.readouterr().out
    assert out.count("2025타경1234") == 1  # query 두 개에 걸려도 한 번만
    # 두 번째 실행에서는 이미 알린 물건이므로 출력 없음
    assert main_mod.run(cfg) == 0
    assert "2025타경1234" not in capsys.readouterr().out
    assert json.loads((tmp_path / "seen.json").read_text())


def test_env_expansion(monkeypatch):
    monkeypatch.setenv("TOKEN_X", "abc")
    assert main_mod._expand_env({"a": ["${TOKEN_X}", "${NOPE}"]}) == {"a": ["abc", ""]}
