#!/usr/bin/env python3
"""Build index.html from data.json + template.html.

Usage: python3 build.py
Outputs: index.html, computed.json, exports/arr_monthly.csv, exports/arr_sources.csv
"""
import base64, csv, json, math, os, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
META = DATA["meta"]
BASE_YEAR = META.get("base_year_real", 2024)
CARRY_MAX = 12  # months to carry the last reported value forward

# ---------------------------------------------------------------- helpers
def ym_to_idx(ym):
    y, m = map(int, ym.split("-"))
    return y * 12 + (m - 1)

def idx_to_ym(i):
    return f"{i // 12}-{i % 12 + 1:02d}"

def idx_to_decimal(i):
    return i // 12 + (i % 12 + 0.5) / 12.0

def date_to_idx(d):
    return ym_to_idx(d[:7])

def interp_log(x0, y0, x1, y1, x):
    if x1 == x0:
        return y1
    t = (x - x0) / (x1 - x0)
    return math.exp(math.log(y0) + t * (math.log(y1) - math.log(y0)))

def table_interp(table, year, log=True):
    """Interpolate a {year: value} table at `year` (log-linear by default)."""
    ys = sorted(int(k) for k in table)
    if year <= ys[0]:
        return float(table[str(ys[0])])
    if year >= ys[-1]:
        return float(table[str(ys[-1])])
    for a, b in zip(ys, ys[1:]):
        if a <= year <= b:
            va, vb = float(table[str(a)]), float(table[str(b)])
            if log:
                return interp_log(a, va, b, vb, year)
            return va + (vb - va) * (year - a) / (b - a)
    return float(table[str(ys[-1])])

CPI = DATA["cpi"]
GDP = DATA["gdp_usd_b"]
CPI_BASE = table_interp(CPI, BASE_YEAR)

def to_real(v, year):
    return v * CPI_BASE / table_interp(CPI, year)

def to_gdp_pct(v_b, year):
    return v_b / table_interp(GDP, year) * 100.0

# ---------------------------------------------------------------- monthly grid
start_i = ym_to_idx(META["grid_start"])
end_i = ym_to_idx(META["data_through"])
months = [idx_to_ym(i) for i in range(start_i, end_i + 1)]
N = len(months)

companies_out = []
for c in DATA["companies"]:
    pts = sorted(c["points"], key=lambda p: p["date"])
    anchors = {}  # month idx -> point (last in month wins)
    for p in pts:
        anchors[date_to_idx(p["date"])] = p
    values = [None] * N
    status = [None] * N
    keys = sorted(anchors)
    for k, i in enumerate(keys):
        if start_i <= i <= end_i:
            p = anchors[i]
            values[i - start_i] = p["value"]
            status[i - start_i] = "estimate" if p["kind"] in ("estimate", "derived") else "reported"
        if k + 1 < len(keys):
            j = keys[k + 1]
            for m in range(i + 1, j):
                if start_i <= m <= end_i:
                    values[m - start_i] = interp_log(i, anchors[i]["value"], j, anchors[j]["value"], m)
                    status[m - start_i] = "interp"
    if keys:
        last = keys[-1]
        for m in range(last + 1, min(end_i, last + CARRY_MAX) + 1):
            if m >= start_i:
                values[m - start_i] = anchors[last]["value"]
                status[m - start_i] = "carry"
    companies_out.append({
        "id": c["id"], "name": c["name"], "name_ko": c["name_ko"], "group": c["group"],
        "in_total": c["in_total"], "est": c["est"], "color": c["color"], "note_ko": c["note_ko"],
        "values": values, "status": status,
        "points": [{"date": p["date"], "value": p["value"], "kind": p["kind"], "src": p.get("src", ""),
                    "src_label": p.get("src_label", ""), "note": p.get("note", ""), "range": p.get("range"), "review": p.get("review", False)} for p in pts],
        "last_point": pts[-1] if pts else None,
    })

by_id = {c["id"]: c for c in companies_out}

def month_total(m, with_google=False):
    s, n, have = 0.0, 0, False
    for c in companies_out:
        if c["in_total"] and c["values"][m] is not None:
            s += c["values"][m]; n += 1; have = True
    if with_google and by_id["google"]["values"][m] is not None:
        s += by_id["google"]["values"][m]
    return (s if have else None), n

totals = [month_total(m)[0] for m in range(N)]
totals_est = [month_total(m, True)[0] for m in range(N)]
coverage = [month_total(m)[1] for m in range(N)]

def pct(a, b):
    return None if (a is None or b is None or b == 0) else (a / b - 1) * 100

latest = N - 1
kpis = {
    "month": months[latest],
    "total": totals[latest],
    "total_est": totals_est[latest],
    "mom": pct(totals[latest], totals[latest - 1]),
    "qoq": pct(totals[latest], totals[latest - 3]),
    "yoy": pct(totals[latest], totals[latest - 12]),
    "yoy2": pct(totals[latest], totals[latest - 24]),
}
# doubling time from trailing 6 months
g6 = (totals[latest] / totals[latest - 6]) ** (1 / 6) - 1 if totals[latest - 6] else None
kpis["doubling_months"] = (math.log(2) / math.log(1 + g6)) if g6 and g6 > 0 else None
kpis["top"] = sorted([(c["name"], c["values"][latest]) for c in companies_out if c["in_total"] and c["values"][latest]],
                     key=lambda t: -t[1])[:3]
kpis["share_top2"] = None
if totals[latest]:
    a = by_id["anthropic"]["values"][latest] or 0
    o = by_id["openai"]["values"][latest] or 0
    kpis["share_top2"] = (a + o) / totals[latest] * 100

# ---------------------------------------------------------------- AI as an "industry" (annual + monthly real)
ai_monthly_real = []
for m in range(N):
    y = idx_to_decimal(start_i + m)
    ai_monthly_real.append(None if totals[m] is None else to_real(totals[m] / 1e9, y))

def crossing_month(series_b, threshold):
    """first fractional month index where series (in $B) crosses threshold (log interp)."""
    prev = None
    for m, v in enumerate(series_b):
        if v is None:
            prev = None; continue
        if prev is not None and prev < threshold <= v:
            pm, pv = prev_m, prev
            t = (math.log(threshold) - math.log(pv)) / (math.log(v) - math.log(pv))
            return pm + t * (m - pm)
        if v >= threshold and prev is None and m == 0:
            return 0.0
        prev, prev_m = v, m
    return None

ai_cross10 = crossing_month(ai_monthly_real, 10)
ai_cross100 = crossing_month(ai_monthly_real, 100)
ai_cross1 = crossing_month(ai_monthly_real, 1)

def month_frac_to_decimal(mf):
    return None if mf is None else idx_to_decimal(start_i) + mf / 12.0

# ---------------------------------------------------------------- industries
def annual_series(points):
    """Return dict year->nominal for all integer years between first and last (log-interp)."""
    ys = [p[0] for p in points]
    out = {}
    for y in range(ys[0], ys[-1] + 1):
        for (a, va), (b, vb) in zip(points, points[1:]):
            if a <= y <= b:
                out[y] = interp_log(a, va, b, vb, y); break
        else:
            out[y] = points[-1][1] if y >= ys[-1] else points[0][1]
    return out

def first_cross(series, thr):
    years = sorted(series)
    for a, b in zip(years, years[1:]):
        if series[a] < thr <= series[b]:
            t = (math.log(thr) - math.log(series[a])) / (math.log(series[b]) - math.log(series[a]))
            return a + t
    if series[years[0]] >= thr:
        return float(years[0])  # already above at start (flag as <=)
    return None

industries_out = []
for ind in DATA["industries"]:
    pts = ind["points"]
    nominal = annual_series(pts)
    real = {y: to_real(v, y) for y, v in nominal.items()}
    gdp = {y: to_gdp_pct(v, y) for y, v in nominal.items()}
    c10, c100 = first_cross(real, 10), first_cross(real, 100)
    first_year = min(real)
    c10_flag = "<=" if (c10 is not None and c10 == first_year and real[first_year] >= 10) else ""
    # growth phase CAGR between 10B and 100B
    cagr = None
    if c10 is not None and c100 is not None and c100 > c10:
        cagr = (10 ** (1 / (c100 - c10)) - 1) * 100
    # maturity: first year after (c100 or c10) where trailing 10y real CAGR < 3%
    mature = None
    ref = c100 if c100 else c10
    if ref:
        for y in sorted(real):
            if y >= ref + 10 and (y - 10) in real and real[y - 10] > 0:
                r = (real[y] / real[y - 10]) ** (1 / 10) - 1
                if r < 0.03:
                    mature = y; break
    peak_year = max(real, key=lambda y: real[y])
    last_year = max(real)
    industries_out.append({
        "id": ind["id"], "name_ko": ind["name_ko"], "name_en": ind["name_en"], "metric_ko": ind["metric_ko"],
        "t0": ind["t0"], "t0_label": ind["t0_label"], "color": ind["color"], "source": ind["source"], "note": ind.get("note", ""),
        "raw": pts,
        "nominal": [[y, round(v, 4)] for y, v in sorted(nominal.items())],
        "real": [[y, round(v, 4)] for y, v in sorted(real.items())],
        "gdp": [[y, round(v, 5)] for y, v in sorted(gdp.items())],
        "cross10": c10, "cross10_flag": c10_flag, "cross100": c100, "cagr_10_100": cagr,
        "mature_year": mature, "peak_year": peak_year, "peak_real": real[peak_year],
        "last_year": last_year, "last_real": real[last_year], "last_nominal": nominal[last_year], "last_gdp": gdp[last_year],
        "years_10_100": (c100 - c10) if (c10 and c100) else None,
    })

# AI pseudo-industry record
ai_real_latest = ai_monthly_real[latest]
ai_record = {
    "id": "ai", "name_ko": "AI 모델 랩 (합산)", "name_en": "AI model labs (combined ARR)",
    "metric_ko": "추적 대상 모델 랩 합산 ARR (Google 추정 제외)", "t0": 2022.9, "t0_label": "ChatGPT 출시 (2022.11)", "color": "#0F1B2D",
    "monthly_real": [[round(idx_to_decimal(start_i + m), 4), (None if v is None else round(v, 4))] for m, v in enumerate(ai_monthly_real)],
    "monthly_nominal": [[round(idx_to_decimal(start_i + m), 4), (None if v is None else round(v / 1e9, 4))] for m, v in enumerate(totals)],
    "monthly_gdp": [[round(idx_to_decimal(start_i + m), 4), (None if v is None else round(to_gdp_pct(v / 1e9, idx_to_decimal(start_i + m)), 5))] for m, v in enumerate(totals)],
    "cross1": month_frac_to_decimal(ai_cross1), "cross10": month_frac_to_decimal(ai_cross10), "cross100": month_frac_to_decimal(ai_cross100),
    "last_real": ai_real_latest, "last_nominal": totals[latest] / 1e9 if totals[latest] else None,
    "last_gdp": to_gdp_pct(totals[latest] / 1e9, idx_to_decimal(end_i)) if totals[latest] else None,
}
if ai_record["cross10"] and ai_record["cross100"]:
    ai_record["years_10_100"] = ai_record["cross100"] - ai_record["cross10"]
    ai_record["cagr_10_100"] = (10 ** (1 / ai_record["years_10_100"]) - 1) * 100
else:
    ai_record["years_10_100"] = None; ai_record["cagr_10_100"] = None

# ---------------------------------------------------------------- sources log
sources = []
for c in DATA["companies"]:
    for p in c["points"]:
        sources.append({"date": p["date"], "company": c["name"], "cid": c["id"], "value": p["value"], "kind": p["kind"],
                        "src": p.get("src", ""), "src_label": p.get("src_label", ""), "note": p.get("note", ""), "review": p.get("review", False)})
sources.sort(key=lambda s: s["date"], reverse=True)

computed = {
    "meta": META, "months": months, "companies": companies_out, "totals": totals, "totals_est": totals_est,
    "coverage": coverage, "kpis": kpis, "industries": industries_out, "ai": ai_record, "sources": sources,
    "cpi": CPI, "gdp": GDP, "base_year": BASE_YEAR, "changelog": DATA.get("changelog", []),
    "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
}
(ROOT / "computed.json").write_text(json.dumps(computed, ensure_ascii=False), encoding="utf-8")

# ---------------------------------------------------------------- CSV exports
exp = ROOT / "exports"; exp.mkdir(exist_ok=True)
with open(exp / "arr_monthly.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    ids = [c["id"] for c in companies_out if c["points"]]
    w.writerow(["month", "total_labs_usd_b", "total_with_google_est_usd_b"] + [f"{i}_usd_b" for i in ids] + [f"{i}_status" for i in ids])
    for m, ym in enumerate(months):
        row = [ym, "" if totals[m] is None else round(totals[m] / 1e9, 4), "" if totals_est[m] is None else round(totals_est[m] / 1e9, 4)]
        row += ["" if by_id[i]["values"][m] is None else round(by_id[i]["values"][m] / 1e9, 4) for i in ids]
        row += [by_id[i]["status"][m] or "" for i in ids]
        w.writerow(row)
with open(exp / "arr_sources.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["date", "company", "annualized_revenue_usd", "kind", "source_label", "source_url", "note"])
    for s in sources:
        w.writerow([s["date"], s["company"], int(s["value"]), s["kind"], s["src_label"], s["src"], s["note"]])
with open(exp / "industries_annual.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["industry_id", "industry", "year", "nominal_usd_b", f"real_{BASE_YEAR}_usd_b", "pct_of_us_gdp"])
    for ind in industries_out:
        g = dict((y, v) for y, v in ind["gdp"])
        r = dict((y, v) for y, v in ind["real"])
        for y, v in ind["nominal"]:
            w.writerow([ind["id"], ind["name_en"], y, v, r[y], g[y]])

# ---------------------------------------------------------------- HTML
def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()

fonts = ROOT / "fonts"
font_css = ""
for fam, fn, wt in [("Barlow Semi Condensed", "barlow-semi-condensed-latin-600-normal.woff2", 600),
                    ("Barlow Semi Condensed", "barlow-semi-condensed-latin-500-normal.woff2", 500),
                    ("IBM Plex Mono", "ibm-plex-mono-latin-400-normal.woff2", 400),
                    ("IBM Plex Mono", "ibm-plex-mono-latin-600-normal.woff2", 600)]:
    p = fonts / fn
    if p.exists():
        font_css += f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{wt};font-display:swap;src:url(data:font/woff2;base64,{b64(p)}) format('woff2');}}\n"

tpl = (ROOT / "template.html").read_text(encoding="utf-8")
html = tpl.replace("/*__FONTS__*/", font_css).replace("__DATA_JSON__", json.dumps(computed, ensure_ascii=False).replace("</", "<\\/"))
(ROOT / "index.html").write_text(html, encoding="utf-8")
print(f"built index.html: {len(html)/1024:.0f} KB | months={N} | total latest={totals[latest]/1e9:.1f}B | est incl={totals_est[latest]/1e9:.1f}B")
print("AI cross $10B real:", ai_record["cross10"], " $100B:", ai_record["cross100"])
for ind in industries_out:
    print(f"  {ind['name_ko']:<8} 10B={ind['cross10'] and round(ind['cross10'],1)} 100B={ind['cross100'] and round(ind['cross100'],1)} "
          f"yrs={ind['years_10_100'] and round(ind['years_10_100'],1)} cagr={ind['cagr_10_100'] and round(ind['cagr_10_100'],1)} mature={ind['mature_year']} peak={ind['peak_year']}")
