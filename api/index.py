"""Vercel 진입점 — 지금 조건에 맞는 경매 물건을 웹 페이지로 보여준다.

    https://<프로젝트>.vercel.app/                     config.yaml 의 regions 로 조회
    https://<프로젝트>.vercel.app/?regions=대구 수성구   이번 조회에만 다른 지역 사용

알림 발송과 중복 기록(data/seen.json)은 하지 않는다.
(Vercel 서버는 파일을 영구 저장할 수 없어서, 매일 알림은 GitHub Actions 가 담당)
"""

from __future__ import annotations

import html
import logging
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kyungmae.main import find_matches, load_config  # noqa: E402
from kyungmae.notifier import DETAIL_URL, format_item  # noqa: E402
from kyungmae.regions import parse_regions  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>경매 알리미</title>
<style>
 body{{font-family:system-ui,-apple-system,"Apple SD Gothic Neo",sans-serif;max-width:860px;margin:0 auto;padding:16px;line-height:1.5}}
 form{{display:flex;gap:8px;margin:12px 0}} input{{flex:1;padding:8px}} button{{padding:8px 14px}}
 pre{{white-space:pre-wrap;background:#f5f5f5;padding:10px;border-radius:6px}}
 .err{{color:#b00}}
</style></head><body>
<h1>경매 알리미</h1>
<form><input name="regions" value="{regions}" placeholder="예: 대구 달서구 상인동, 부산 해운대구">
<button>조회</button></form>
{body}
<p><a href="{detail}">법원경매정보에서 사건번호로 상세 조회</a></p>
</body></html>"""


def render(regions_q: str) -> tuple[int, str]:
    cfg = load_config(ROOT / "config.yaml")
    # Vercel 에서는 프로젝트 폴더가 읽기 전용이라 기록 파일 경로를 /tmp 로 돌린다.
    cfg["state_file"] = "/tmp/kyungmae-seen.json"
    try:
        parse_regions(regions_q or cfg.get("regions"))
    except ValueError as e:
        return 400, f'<p class="err">지역 설정 오류: {html.escape(str(e))}</p>'
    try:
        matches, items, _ = find_matches(cfg, resend=True, regions_override=regions_q or None)
    except Exception as e:  # 사이트 차단·개편 등
        logging.exception("조회 실패")
        return 502, f'<p class="err">법원경매정보 조회 실패: {html.escape(str(e))}</p>'
    if not items:
        return 200, "<p>지금 조건에 맞는 물건이 없습니다.</p>"
    parts = [f"<p>조건에 맞는 물건 {len(items)}건</p>"]
    for name, rows in matches.items():
        parts.append(f"<h2>{html.escape(name)} ({len(rows)}건)</h2>")
        parts.extend(f"<pre>{html.escape(format_item(i))}</pre>" for i in rows)
    return 200, "\n".join(parts)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        regions_q = (q.get("regions") or [""])[0].strip()
        status, body = render(regions_q)
        page = PAGE.format(regions=html.escape(regions_q), body=body, detail=DETAIL_URL)
        data = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
