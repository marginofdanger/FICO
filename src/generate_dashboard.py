"""
generate_dashboard.py — master.json + template.html -> output/dashboard.html

Builds the JS data literals (M, PROD, LENDERS, CROSS, LMONTH) from master.json
and injects them at the //__DATA__ marker in template.html. Output is pure ASCII
(numbers + ASCII names), so it publishes cleanly as an Artifact.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(HERE, "..", "master.json")
TEMPLATE = os.path.join(HERE, "template.html")
OUT = os.path.join(HERE, "..", "output", "dashboard.html")

NAMEMAP = {'UNITED WHOLESALE MORTGAGE, LLC': 'United Wholesale Mortgage',
           'ROCKET MORTGAGE, LLC': 'Rocket Mortgage', 'NEWREZ LLC': 'NewRez'}
def short(n):
    if n in NAMEMAP:
        return NAMEMAP[n]
    t = n.title()
    for suf in (', National Association', ' National Association', ', Inc.', ', Ltd.',
                ', Llc', ' Llc', ', Company', ' Company', ' Corporation'):
        t = t.replace(suf, '')
    return t.strip().rstrip(',')

def js_data(m):
    series = m['series']; months = m['months']
    lines = ["// per month arrays: [base_upb, base_loans, wa_fico, vs_upb, vs_upb_pct, vs_loans, vs_loan_pct, n_vs_pools] -- LOAN-LEVEL",
             "const M=["]
    for s in series:
        lines.append(f' {{l:"{s["short"]}",m:"{s["label"]}",f:{json.dumps(s["f"])},r:{json.dumps(s["r"])},t:{json.dumps(s["t"])}}},')
    lines.append("];")

    # product per month (standard term buckets, sorted by penetration desc)
    def pblock(ym):
        pj = m['product'][ym]
        rows = sorted([(k, v) for k, v in pj.items() if k in ('30yr', '20yr', '15yr', '10yr')],
                      key=lambda kv: -kv[1]['pct'])
        return "[" + ",".join(f'{{p:"{k}",pct:{round(v["pct"],3)},vs:{v["vs_upb"]},upb:{v["upb"]}}}'
                              for k, v in rows) + "]"
    lines.append("const PRODM={" + ",".join(f'"{ym}":{pblock(ym)}' for ym in months) + "};")

    # LENDERM: top lenders per month (top-N by volume + any VS lender) for the "who's driving" bar + month selector
    def lrow(v):
        return ('{name:%s,loans:%d,upb:%d,vs:%d,vs_upb:%d,fn:%d,fr:%d,rate:%s}' %
                (json.dumps(short(v['name'])), v['loans'], v['upb'], v['vs_loans'], v['vs_upb'],
                 v['fn_vs'], v['fre_vs'], round(v['rate'], 3)))
    lines.append("const LENDERM={" +
                 ",".join(f'"{ym}":[' + ",".join(lrow(v) for v in m['lenders'][ym]) + "]" for ym in months) + "};")

    # cross-tab for ALL months + the month list (for the month selector)
    lines.append("const XCROSS=" + json.dumps(m['crosstab'], separators=(',', ':')) + ";")
    lines.append("const XMONTHS=[" + ",".join(f'{{ym:"{s["month"]}",l:"{s["short"]}"}}' for s in series) + "];")

    # LSER: per-lender time series (line chart) with loans/upb totals for hover
    lines.append("const LSER=[")
    for s in m['lender_series']:
        lines.append('  {name:%s,vs:%s,rate:%s,loans:%s,upb:%s},' % (
            json.dumps(short(s['name'])), json.dumps(s['vs']), json.dumps(s['rate']),
            json.dumps(s['loans']), json.dumps(s['upb'])))
    lines.append("];")

    # VINT: agency VS penetration by origination cohort (First Payment Date).
    # `c` flags a cohort with all three bulk issuance months on hand; the rest are partial.
    lines.append("// origination-vintage view: l=label, n=loans, v=vs_loans, p=vs% of loans,"
                 " up=vs% of UPB, c=complete cohort")
    lines.append("const VINT=[" + ",".join(
        '{l:%s,n:%d,v:%d,p:%s,up:%s,c:%d}' % (json.dumps(v['short']), v['loans'], v['vs_loans'],
                                              round(v['pct'], 3), round(v['upb_pct'], 3),
                                              int(v['complete']))
        for v in m['vintage']) + "];")
    # MTD: provisional month-to-date from intraday cuts. null when none are loaded.
    d = m.get('mtd')
    if d:
        lines.append("const MTD=" + json.dumps({
            'short': d['short'], 'month': d['month'], 'issuers': d['issuers'],
            'files': d['files'], 'partial_issuers': d['partial_issuers'],
            'loans': d['loans'], 'upb': d['upb'], 'vs_loans': d['vs_loans'],
            'vs_upb': d['vs_upb'], 'pct': round(d['pct'], 3), 'upb_pct': round(d['upb_pct'], 3),
            'lenders': [dict(x, name=short(x['name'])) for x in d['lenders']],
        }, separators=(',', ':')) + ";")
    else:
        lines.append("const MTD=null;")
    lines.append("const VINTL=[" + ",".join(
        '{name:%s,rate:%s,loans:%s,vs:%s}' % (json.dumps(short(s['name'])), json.dumps(s['rate']),
                                              json.dumps(s['loans']), json.dumps(s['vs']))
        for s in m['vintage_lender']) + "];")
    return "\n".join(lines)

def generate():
    m = json.load(open(MASTER))
    tmpl = open(TEMPLATE, encoding="utf-8").read()
    assert "//__DATA__" in tmpl, "template missing //__DATA__ marker"
    html = tmpl.replace("//__DATA__", js_data(m))
    bad = [c for c in html if ord(c) > 127]
    assert not bad, f"non-ASCII leaked into output: {sorted(set(hex(ord(c)) for c in bad))}"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    return OUT

if __name__ == '__main__':
    p = generate()
    print(f"wrote {os.path.relpath(p, HERE)} ({os.path.getsize(p):,} bytes)")
