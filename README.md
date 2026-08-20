# AI ARR Tracker — AI 모델 기업 연환산 매출 추적 사이트

OpenAI·Anthropic·Google(Gemini)·xAI·Mistral·Cohere·DeepSeek·Moonshot·Z.ai·Microsoft AI·Meta의 연환산 매출(ARR)을 **월 단위**로 정리하고, 합산 ARR을 철도·전력·전화·자동차·제약·무선통신·인터넷 광고·전자상거래·클라우드·스마트폰의 성장 곡선과 비교하는 정적 웹사이트입니다. 외부 라이브러리·CDN 의존 없이 `index.html` 한 파일로 동작합니다(폰트·데이터 내장).

## 폴더 구성

| 파일 | 역할 |
|---|---|
| `data.json` | **유일한 데이터 원본.** 회사별 ARR 포인트(날짜·값·출처 URL·구분), Google 추정 입력, 산업 시계열, CPI·GDP 디플레이터, 변경 이력 |
| `template.html` | 사이트 템플릿(디자인·차트 엔진·해설 문구) |
| `build.py` | `data.json` → 월별 보간·합산·지표 계산 → `index.html`, `computed.json`, `exports/*.csv` 생성 |
| `index.html` | **빌드 결과물(배포 대상).** 단독으로 열어도 동작 |
| `exports/` | 월별 ARR CSV, 출처 로그 CSV, 산업 시계열 CSV (사이트의 내려받기 링크 대상) |
| `scripts/update_monthly.py` | 매월 1일 자동 실행: Epoch AI 데이터셋에서 새 보고 수집 → `data.json`에 '검토 필요' 표시로 추가 → 날짜 메타·변경 이력 갱신 |
| `.github/workflows/monthly-update.yml` | GitHub Actions: 매월 1일 갱신 + 빌드 + GitHub Pages 배포 (push 시에도 빌드·배포) |
| `fonts/` | 내장용 웹폰트(Barlow Semi Condensed, IBM Plex Mono — OFL) |

## 1. 공개하기 (GitHub Pages, 무료)

1. GitHub에서 새 저장소를 만들고 이 폴더 전체를 올립니다(`main` 브랜치).
2. 저장소 **Settings → Pages → Build and deployment → Source** 를 **GitHub Actions** 로 선택합니다.
3. **Actions** 탭에서 `monthly-update-and-deploy` 워크플로를 한 번 수동 실행(Run workflow)하거나, 아무 커밋이나 push 합니다.
4. 1~2분 뒤 `https://<계정명>.github.io/<저장소명>/` 에서 사이트가 열립니다. 커스텀 도메인은 Settings → Pages에서 연결.

Netlify/Vercel/Cloudflare Pages를 쓴다면 빌드 명령 `python3 build.py`, 공개 폴더는 저장소 루트(`index.html`, `exports/`)로 지정하면 됩니다. 가장 단순하게는 `index.html`과 `exports/` 폴더만 아무 정적 호스팅에 올려도 됩니다.

## 2. 매월 1일 자동 갱신 — 무엇이 자동이고 무엇이 수동인가

워크플로가 매월 1일 00:15 UTC(한국 09:15)에 실행되어:

- **자동**: Epoch AI의 [AI companies revenue reports](https://epoch.ai/data/ai_companies_revenue_reports.csv)(CC-BY)에서 회사별 마지막 포인트 이후의 새 보고(신뢰도 Confident/Likely, 전사 기준)를 가져와 `data.json`에 추가합니다. 추가된 포인트는 사이트 출처 로그에 **'검토 필요'** 배지로 표시됩니다. 날짜 메타(마지막 업데이트·데이터 기준월·다음 업데이트)와 변경 이력도 갱신되고, 사이트가 다시 빌드·배포됩니다. 새 보고가 없어도 '최근값 유지' 기간이 한 달 연장된 상태로 재배포됩니다.
- **수동(분기 1회 권장, 1·4·7·10월 말 실적 시즌 후)**:
  - Google 추정 입력값: Alphabet 실적의 API 토큰/분, Gemini 구독·Enterprise 시트 → `data.json`의 `google.points`에 새 `estimate` 포인트 추가(`range` 포함).
  - Microsoft AI 런레이트(공시 시), Meta 구독 매출(공개 시).
  - Epoch에 아직 반영되지 않은 Bloomberg/CNBC/The Information 보도.
  - 자동 추가된 '검토 필요' 포인트 확인 후 `"review": true` 삭제(또는 값·출처 수정).

자동 수집 결과 보고서는 `updates/YYYY-MM-DD.md`에 쌓입니다.

## 3. 수동으로 데이터 추가·수정하기

`data.json`의 해당 회사 `points` 배열에 한 줄 추가 → `python3 build.py` → 커밋/푸시(Pages면 자동 배포).

```json
{"date": "2026-09-15", "value": 5.0e10, "kind": "media",
 "src": "https://...", "src_label": "Bloomberg", "note": "9월 중순 $50B"}
```

- `kind`: `disclosure`(회사 공시) / `media`(보도) / `estimate`(추정) / `derived`(파생 계산)
- 같은 달에 포인트가 여럿이면 가장 늦은 날짜 값을 그 달 값으로 씁니다. 보고 사이는 로그 선형 보간, 마지막 보고 이후는 최대 12개월 최근값 유지(점선).
- 새 회사 추가: `companies` 배열에 객체 추가(`in_total`로 합산 포함 여부, `group`은 `lab`/`bigtech`).
- 산업 시계열 수정: `industries[].points` 는 `[연도, 명목 $B]`. CPI·GDP 표를 연장하면 실질·GDP% 자동 반영.

빌드 결과의 핵심 지표(합산·도달 시점·산업별 10B→100B 소요 연수)는 `build.py` 실행 시 콘솔에 출력되므로 수치 검증에 쓰면 됩니다.

## 4. 로컬 미리보기

```bash
python3 build.py          # index.html 생성
python3 -m http.server    # http://localhost:8000 (CSV 링크까지 확인하려면 서버로 열기)
```

`index.html`을 그냥 더블클릭해도 차트는 모두 동작합니다(CSV 내려받기 링크만 서버 필요).

## 5. 정의와 한계 (사이트 06 섹션과 동일)

- ARR = 최근 월 매출×12 등 '현재 속도'. 1년 인식 매출(GAAP)보다 큽니다. 회사별 정의가 다르고 대부분 익명 소식통 보도입니다.
- 합산(기본)은 공시·보도 기반 모델 랩만. Google은 비공시라 자체 추정(±50% 이상), Microsoft AI는 플랫폼 매출이라 참고선, Meta는 직접 모델 매출 없음.
- 산업 시계열은 매출 성격(상품 거래액 vs 서비스 매출)·지역(미국 vs 글로벌)이 다르고, 1950년 이전은 ±20~30% 근사치입니다.

라이선스: 데이터 출처는 각 링크 참조(Epoch AI 데이터셋은 CC-BY 4.0). 코드와 사이트 구성은 자유롭게 수정해 쓰셔도 됩니다.
