"""
master_build.py — the single analysis step.

Reads every {FNM,FRE}_ILLD_YYYYMM.txt loan-level file in ../data and writes
../master.json with:
  series    : monthly issuance + WA FICO + VantageScore penetration (Fannie / Freddie / total)
  crosstab  : FICO-only / VS-only / Both / Neither  (loans + UPB), per GSE + agency, per month
  lender    : VS-scored loans by seller, per month (per-GSE split)
  product   : VS penetration by loan-term bucket, per month

Every figure is loan-level (each loan counted once), so all views reconcile.
Run directly or via refresh.py.
"""
import json, os, glob, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT  = os.path.join(HERE, "..", "master.json")

NA = {'9999', '7777', ''}          # 9999=Not Available, 7777=Not Applicable; 777 is a valid score
LAB = {'01':"Jan",'02':"Feb",'03':"Mar",'04':"Apr",'05':"May",'06':"Jun",'07':"Jul",
       '08':"Aug",'09':"Sep",'10':"Oct",'11':"Nov",'12':"Dec"}

def month_label(ym):   # 202606 -> "Jun '26"
    return f"{LAB[ym[4:6]]} '{ym[2:4]}"

def discover_months():
    months = set()
    for p in glob.glob(os.path.join(DATA, "FNM_ILLD_*.txt")):
        m = re.search(r'FNM_ILLD_(\d{6})\.txt$', os.path.basename(p))
        if m and os.path.exists(os.path.join(DATA, f"FRE_ILLD_{m.group(1)}.txt")):
            months.add(m.group(1))
    return sorted(months)

def bucket(t):
    try: t = float(t)
    except (TypeError, ValueError): return 'other'
    if t >= 330: return '30yr'
    if 205 <= t < 300: return '20yr'
    if 165 <= t < 205: return '15yr'
    if 100 <= t < 150: return '10yr'
    return 'other'

def scan(issuer, ym):
    path = os.path.join(DATA, f"{issuer}_ILLD_{ym}.txt")
    with open(path, encoding='utf-8', errors='replace') as f:
        h = f.readline().rstrip('\n').split('|'); ix = {n: i for i, n in enumerate(h)}
        iF, iV = ix['Classic FICO'], ix['VS4']
        iFo, iVo = ix['Origination Classic FICO'], ix['Origination VS4']
        iU, iS, iT, iSec = (ix['Issuance Investor Loan UPB'], ix['Seller Name'],
                            ix['Loan Term'], ix['Security Identifier'])
        tot_l = 0; tot_u = 0.0; fico_wsum = 0.0; fico_wden = 0.0
        ct = {k: [0, 0.0] for k in ('fico_only', 'vs_only', 'both', 'neither')}
        prod = defaultdict(lambda: [0.0, 0.0, 0, 0])   # upb, vs_upb, loans, vs_loans
        vs_secs = set(); all_secs = set()
        sell = defaultdict(lambda: [0, 0.0, 0, 0.0])   # loans, upb, vs_loans, vs_upb
        for line in f:
            p = line.rstrip('\n').split('|')
            if len(p) <= iS: continue
            try: u = float(p[iU])
            except ValueError: u = 0.0
            fico = p[iF].strip()
            fico = fico if fico not in NA else (p[iFo].strip() if p[iFo].strip() not in NA else '')
            hf = fico != ''
            hv = (p[iV].strip() not in NA) or (p[iVo].strip() not in NA)
            k = 'both' if (hf and hv) else 'fico_only' if hf else 'vs_only' if hv else 'neither'
            ct[k][0] += 1; ct[k][1] += u
            tot_l += 1; tot_u += u; all_secs.add(p[iSec])
            if hf:
                try: fico_wsum += float(fico) * u; fico_wden += u
                except ValueError: pass
            b = prod[bucket(p[iT])]; b[0] += u; b[2] += 1
            s = p[iS].strip() or '(blank)'; d = sell[s]; d[0] += 1; d[1] += u
            if hv:
                vs_secs.add(p[iSec]); b[1] += u; b[3] += 1; d[2] += 1; d[3] += u
    return {'tot_l': tot_l, 'tot_u': tot_u,
            'wa_fico': round(fico_wsum / fico_wden, 1) if fico_wden else None,
            'ct': ct, 'prod': {k: list(v) for k, v in prod.items()},
            'n_vs_pools': len(vs_secs), 'n_pools': len(all_secs), 'sell': sell}

def pct(a, b): return round(a / b * 100, 4) if b else 0.0

def build():
    months = discover_months()
    if not months:
        raise SystemExit(f"No paired FNM/FRE loan-level files found in {DATA}")
    TOP_N = 12   # top lenders (by volume) kept per month for the "top lenders" chart
    series = []; crosstab = {}; lenders = {}; product = {}; combined = {}
    for ym in months:
        fn = scan('FNM', ym); fr = scan('FRE', ym)
        def pack(m):
            vl = m['ct']['vs_only'][0]; vu = m['ct']['vs_only'][1]
            return [round(m['tot_u']), m['tot_l'], m['wa_fico'], round(vu),
                    pct(vu, m['tot_u']), vl, pct(vl, m['tot_l']), m['n_vs_pools'], m['n_pools']]
        tu = fn['tot_u'] + fr['tot_u']; tl = fn['tot_l'] + fr['tot_l']
        tvu = fn['ct']['vs_only'][1] + fr['ct']['vs_only'][1]
        tvl = fn['ct']['vs_only'][0] + fr['ct']['vs_only'][0]
        tfico = (((fn['wa_fico'] or 0) * fn['tot_u'] + (fr['wa_fico'] or 0) * fr['tot_u']) / tu) if tu else None
        t8 = [round(tu), tl, round(tfico, 1) if tfico else None, round(tvu),
              pct(tvu, tu), tvl, pct(tvl, tl), fn['n_vs_pools'] + fr['n_vs_pools'], fn['n_pools'] + fr['n_pools']]
        series.append({'month': ym, 'label': f"{ym[:4]}-{ym[4:]}", 'short': month_label(ym),
                       'f': pack(fn), 'r': pack(fr), 't': t8})
        crosstab[ym] = {
            'fannie':  {c: [fn['ct'][c][0], round(fn['ct'][c][1])] for c in fn['ct']},
            'freddie': {c: [fr['ct'][c][0], round(fr['ct'][c][1])] for c in fr['ct']},
            'agency':  {c: [fn['ct'][c][0] + fr['ct'][c][0], round(fn['ct'][c][1] + fr['ct'][c][1])] for c in fn['ct']}}
        # combined per-seller stats: [loans, upb, vs_loans, vs_upb, fn_vs, fre_vs]
        comb = {}
        for s in set(fn['sell']) | set(fr['sell']):
            a = fn['sell'].get(s, [0, 0, 0, 0]); b = fr['sell'].get(s, [0, 0, 0, 0])
            comb[s] = [a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3], a[2], b[2]]
        combined[ym] = comb
        # keep top-N by volume, plus any seller with VS this month
        keep = set(sorted(comb, key=lambda s: -comb[s][0])[:TOP_N]) | {s for s in comb if comb[s][2] > 0}
        lenders[ym] = [{'name': s, 'loans': comb[s][0], 'upb': round(comb[s][1]),
                        'vs_loans': comb[s][2], 'vs_upb': round(comb[s][3]),
                        'fn_vs': comb[s][4], 'fre_vs': comb[s][5],
                        'rate': pct(comb[s][2], comb[s][0])}
                       for s in sorted(keep, key=lambda s: -comb[s][0])]
        pm = {}
        for k in set(fn['prod']) | set(fr['prod']):
            a = fn['prod'].get(k, [0, 0, 0, 0]); b = fr['prod'].get(k, [0, 0, 0, 0])
            upb = a[0] + b[0]; vsu = a[1] + b[1]
            pm[k] = {'upb': round(upb), 'vs_upb': round(vsu), 'pct': pct(vsu, upb), 'vs_loans': a[3] + b[3]}
        product[ym] = pm
    # per-lender time series for every seller that ever delivered VS (for the over-time chart + hover)
    ever_vs = {s for ym in months for s in combined[ym] if combined[ym][s][2] > 0}
    lender_series = []
    for s in sorted(ever_vs, key=lambda s: -sum(combined[ym].get(s, [0,0,0,0,0,0])[2] for ym in months)):
        lender_series.append({
            'name': s,
            'vs':    [combined[ym].get(s, [0,0,0,0,0,0])[2] for ym in months],
            'rate':  [pct(combined[ym].get(s, [0,0,0,0,0,0])[2], combined[ym].get(s, [1,0,0,0,0,0])[0]) for ym in months],
            'loans': [combined[ym].get(s, [0,0,0,0,0,0])[0] for ym in months],
            'upb':   [round(combined[ym].get(s, [0,0,0,0,0,0])[1]) for ym in months]})
    out = {'series': series, 'crosstab': crosstab, 'lenders': lenders,
           'lender_series': lender_series, 'product': product, 'months': months}
    json.dump(out, open(OUT, 'w'), indent=1)
    return out

if __name__ == '__main__':
    o = build()
    print(f"Months: {', '.join(o['months'])}")
    print(f"{'Month':<8}{'agUPB$B':>9}{'WAfico':>7}{'VS$M':>9}{'VS%UPB':>8}{'VSloans':>8}{'VSpool':>7}")
    for s in o['series']:
        t = s['t']
        print(f"{s['label']:<8}{t[0]/1e9:>9.2f}{t[2] or 0:>7.1f}{t[3]/1e6:>9.1f}{t[4]:>8.3f}{t[5]:>8,}{t[7]:>7}")
    print(f"\nwrote {os.path.relpath(OUT, HERE)}")
