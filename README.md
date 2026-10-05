# kyungmae — 대법원 경매 새 물건 알리미

[법원경매정보(courtauction.go.kr)](https://www.courtauction.go.kr)를 매일 조회해서
**내가 정한 조건에 맞는 새 경매 물건**이 나오면 텔레그램 / 이메일 / 디스코드 / 슬랙으로 알려줍니다.

- 지역, 용도(아파트·다세대·토지 …), 감정가·최저가 범위, 유찰 횟수, 최저가율(%),
  면적, 매각기일, 법원, 위험 물건 제외(대항력 임차인·지분·유치권 …) 조건을 골라 쓸 수 있습니다.
- 한 번 알린 물건은 다시 알리지 않습니다. 단, **유찰되어 최저가가 내려가면 다시 알립니다.**
- 조건(watch)을 여러 개 등록할 수 있습니다.

## 동작 방식

1. **서버 검색**: `config.yaml`의 `search.queries`(지역·법원 등)로 오늘부터 `days_ahead`일 뒤까지의
   매각기일 물건을 모두 가져옵니다.
2. **조건 필터**: `watches`의 조건(주소·용도 키워드, 가격, 유찰 횟수 등)으로 거릅니다.
3. **중복 제거**: `data/seen.json`에 없는 물건만 알리고 기록합니다.

## 설치 & 실행

```bash
pip install -r requirements.txt

# 1) config.yaml 에서 search.queries 와 watches 를 내 조건으로 수정
# 2) 알림 없이 결과만 확인
python -m kyungmae --dry-run

# 3) 알림 채널 테스트 (환경변수 설정 후)
export TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
python -m kyungmae --test-notify

# 4) 실제 실행
python -m kyungmae
```

## 매일 자동 실행

### 방법 A. GitHub Actions (PC를 켜둘 필요 없음)

`.github/workflows/daily.yml`이 **매일 오전 8시(KST)** 에 실행됩니다.

1. 저장소 → Settings → Secrets and variables → Actions 에서 사용할 채널의 값을 등록
   - 텔레그램: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - 이메일: `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO`
   - 디스코드/슬랙: `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`
2. Actions 탭 → "경매 알리미 (매일)" → **Run workflow** 로 한 번 수동 실행해서 확인
3. 알림 기록(`data/seen.json`)은 워크플로가 자동으로 커밋합니다.

> ⚠️ 법원경매정보 사이트가 해외 IP(GitHub 서버는 미국)를 막으면 Actions 에서는 조회가 실패할 수 있습니다.
> 그럴 때는 방법 B 처럼 국내 PC/서버에서 실행하세요.

### 방법 B. 내 PC / 서버의 스케줄러

- **Linux / macOS (cron)** — `crontab -e`
  ```
  0 8 * * * cd /경로/kyungmae && /usr/bin/python3 -m kyungmae >> data/run.log 2>&1
  ```
  (환경변수는 crontab 맨 위에 `TELEGRAM_BOT_TOKEN=...` 형태로 적거나, `config.yaml`에 직접 입력)
- **Windows** — 작업 스케줄러 → 기본 작업 만들기 → 매일 08:00 →
  프로그램 `python`, 인수 `-m kyungmae`, 시작 위치 `C:\경로\kyungmae`

## 알림 채널 설정

| 채널 | 준비 방법 |
|---|---|
| 텔레그램 (추천) | [@BotFather](https://t.me/BotFather) 에서 `/newbot` → 토큰 발급. 봇에게 아무 메시지 보낸 뒤 `https://api.telegram.org/bot<토큰>/getUpdates` 에서 `chat.id` 확인 |
| 이메일 | 네이버: 메일 설정 → POP3/SMTP 사용 → `smtp.naver.com:465`, 지메일: 2단계 인증 후 *앱 비밀번호* 발급 → `smtp.gmail.com:465` |
| 디스코드 | 채널 설정 → 연동 → 웹후크 만들기 → URL 복사 |
| 슬랙 | Incoming Webhooks 앱 추가 → URL 복사 |

## 조건 작성 예시

```yaml
watches:
  - name: 마포·용산 소형 아파트
    address_keywords: [마포구, 용산구]
    usage_keywords: [아파트, 오피스텔]
    exclude_risks: [대항력임차인, 선순위권리, 지분매각, 유치권]
    min_price_max: 800000000      # 최저가 8억 이하
    fail_count_min: 1             # 1회 이상 유찰
    area_min: 59                  # 59㎡ ~ 85㎡
    area_max: 85

  - name: 제주 토지 반값
    address_keywords: [제주]
    usage_keywords: [대지, 전, 답, 임야]
    exclude_risks: [지분매각, 법정지상권, 분묘기지권]
    max_ratio: 50                 # 최저가가 감정가의 50% 이하
    sale_within_days: 7           # 7일 안에 입찰하는 것만
```

### 골라 쓸 수 있는 조건

| 항목 | 설명 |
|---|---|
| `address_keywords` | 주소에 하나라도 포함 |
| `usage_keywords` | 법원이 표기한 용도에 하나라도 포함 |
| `usage_in_address` | `true`면 주소·건물명에서도 용도 키워드를 찾음 (기본 `false`) |
| `courts` | 담당 법원 이름 일부 |
| `exclude_keywords` | 주소/용도/비고에 이 문구가 있으면 제외 (자유 입력) |
| `exclude_risks` | 위험 물건 제외 (아래 표에서 선택) |
| `appraisal_min` / `appraisal_max` | 감정가 범위 (원) |
| `min_price_min` / `min_price_max` | 최저매각가 범위 (원) |
| `fail_count_min` / `fail_count_max` | 유찰 횟수 범위 |
| `min_ratio` / `max_ratio` | 최저가/감정가 비율(%) 범위 |
| `area_min` / `area_max` | 면적(㎡) 범위. 면적을 알 수 없는 물건은 제외 |
| `sale_within_days` | 매각기일이 오늘부터 N일 안인 것만 |

`exclude_risks`에 쓸 수 있는 값 (물건비고·주소·용도에서 해당 문구를 찾아 제외):

| 값 | 찾는 문구 |
|---|---|
| `대항력임차인` | 대항할 수 있는 임차인 |
| `선순위권리` | 선순위, 매수인이 인수 |
| `지분매각` | 지분 |
| `유치권` | 유치권 |
| `법정지상권` | 법정지상권 |
| `대지권미등기` | 대지권미등기, 대지권 없음 |
| `토지별도등기` | 토지별도등기 |
| `위반건축물` | 위반건축물 |
| `재매각` | 재매각, 매수보증금 20% |
| `분묘기지권` | 분묘 |

> 물건비고에 적힌 문구로만 판단하므로 위험이 모두 걸러지는 것은 아닙니다.
> 입찰 전에는 반드시 매각물건명세서·현황조사서를 직접 확인하세요.

## 문제 해결

- **검색 결과가 0건이거나 오류가 날 때**: 사이트 개편으로 API 필드가 바뀌었을 수 있습니다.
  `python -m kyungmae --dry-run --dump raw.json -v` 로 원본 응답을 저장해 확인하고,
  요청 필드는 `search.extra_params`로 덮어쓸 수 있습니다. 응답 필드명 매핑은
  `kyungmae/client.py`의 `parse_item()`에 있습니다.
- **검색이 너무 오래 걸릴 때**: `search.queries`에 `sido_code`, `usage_large`(건물 20000 / 토지 10000),
  `min_price_max` 등 서버 검색 조건을 넣어 범위를 줄이세요. (서울 건물 2주치 ≈ 3,000건 ≈ 80페이지)
- **"잠시 후 다시 이용해 주십시오" 오류**: 요청이 많을 때 사이트가 돌려주는 오류로, 자동으로 몇 번 재시도합니다.
  자주 나면 `delay_seconds`를 늘리세요.
- 사이트에 부담을 주지 않도록 하루 1~2회 정도만 실행하는 것을 권장합니다.

## 테스트

```bash
pip install pytest && python -m pytest -q
```
