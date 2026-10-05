"""경매 알리미 실행 진입점.

    python -m kyungmae                    # config.yaml 로 1회 실행
    python -m kyungmae -c my.yaml --dry-run
    python -m kyungmae --dump raw.json    # 원본 응답 저장 (필드 확인용)
    python -m kyungmae --test-notify      # 알림 채널만 테스트
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import yaml

from .client import CourtAuctionClient, parse_item
from .filters import Watch
from .notifier import ConsoleNotifier, build_notifiers, format_message, notify_all
from .store import SeenStore

log = logging.getLogger("kyungmae")

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(obj):
    """설정값 안의 ${ENV} 를 환경변수로 치환한다. 없는 변수는 빈 문자열."""
    if isinstance(obj, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    return obj


def _has_remote(notifiers: list) -> bool:
    return any(not isinstance(n, ConsoleNotifier) for n in notifiers)


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg = _expand_env(cfg)
    if not cfg.get("watches"):
        raise SystemExit("config 에 watches(알림 조건)가 하나 이상 있어야 합니다.")
    return cfg


def run(cfg: dict, dry_run: bool = False, dump: str | None = None, resend: bool = False) -> int:
    search_cfg = cfg.get("search") or {}
    days_ahead = int(search_cfg.get("days_ahead", 14))
    queries = search_cfg.get("queries") or [{}]
    extra = search_cfg.get("extra_params") or {}

    client = CourtAuctionClient(
        delay=float(search_cfg.get("delay_seconds", 1.0)),
        page_size=int(search_cfg.get("page_size", 40)),
    )
    watches = [Watch.from_dict(w) for w in cfg["watches"]]
    store = SeenStore(cfg.get("state_file", "data/seen.json"))

    raw_rows: list[dict] = []
    items = {}
    for q in queries:
        criteria = client.build_criteria(days_ahead=days_ahead, extra=extra, **q)
        for raw in client.search(criteria, max_pages=int(search_cfg.get("max_pages", 50))):
            raw_rows.append(raw)
            item = parse_item(raw)
            items[item.uid] = item  # 여러 query 에 중복으로 걸린 물건 제거
    log.info("검색된 물건 %d건", len(items))

    if dump:
        Path(dump).write_text(json.dumps(raw_rows, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("원본 응답을 %s 에 저장했습니다.", dump)

    matches: dict[str, list] = {}
    new_items = []
    for item in sorted(items.values(), key=lambda i: (i.sale_date, i.court, i.case_no)):
        if not resend and not store.is_new(item.uid, item.min_price):
            continue
        hit = [w.name for w in watches if w.matches(item)]
        for name in hit:
            matches.setdefault(name, []).append(item)
        if hit:
            new_items.append(item)

    if not new_items:
        log.info("조건에 맞는 새 물건이 없습니다.")
        return 0

    text = format_message(matches)
    if dry_run:
        print(text)
        log.info("dry-run: 알림을 보내지 않고 상태도 저장하지 않습니다.")
        return 0

    notifiers = build_notifiers(cfg.get("notify") or {})
    if not _has_remote(notifiers):
        log.warning("텔레그램/이메일 등 알림 채널이 설정되지 않아 화면(로그)에만 출력합니다.")
    failed = notify_all(notifiers, text)
    for item in new_items:
        store.add(item.uid, item.min_price, item.sale_date)
    store.save()
    log.info("새 물건 %d건 알림 완료 (실패 채널 %d개)", len(new_items), failed)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kyungmae", description="대법원 경매 새 물건 알리미")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("--dry-run", action="store_true", help="알림/상태저장 없이 결과만 출력")
    p.add_argument("--dump", metavar="FILE", help="검색 원본 응답을 JSON 으로 저장")
    p.add_argument("--resend", action="store_true", help="이미 알린 물건도 포함해 조건에 맞는 물건 모두 다시 알림")
    p.add_argument("--test-notify", action="store_true", help="설정된 알림 채널로 테스트 메시지 전송")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    cfg = load_config(args.config)

    if args.test_notify:
        notifiers = build_notifiers(cfg.get("notify") or {})
        if not _has_remote(notifiers):
            log.error("설정된 알림 채널이 없습니다. TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 등을 확인하세요.")
            return 1
        failed = notify_all(notifiers, "✅ 경매 알리미 테스트 메시지입니다. 이 메시지가 보이면 설정 완료!")
        return 1 if failed else 0
    return run(cfg, dry_run=args.dry_run, dump=args.dump, resend=args.resend)


if __name__ == "__main__":
    sys.exit(main())
