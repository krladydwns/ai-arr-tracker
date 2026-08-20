#!/usr/bin/env python3
"""월간 자동 업데이트 스크립트 (매월 1일 GitHub Actions에서 실행).

1. Epoch AI 'AI companies revenue reports' CSV(CC-BY)를 내려받아
2. data.json에 없는 새 보고(회사별 마지막 포인트 이후 날짜)를 찾아
3. kind=media, review=true(검토 필요) 로 추가하고
4. meta.last_updated / data_through / next_update 와 changelog를 갱신한 뒤
5. updates/YYYY-MM-DD.md 에 변경 보고서를 남깁니다.

자동 추가된 포인트는 사이트 출처 로그에 '검토 필요' 배지로 표시됩니다.
사람이 확인 후 review 플래그를 지우거나 값을 수정하면 됩니다.

사용: python3 scripts/update_monthly.py [--dry-run] [--csv path]
"""
import csv, io, json, re, sys, datetime as dt, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data.json"
EPOCH_URL = "https://epoch.ai/data/ai_companies_revenue_reports.csv"

NAME_MAP = {
    "anthropic": "anthropic", "openai": "openai", "xai": "xai", "mistral": "mistral", "mistral ai": "mistral",
    "cohere": "cohere", "deepseek": "deepseek", "moonshot": "moonshot", "moonshot ai": "moonshot",
    "zhipu": "zhipu", "zhipu ai": "zhipu", "z.ai": "zhipu", "z.ai (zhipu)": "zhipu", "microsoft": "microsoft",
}
MIN_CONFIDENCE = {"confident", "likely"}  # Epoch 'Confidence' 열 기준 (Speculative 제외)

def fetch_csv(path=None):
    if path:
        return Path(path).read_text(encoding="utf-8")
    req = urllib.request.Request(EPOCH_URL, headers={"User-Agent": "ai-arr-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")

def main():
    dry = "--dry-run" in sys.argv
    csv_path = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in data["companies"]}
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).date()  # KST 기준 날짜
    report = [f"# 월간 업데이트 보고서 {today.isoformat()}", ""]

    try:
        text = fetch_csv(csv_path)
    except Exception as e:  # 네트워크 실패 시에도 날짜 메타는 갱신
        report.append(f"Epoch CSV 다운로드 실패: {e}")
        text = ""

    added, unknown = [], set()
    if text:
        rows = list(csv.DictReader(io.StringIO(text)))
        for r in rows:
            name = (r.get("Company") or "").strip()
            key = re.sub(r"\s*\(.*?\)\s*", " ", name.lower()).strip()  # "Z.ai (Zhipu)" -> "z.ai"
            cid = NAME_MAP.get(key) or NAME_MAP.get(name.lower())
            if not cid:
                for k, v in NAME_MAP.items():
                    if k in key.split() or key.startswith(k + " "):
                        cid = v; break
            if not cid:
                unknown.add(name); continue
            if (r.get("Annualized revenue type") or "").lower().find("run rate") < 0 and (r.get("Annualized revenue type") or "") != "":
                pass  # 연간 매출도 연환산으로 쓰되 note에 유형을 남김
            scope = (r.get("Scope") or "").lower()
            if scope and "full company" not in scope:
                continue
            conf = (r.get("Confidence") or "").strip().lower()
            if conf and conf not in MIN_CONFIDENCE:
                continue
            date = (r.get("Date") or "").strip()[:10]
            try:
                val = float(r.get("Annualized revenue (USD)") or 0)
            except ValueError:
                continue
            if not date or val <= 0:
                continue
            c = by_id[cid]
            last = max((p["date"] for p in c["points"]), default="0000-00-00")
            if date <= last or any(p["date"] == date for p in c["points"]):
                continue
            pt = {
                "date": date, "value": val, "kind": "media",
                "src": (r.get("Source 1") or "").strip(), "src_label": "Epoch AI 데이터셋 경유 (자동 수집)",
                "note": f"[자동 수집 — 검토 필요] {(r.get('Annualized revenue type') or '').strip()} / {(r.get('Notes') or '').strip()[:160]}",
                "review": True,
            }
            c["points"].append(pt)
            c["points"].sort(key=lambda p: p["date"])
            added.append((c["name"], date, val))
            by_id[cid] = c

    # meta 갱신
    data["meta"]["last_updated"] = today.isoformat()
    # 월초(1~7일) 실행 시 '데이터 기준월'은 직전 달 (해당 월은 아직 데이터가 없음)
    ref = (today.replace(day=1) - dt.timedelta(days=1)) if today.day <= 7 else today
    data["meta"]["data_through"] = ref.strftime("%Y-%m")
    nxt = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    data["meta"]["next_update"] = nxt.isoformat()
    if added:
        txt = "자동 수집: " + ", ".join(f"{n} {d} ${v/1e9:.2f}B" for n, d, v in added) + " (검토 필요)"
    else:
        txt = "자동 갱신: 새 보고 없음, 최근값 유지 기간 연장"
    data["changelog"].insert(0, {"date": today.isoformat(), "text": txt})

    report.append(f"추가된 포인트: {len(added)}")
    for n, d, v in added:
        report.append(f"- {n} {d} ${v/1e9:.3f}B")
    if unknown:
        report.append("")
        report.append("매핑되지 않은 회사(수동 검토): " + ", ".join(sorted(u for u in unknown if u)))
    report.append("")
    report.append("수동 확인 항목: Google 추정 입력값(분기 실적), Microsoft AI 런레이트, Meta 구독 매출 공개 여부, 뉴스 기반 새 보도(Bloomberg/CNBC/The Information).")

    out = "\n".join(report)
    print(out)
    if not dry:
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        upd = ROOT / "updates"; upd.mkdir(exist_ok=True)
        (upd / f"{today.isoformat()}.md").write_text(out, encoding="utf-8")

if __name__ == "__main__":
    main()
