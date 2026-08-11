"""
master_build.py — the single analysis step.

Reads every {FNM,FRE}_ILLD_YYYYMM.txt loan-level file in ../data and writes
../master.json with:
  series    : monthly issuance + WA FICO + VantageScore penetration (Fannie / Freddie / total)
  crosstab  : FICO-only / VS-only / Both / Neither  (loans + UPB), per GSE + agency, per month
  lender    : VS-scored loans by seller, per month (per-GSE split)
  product   : VS penetration by loan-term bucket, per month
  vintage   : VS penetration by ORIGINATION cohort (First Payment Date), pooled
              across every issuance file — the leading-edge run-rate view

Every figure is loan-level (each loan counted once), so all views reconcile.

Why vintage matters: the issuance-month series blends loans that closed over a
~3-month window, so it lags the true run-rate badly during a ramp. A loan's
First Payment Date is ~2 months after it closed, and

    Loan Age = issuance_month - first_payment_month + 1

so each issuance file carries cohorts at age -1 (newest), 0, +1, ... A cohort is
only materially complete once the issuance file for cohort+1 has landed; later
cohorts are partial and flagged as such.

Loan purpose: every seller/cohort/month tally is also kept split by Loan Purpose
(P purchase, C cash-out refi, N rate/term refi, O everything else -- chiefly the
'M' modified loans that ride in reperforming pools). The `*_p` keys mirror their
unsplit counterparts exactly, so the dashboard can filter any lender or cohort
view by loan type. Refis run well ahead of purchase, and by different margins at
different lenders, so the blended number hides most of the story.

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

PK     = ('P', 'C', 'N', 'O')   # every loan lands in exactly one, so these sum to the total
PSPLIT = ('P', 'C', 'N')        # the three the dashboard offers as filters
Z4     = [0, 0.0, 0, 0.0]

def month_label(ym):   # 202606 -> "Jun '26"
    return f"{LAB[ym[4:6]]} '{ym[2:4]}"

def discover_months():
    months = set()
    for p in glob.glob(os.path.join(DATA, "FNM_ILLD_*.txt")):
        m = re.search(r'FNM_ILLD_(\d{6})\.txt$', os.path.basename(p))
        if m and os.path.exists(os.path.join(DATA, f"FRE_ILLD_{m.group(1)}.txt")):
            months.add(m.group(1))
    return sorted(months)

def discover_intraday(final_months):
    """Mid-month loan-level snapshots -> {issuer: {ym: [paths]}}.

    Fannie/Freddie publish intraday cuts (FNM_ILLD_YYYYMMDD_N.txt) during the
    month. They give a month-to-date read weeks before the month-end file. A
    month that already has its final file is skipped -- the final file is a
    superset. Loans are deduped on Loan Identifier when a month has several
    snapshots, so this is correct whether the cuts are cumulative or daily
    increments.
    """
    found = {'FNM': defaultdict(list), 'FRE': defaultdict(list)}
    for iss in ('FNM', 'FRE'):
        for p in sorted(glob.glob(os.path.join(DATA, f"{iss}_ILLD_*.txt"))):
            m = re.search(rf'{iss}_ILLD_(\d{{4}})(\d{{2}})(\d{{2}})(?:_(\d+))?\.txt$',
                          os.path.basename(p))
            if not m:
                continue
            ym = m.group(1) + m.group(2)
            if ym in final_months:
                continue
            found[iss][ym].append(p)
    return found

def madd(ym, k):
    """'202606' + k months -> 'YYYYMM'."""
    n = int(ym[:4]) * 12 + int(ym[4:6]) - 1 + k
    return f"{n // 12:04d}{n % 12 + 1:02d}"

def cohort_key(fpd):
    """First Payment Date 'MMYYYY' -> 'YYYYMM' (sortable). '' if unparseable."""
    fpd = (fpd or '').strip()
    if len(fpd) != 6 or not fpd.isdigit():
        return ''
    mm, yyyy = fpd[:2], fpd[2:]
    if not ('01' <= mm <= '12') or not ('1990' <= yyyy <= '2099'):
        return ''
    return yyyy + mm

def bucket(t):
    try: t = float(t)
    except (TypeError, ValueError): return 'other'
    if t >= 330: return '30yr'
    if 205 <= t < 300: return '20yr'
    if 165 <= t < 205: return '15yr'
    if 100 <= t < 150: return '10yr'
    return 'other'

def psum(pm, n=4):
    """Collapse a {purpose: [...]} tally back to the unsplit total."""
    return [sum(v[i] for v in pm.values()) for i in range(n)]

def scan(issuer, ym):
    return scan_paths([os.path.join(DATA, f"{issuer}_ILLD_{ym}.txt")])

def scan_paths(paths):
    """Accumulate one issuer-month across one or more loan-level files.

    Several files only happens for intraday snapshots, where a loan can repeat
    across cuts, so Loan Identifier is deduped when there is more than one file.
    """
    dedup = len(paths) > 1
    seen = set()
    tot_l = 0; tot_u = 0.0; fico_wsum = 0.0; fico_wden = 0.0
    ct = {k: [0, 0.0] for k in ('fico_only', 'vs_only', 'both', 'neither')}
    prod = defaultdict(lambda: [0.0, 0.0, 0, 0])   # upb, vs_upb, loans, vs_loans
    vs_secs = set(); all_secs = set()
    # every purpose-keyed tally below is {purpose: [...]}, summing to the total
    sell = defaultdict(lambda: {k: [0, 0.0, 0, 0.0] for k in PK})   # loans, upb, vs_loans, vs_upb
    purp = {k: [0, 0.0, 0, 0.0] for k in PK}                        # same, all sellers
    vint = defaultdict(lambda: {k: [0, 0, 0.0, 0.0] for k in PK})   # loans, vs_loans, upb, vs_upb
    vint_sell = defaultdict(lambda: defaultdict(lambda: {k: [0, 0, 0.0, 0.0] for k in PK}))
    for path in paths:
      with open(path, encoding='utf-8', errors='replace') as f:
        h = f.readline().rstrip('\n').split('|'); ix = {n: i for i, n in enumerate(h)}
        # An intraday cut with no new loans is published as a bare date stamp
        # ('08032026') -- no header, no rows. Nothing to scan.
        if len(h) < 2:
            continue
        iF, iV = ix['Classic FICO'], ix['VS4']
        iFo, iVo = ix['Origination Classic FICO'], ix['Origination VS4']
        iU, iS, iT, iSec = (ix['Issuance Investor Loan UPB'], ix['Seller Name'],
                            ix['Loan Term'], ix['Security Identifier'])
        iFP, iID = ix['First Payment Date'], ix['Loan Identifier']
        iP, iPo = ix['Loan Purpose'], ix['Origination Loan Purpose']
        for line in f:
            p = line.rstrip('\n').split('|')
            if len(p) <= iS: continue
            if dedup:
                lid = p[iID]
                if lid in seen: continue
                seen.add(lid)
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
            # 'M' (modified) and anything unexpected fall into 'O'
            pk = p[iP].strip() or p[iPo].strip()
            pk = pk if pk in PSPLIT else 'O'
            s = p[iS].strip() or '(blank)'
            d = sell[s][pk]; d[0] += 1; d[1] += u
            a = purp[pk];    a[0] += 1; a[1] += u
            ck = cohort_key(p[iFP])
            if ck:
                v = vint[ck][pk]; v[0] += 1; v[2] += u
                vsl = vint_sell[ck][s][pk]; vsl[0] += 1; vsl[2] += u
            if hv:
                vs_secs.add(p[iSec]); b[1] += u; b[3] += 1
                d[2] += 1; d[3] += u; a[2] += 1; a[3] += u
                if ck:
                    v[1] += 1; v[3] += u; vsl[1] += 1; vsl[3] += u
    return {'tot_l': tot_l, 'tot_u': tot_u,
            'wa_fico': round(fico_wsum / fico_wden, 1) if fico_wden else None,
            'ct': ct, 'prod': {k: list(v) for k, v in prod.items()},
            'n_vs_pools': len(vs_secs), 'n_pools': len(all_secs), 'sell': sell,
            'purp': purp, 'vint': vint, 'vint_sell': vint_sell}

def pct(a, b): return round(a / b * 100, 4) if b else 0.0

def build():
    months = discover_months()
    if not months:
        raise SystemExit(f"No paired FNM/FRE loan-level files found in {DATA}")
    TOP_N = 12   # top lenders (by volume) kept per month for the "top lenders" chart
    series = []; crosstab = {}; lenders = {}; product = {}; combined = {}
    purpose_series = []
    # combined[ym][seller][purpose] = [loans, upb, vs_loans, vs_upb, fn_vs, fre_vs]
    lenders_p = {pk: {} for pk in PSPLIT}
    # origination-cohort accumulators, pooled across every issuance file.
    # A loan appears in exactly one issuance file, so summing is safe (no dedup).
    vint = defaultdict(lambda: {k: [0, 0, 0.0, 0.0] for k in PK})
    # cohort -> seller -> purpose -> loans, vs_loans, upb, vs_upb, fn_vs, fre_vs
    vint_sell = defaultdict(lambda: defaultdict(lambda: {k: [0, 0, 0.0, 0.0, 0, 0] for k in PK}))

    def merge_vint(src, iss):
        """Fold one issuer-month's cohort tallies into the pooled accumulators."""
        for ck, pm in src['vint'].items():
            a = vint[ck]
            for pk, v in pm.items():
                for i in range(4):
                    a[pk][i] += v[i]
        for ck, sm in src['vint_sell'].items():
            for s, pm in sm.items():
                a = vint_sell[ck][s]
                for pk, v in pm.items():
                    t = a[pk]
                    for i in range(4):
                        t[i] += v[i]
                    t[4 if iss == 'FNM' else 5] += v[1]

    for ym in months:
        fn = scan('FNM', ym); fr = scan('FRE', ym)
        for iss, src in (('FNM', fn), ('FRE', fr)):
            merge_vint(src, iss)
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
        # ---- agency issuance by loan purpose (per GSE + total) ----
        # Same VS-only numerator as the headline, cut by Loan Purpose.
        def ppack(m, pk):
            n, u, v, vu = m['purp'][pk]
            return [n, round(u), v, round(vu), pct(v, n), pct(vu, u)]
        pblk = {}
        for pk in PSPLIT:
            a = fn['purp'][pk]; b = fr['purp'][pk]
            n = a[0] + b[0]; u = a[1] + b[1]; v = a[2] + b[2]; vu = a[3] + b[3]
            pblk[pk] = {'f': ppack(fn, pk), 'r': ppack(fr, pk),
                        't': [n, round(u), v, round(vu), pct(v, n), pct(vu, u)]}
        purpose_series.append({'month': ym, 'short': month_label(ym), 'p': pblk})
        # ---- per-seller stats, kept by purpose; 'all' is the sum ----
        # comb[seller][purpose] = [loans, upb, vs_loans, vs_upb, fn_vs, fre_vs]
        comb = {}
        for s in set(fn['sell']) | set(fr['sell']):
            a = fn['sell'].get(s); b = fr['sell'].get(s)
            comb[s] = {pk: [(a[pk][0] if a else 0) + (b[pk][0] if b else 0),
                            (a[pk][1] if a else 0.0) + (b[pk][1] if b else 0.0),
                            (a[pk][2] if a else 0) + (b[pk][2] if b else 0),
                            (a[pk][3] if a else 0.0) + (b[pk][3] if b else 0.0),
                            (a[pk][2] if a else 0), (b[pk][2] if b else 0)] for pk in PK}
        combined[ym] = comb

        def lender_rows(pick):
            """Rank sellers on `pick(seller) -> [loans, upb, vs, vs_upb, fn_vs, fre_vs]`."""
            g = {s: pick(s) for s in comb}
            keep = set(sorted(g, key=lambda s: -g[s][0])[:TOP_N]) | {s for s in g if g[s][2] > 0}
            return [{'name': s, 'loans': g[s][0], 'upb': round(g[s][1]),
                     'vs_loans': g[s][2], 'vs_upb': round(g[s][3]),
                     'fn_vs': g[s][4], 'fre_vs': g[s][5],
                     'rate': pct(g[s][2], g[s][0]), 'upb_rate': pct(g[s][3], g[s][1])}
                    for s in sorted(keep, key=lambda s: -g[s][0])]
        lenders[ym] = lender_rows(lambda s: psum(comb[s], 6))
        for pk in PSPLIT:
            # ranked within the purpose -- the biggest purchase shop is not the
            # biggest cash-out shop, and that is the point of the filter
            lenders_p[pk][ym] = lender_rows(lambda s, pk=pk: comb[s][pk])
        pm = {}
        for k in set(fn['prod']) | set(fr['prod']):
            a = fn['prod'].get(k, [0, 0, 0, 0]); b = fr['prod'].get(k, [0, 0, 0, 0])
            upb = a[0] + b[0]; vsu = a[1] + b[1]
            pm[k] = {'upb': round(upb), 'vs_upb': round(vsu), 'pct': pct(vsu, upb), 'vs_loans': a[3] + b[3]}
        product[ym] = pm
    # ---- intraday (month-to-date) snapshots ----
    # These only feed the cohort view and a provisional MTD headline; they never
    # enter `series`, which must stay a clean month-end apples-to-apples series.
    intra = discover_intraday(set(months))
    intra_months = sorted(set(intra['FNM']) | set(intra['FRE']))
    mtd = None
    for ym in intra_months:
        parts = {}
        for iss in ('FNM', 'FRE'):
            if intra[iss].get(ym):
                parts[iss] = scan_paths(sorted(intra[iss][ym]))
        for iss, src in parts.items():
            merge_vint(src, iss)
        if ym == intra_months[-1]:
            tl = sum(p['tot_l'] for p in parts.values())
            tu = sum(p['tot_u'] for p in parts.values())
            vl = sum(p['ct']['vs_only'][0] for p in parts.values())
            vu = sum(p['ct']['vs_only'][1] for p in parts.values())
            # per-seller MTD, same shape as the month-end lender rows
            msell = defaultdict(lambda: {k: [0, 0.0, 0, 0.0, 0, 0] for k in PK})
            mpurp = {k: [0, 0.0, 0, 0.0] for k in PK}
            for iss, p in parts.items():
                for s, pmm in p['sell'].items():
                    for pk, d in pmm.items():
                        a = msell[s][pk]
                        a[0] += d[0]; a[1] += d[1]; a[2] += d[2]; a[3] += d[3]
                        a[4 if iss == 'FNM' else 5] += d[2]
                for pk, d in p['purp'].items():
                    a = mpurp[pk]
                    for i in range(4):
                        a[i] += d[i]

            def mtd_rows(pick):
                g = {s: pick(s) for s in msell}
                keep = set(sorted(g, key=lambda s: -g[s][0])[:TOP_N]) | {s for s in g if g[s][2] > 0}
                return [{'name': s, 'loans': g[s][0], 'upb': round(g[s][1]),
                         'vs_loans': g[s][2], 'vs_upb': round(g[s][3]),
                         'fn_vs': g[s][4], 'fre_vs': g[s][5],
                         'rate': pct(g[s][2], g[s][0]), 'upb_rate': pct(g[s][3], g[s][1])}
                        for s in sorted(keep, key=lambda s: -g[s][0])]
            mtd = {'month': ym, 'short': month_label(ym),
                   'issuers': sorted(parts), 'files': sum(len(intra[i].get(ym, [])) for i in parts),
                   'partial_issuers': sorted(set(('FNM', 'FRE')) - set(parts)),
                   'loans': tl, 'upb': round(tu), 'vs_loans': vl, 'vs_upb': round(vu),
                   'pct': pct(vl, tl), 'upb_pct': pct(vu, tu),
                   'lenders': mtd_rows(lambda s: psum(msell[s], 6)),
                   'lenders_p': {pk: mtd_rows(lambda s, pk=pk: msell[s][pk]) for pk in PSPLIT},
                   'p': {pk: {'loans': mpurp[pk][0], 'upb': round(mpurp[pk][1]),
                              'vs_loans': mpurp[pk][2], 'vs_upb': round(mpurp[pk][3]),
                              'pct': pct(mpurp[pk][2], mpurp[pk][0]),
                              'upb_pct': pct(mpurp[pk][3], mpurp[pk][1])} for pk in PSPLIT}}
    intra_sellers = {s for ck in vint_sell for s, pm in vint_sell[ck].items()
                     if sum(v[1] for v in pm.values()) > 0}

    # per-lender time series for every seller that ever delivered VS (for the over-time chart + hover)
    ever_vs = {s for ym in months for s in combined[ym] if psum(combined[ym][s], 6)[2] > 0}
    ZP = {pk: [0, 0.0, 0, 0.0, 0, 0] for pk in PK}

    def cget(ym, s, pk=None):
        """One seller's month, for a purpose or (pk=None) summed across all."""
        c = combined[ym].get(s, ZP)
        return c[pk] if pk else psum(c, 6)

    def lseries(pk=None):
        order = sorted(ever_vs, key=lambda s: -sum(cget(ym, s, pk)[2] for ym in months))
        return [{'name': s,
                 'vs':    [cget(ym, s, pk)[2] for ym in months],
                 'rate':  [pct(cget(ym, s, pk)[2], cget(ym, s, pk)[0]) for ym in months],
                 'loans': [cget(ym, s, pk)[0] for ym in months],
                 'upb':   [round(cget(ym, s, pk)[1]) for ym in months]} for s in order]
    lender_series = lseries()
    lender_series_p = {pk: lseries(pk) for pk in PSPLIT}
    # ---- origination-vintage view ----
    # Loan Age = issuance_month - cohort + 1, so cohort C is fed by issuance month
    # C-2 (age -1, the newest loans), C-1 (age 0) and C (age 1) -- that's the bulk;
    # ages 2+ are a ~5% tail that trickles in later. With issuance months [I0..I1]
    # on hand, C has all three bulk months only when C-2 >= I0 and C <= I1.
    # Intraday months extend the cohort range but never count toward completeness.
    I0, I1 = months[0], months[-1]
    last_any = max([I1] + intra_months)
    lo, hi = I0, madd(last_any, 2)             # cohorts worth showing
    cfull_lo, cfull_hi = madd(I0, 2), I1
    cohorts = [c for c in sorted(vint) if lo <= c <= hi]

    def vrow(c, t):
        n, v, u, vu = t[0], t[1], t[2], t[3]
        return {'cohort': c, 'short': month_label(c),
                'loans': n, 'vs_loans': v, 'upb': round(u), 'vs_upb': round(vu),
                'pct': pct(v, n), 'upb_pct': pct(vu, u),
                'complete': cfull_lo <= c <= cfull_hi}
    vintage = [vrow(c, psum(vint[c])) for c in cohorts]
    vintage_p = {pk: [vrow(c, vint[c][pk]) for c in cohorts] for pk in PSPLIT}
    # per-lender cohort series, for every seller that ever delivered VS.
    # The seller SET and its order are held fixed across purposes so the
    # dashboard's lender dropdown does not reshuffle when the filter changes.
    ZS = {pk: [0, 0, 0.0, 0.0, 0, 0] for pk in PK}

    def vget(c, s, pk=None):
        d = vint_sell[c].get(s, ZS)
        return d[pk] if pk else psum(d, 6)
    vl_order = sorted(ever_vs | intra_sellers,
                      key=lambda s: -sum(vget(c, s)[1] for c in cohorts))

    def vlseries(pk=None):
        out = []
        for s in vl_order:
            g = [vget(c, s, pk) for c in cohorts]
            out.append({'name': s,
                        'loans':    [x[0] for x in g],
                        'vs':       [x[1] for x in g],
                        'rate':     [pct(x[1], x[0]) for x in g],
                        'upb':      [round(x[2]) for x in g],
                        'vs_upb':   [round(x[3]) for x in g],
                        'upb_rate': [pct(x[3], x[2]) for x in g],
                        'fn_vs':    [x[4] for x in g],
                        'fre_vs':   [x[5] for x in g]})
        return out
    vintage_lender = vlseries()
    vintage_lender_p = {pk: vlseries(pk) for pk in PSPLIT}
    out = {'series': series, 'crosstab': crosstab, 'lenders': lenders,
           'lender_series': lender_series, 'product': product, 'months': months,
           'vintage': vintage, 'vintage_lender': vintage_lender,
           'vintage_complete_through': cfull_hi, 'mtd': mtd,
           'purpose_series': purpose_series, 'lenders_p': lenders_p,
           'lender_series_p': lender_series_p, 'vintage_p': vintage_p,
           'vintage_lender_p': vintage_lender_p}
    json.dump(out, open(OUT, 'w'), indent=1)
    return out

if __name__ == '__main__':
    o = build()
    print(f"Months: {', '.join(o['months'])}")
    print(f"{'Month':<8}{'agUPB$B':>9}{'WAfico':>7}{'VS$M':>9}{'VS%UPB':>8}{'VSloans':>8}{'VSpool':>7}")
    for s in o['series']:
        t = s['t']
        print(f"{s['label']:<8}{t[0]/1e9:>9.2f}{t[2] or 0:>7.1f}{t[3]/1e6:>9.1f}{t[4]:>8.3f}{t[5]:>8,}{t[7]:>7}")
    print(f"\n{'Month':<8}{'Purchase':>11}{'Cash-out':>11}{'Rate/term':>11}   VS % of loans")
    for s in o['purpose_series']:
        print(f"{s['short']:<8}" + "".join(f"{s['p'][pk]['t'][4]:>10.2f}%" for pk in ('P', 'C', 'N')))
    print(f"\nwrote {os.path.relpath(OUT, HERE)}")
