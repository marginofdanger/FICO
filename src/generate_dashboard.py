"""
generate_dashboard.py — master.json + template.html -> output/dashboard.html

Builds the JS data literals (M, PROD, LENDERS, CROSS, LMONTH) from master.json
and injects them at the //__DATA__ marker in template.html. Output is pure ASCII
(numbers + ASCII names), so it publishes cleanly as an Artifact.

Everything the loan-purpose filter touches is emitted keyed by purpose --
LENDERM/LSER/VINT/VINTL/MTD.lenders are all {all,P,C,N} -> (what they used to
be). That keeps the JS a single lookup away from filtered, rather than
threading a purpose argument through every render function.
"""
import json, os

PK = ('P', 'C', 'N')            # purchase / cash-out refi / rate-term refi
PALL = ('all',) + PK

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

    # LENDERM: top lenders per month (top-N by volume + any VS lender) for the "who's driving" bar +
    # month selector, keyed by loan purpose. Ranked *within* each purpose -- the biggest purchase
    # shop is not the biggest cash-out shop.
    def lrow(v):
        return ('{name:%s,loans:%d,upb:%d,vs:%d,vs_upb:%d,fn:%d,fr:%d,rate:%s}' %
                (json.dumps(short(v['name'])), v['loans'], v['upb'], v['vs_loans'], v['vs_upb'],
                 v['fn_vs'], v['fre_vs'], round(v['rate'], 3)))
    def lblock(src):
        return "{" + ",".join(f'"{ym}":[' + ",".join(lrow(v) for v in src[ym]) + "]" for ym in months) + "}"
    lines.append("const LENDERM={" + ",".join(
        f'{pk}:{lblock(m["lenders"] if pk == "all" else m["lenders_p"][pk])}' for pk in PALL) + "};")

    # PSER: agency issuance by loan purpose, per month, following the GSE toggle.
    # f/r/t = [loans, upb, vs_loans, vs_upb, vs_loan_pct, vs_upb_pct]
    lines.append("// by loan purpose: f/r/t = [loans, upb, vs_loans, vs_upb, vs_loan_pct, vs_upb_pct]")
    lines.append("const PSER=[" + ",".join(
        '{l:%s,p:{%s}}' % (json.dumps(s['short']),
                           ",".join('%s:{f:%s,r:%s,t:%s}' % (
                               pk, json.dumps(s['p'][pk]['f']), json.dumps(s['p'][pk]['r']),
                               json.dumps(s['p'][pk]['t'])) for pk in PK))
        for s in m['purpose_series']) + "];")

    # cross-tab for ALL months + the month list (for the month selector)
    lines.append("const XCROSS=" + json.dumps(m['crosstab'], separators=(',', ':')) + ";")
    lines.append("const XMONTHS=[" + ",".join(f'{{ym:"{s["month"]}",l:"{s["short"]}"}}' for s in series) + "];")

    # LSER: per-lender time series (line chart) with loans/upb totals for hover, by purpose
    def lserblock(src):
        return "[" + ",".join('{name:%s,vs:%s,rate:%s,loans:%s,upb:%s}' % (
            json.dumps(short(s['name'])), json.dumps(s['vs']), json.dumps(s['rate']),
            json.dumps(s['loans']), json.dumps(s['upb'])) for s in src) + "]"
    lines.append("const LSER={" + ",".join(
        f'{pk}:{lserblock(m["lender_series"] if pk == "all" else m["lender_series_p"][pk])}'
        for pk in PALL) + "};")

    # VINT: agency VS penetration by origination cohort (First Payment Date).
    # `c` flags a cohort with all three bulk issuance months on hand; the rest are partial.
    lines.append("// origination-vintage view: l=label, n=loans, v=vs_loans, p=vs% of loans,"
                 " up=vs% of UPB, c=complete cohort")
    def vblock(src):
        return "[" + ",".join(
            '{l:%s,n:%d,v:%d,p:%s,up:%s,c:%d}' % (json.dumps(v['short']), v['loans'], v['vs_loans'],
                                                  round(v['pct'], 3), round(v['upb_pct'], 3),
                                                  int(v['complete'])) for v in src) + "]"
    lines.append("const VINT={" + ",".join(
        f'{pk}:{vblock(m["vintage"] if pk == "all" else m["vintage_p"][pk])}' for pk in PALL) + "};")
    # MTD: provisional month-to-date from intraday cuts. null when none are loaded.
    d = m.get('mtd')
    if d:
        lines.append("const MTD=" + json.dumps({
            'short': d['short'], 'month': d['month'], 'issuers': d['issuers'],
            'files': d['files'], 'partial_issuers': d['partial_issuers'],
            'loans': d['loans'], 'upb': d['upb'], 'vs_loans': d['vs_loans'],
            'vs_upb': d['vs_upb'], 'pct': round(d['pct'], 3), 'upb_pct': round(d['upb_pct'], 3),
            'lenders': {pk: [dict(x, name=short(x['name']))
                             for x in (d['lenders'] if pk == 'all' else d['lenders_p'][pk])]
                        for pk in PALL},
            'p': dict({'all': {'loans': d['loans'], 'upb': d['upb'], 'vs_loans': d['vs_loans'],
                               'vs_upb': d['vs_upb'], 'pct': round(d['pct'], 3),
                               'upb_pct': round(d['upb_pct'], 3)}},
                      **{pk: {k: (round(v, 3) if isinstance(v, float) else v)
                              for k, v in d['p'][pk].items()} for pk in PK}),
        }, separators=(',', ':')) + ";")
    else:
        lines.append("const MTD=null;")
    def vlblock(src):
        return "[" + ",".join(
            '{name:%s,rate:%s,loans:%s,vs:%s,upb:%s,vs_upb:%s,upb_rate:%s,fn:%s,fr:%s}' % (
                json.dumps(short(s['name'])), json.dumps(s['rate']), json.dumps(s['loans']),
                json.dumps(s['vs']), json.dumps(s['upb']), json.dumps(s['vs_upb']),
                json.dumps([round(x, 3) for x in s['upb_rate']]),
                json.dumps(s['fn_vs']), json.dumps(s['fre_vs'])) for s in src) + "]"
    # seller set + order is identical across purposes, so the lender dropdown is stable
    lines.append("const VINTL={" + ",".join(
        f'{pk}:{vlblock(m["vintage_lender"] if pk == "all" else m["vintage_lender_p"][pk])}'
        for pk in PALL) + "};")
    lines.append('const PURP=[{k:"all",l:"All loan types"},{k:"P",l:"Purchase"},'
                 '{k:"C",l:"Cash-out refi"},{k:"N",l:"Rate/term refi"}];')
    # cohort labels + partial flag, so the vintage lender table can name its cohort
    lines.append("const VINTC=[" + ",".join(
        '{l:%s,c:%d}' % (json.dumps(v['short']), int(v['complete'])) for v in m['vintage']) + "];")
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
