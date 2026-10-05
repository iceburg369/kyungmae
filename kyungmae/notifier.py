"""알림 채널: 콘솔, 텔레그램, 이메일(SMTP), 디스코드/슬랙 웹훅.

비밀값(토큰, 비밀번호)은 config.yaml 에 직접 쓰지 말고 `${ENV_NAME}` 형태로
환경변수를 참조하는 것을 권장한다.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

import requests

from .client import AuctionItem

log = logging.getLogger(__name__)

DETAIL_URL = "https://www.courtauction.go.kr/pgj/index.on"


def won(n: int) -> str:
    if n >= 100_000_000:
        eok, rest = divmod(n, 100_000_000)
        man = rest // 10_000
        return f"{eok}억 {man:,}만원" if man else f"{eok}억원"
    if n >= 10_000:
        return f"{n // 10_000:,}만원"
    return f"{n:,}원"


def format_item(item: AuctionItem) -> str:
    lines = [
        f"[{item.court}] {item.case_no} (물건 {item.item_no})",
        f"  용도: {item.usage}",
        f"  주소: {item.address}",
        f"  감정가 {won(item.appraisal)} → 최저가 {won(item.min_price)} "
        f"({item.ratio:.0f}%, 유찰 {item.fail_count}회)",
        f"  매각기일: {item.sale_date}",
    ]
    if item.area:
        lines.append(f"  면적: {item.area}")
    if item.note:
        lines.append(f"  비고: {item.note[:200]}")
    return "\n".join(lines)


def format_message(matches: dict[str, list[AuctionItem]]) -> str:
    total = sum(len(v) for v in matches.values())
    parts = [f"🏠 새 경매 물건 {total}건"]
    for watch_name, items in matches.items():
        parts.append(f"\n■ {watch_name} ({len(items)}건)")
        parts.extend(format_item(i) for i in items)
    parts.append(f"\n상세 조회: {DETAIL_URL} (사건번호로 검색)")
    return "\n".join(parts)


def _chunks(text: str, size: int) -> list[str]:
    out, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > size and buf:
            out.append(buf)
            buf = ""
        buf += line + "\n"
    if buf:
        out.append(buf)
    return out


class Notifier:
    def send(self, text: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    def send(self, text: str) -> None:
        print(text)


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id

    def send(self, text: str) -> None:
        for chunk in _chunks(text, 3900):  # 텔레그램 메시지 최대 4096자
            r = requests.post(
                self.url,
                json={"chat_id": self.chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=20,
            )
            r.raise_for_status()


class WebhookNotifier(Notifier):
    """디스코드(content) / 슬랙(text) 웹훅."""

    def __init__(self, url: str, kind: str = "discord"):
        self.url = url
        self.kind = kind

    def send(self, text: str) -> None:
        limit = 1900 if self.kind == "discord" else 3500
        key = "content" if self.kind == "discord" else "text"
        for chunk in _chunks(text, limit):
            r = requests.post(self.url, json={key: chunk}, timeout=20)
            r.raise_for_status()


class EmailNotifier(Notifier):
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        to: str | list[str],
        sender: str | None = None,
        use_ssl: bool = True,
    ):
        self.host, self.port = host, int(port)
        self.username, self.password = username, password
        self.to = [to] if isinstance(to, str) else list(to)
        self.sender = sender or username
        self.use_ssl = use_ssl

    def send(self, text: str) -> None:
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = text.split("\n", 1)[0]
        msg["From"] = formataddr(("경매알리미", self.sender))
        msg["To"] = ", ".join(self.to)
        if self.use_ssl:
            smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=30)
            smtp.starttls()
        with smtp:
            smtp.login(self.username, self.password)
            smtp.sendmail(self.sender, self.to, msg.as_string())


def build_notifiers(cfg: dict) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if cfg.get("console", True):
        notifiers.append(ConsoleNotifier())
    if (t := cfg.get("telegram")) and t.get("bot_token") and t.get("chat_id"):
        notifiers.append(TelegramNotifier(t["bot_token"], str(t["chat_id"])))
    if (e := cfg.get("email")) and e.get("host") and e.get("to"):
        notifiers.append(EmailNotifier(**e))
    for kind in ("discord", "slack"):
        if (w := cfg.get(kind)) and w.get("webhook_url"):
            notifiers.append(WebhookNotifier(w["webhook_url"], kind))
    return notifiers


def notify_all(notifiers: list[Notifier], text: str) -> int:
    """모든 채널로 보낸다. 실패한 채널 수를 반환."""
    failed = 0
    for n in notifiers:
        try:
            n.send(text)
        except Exception as e:  # 한 채널이 실패해도 나머지는 보낸다
            failed += 1
            log.error("%s 알림 실패: %s", type(n).__name__, e)
    return failed
