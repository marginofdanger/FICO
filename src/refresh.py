"""
refresh.py — one command to rebuild the tracker.

  1. Extract any {FNM,FRE}_ILLD_*.zip sitting in ../data  ->  .txt
  2. master_build : all loan-level files      ->  ../master.json
  3. generate_dashboard : master.json + template -> ../output/dashboard.html
  4. Write ../output/monthly.csv and ../output/lender_by_month.csv

Usage:  python src/refresh.py
Drop the new month's FNM_ILLD_YYYYMM.zip + FRE_ILLD_YYYYMM.zip into data/ first
(see FETCH.md for how to download them).
"""
import os, glob, zipfile, csv, json
import master_build, generate_dashboard

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUTDIR = os.path.join(HERE, "..", "output")

def extract_zips():
    n = 0
    for z in glob.glob(os.path.join(DATA, "*_ILLD_*.zip")):
        txt = z[:-4] + ".txt"
        if os.path.exists(txt) and os.path.getmtime(txt) >= os.path.getmtime(z):
            continue
        with zipfile.ZipFile(z) as zf:
            zf.extractall(DATA)
        n += 1
    return n

def write_csvs(m):
    os.makedirs(OUTDIR, exist_ok=True)
    # monthly series (fannie/freddie/total)
    with open(os.path.join(OUTDIR, "monthly.csv"), "w", newline="") as f:
        w = csv.writer(f)
        # must stay in step with master_build.pack()
        cols = ["upb", "loans", "wa_fico", "vs_upb", "vs_upb_pct", "vs_loans", "vs_loan_pct",
                "vs_pools", "total_pools"]
        w.writerow(["month"] + [f"fnm_{c}" for c in cols] + [f"fre_{c}" for c in cols] + [f"tot_{c}" for c in cols])
        for s in m["series"]:
            row = [s["label"]] + s["f"] + s["r"] + s["t"]
            assert len(row) == 1 + 3 * len(cols), \
                f"monthly.csv header/row mismatch: {len(row)} values vs {1 + 3*len(cols)} columns"
            w.writerow(row)
    # lender by month (long form) -- only sellers that actually delivered VS that month
    with open(os.path.join(OUTDIR, "lender_by_month.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "seller", "vs_loans", "vs_upb", "seller_loans", "vs_rate_pct", "fannie_vs", "freddie_vs"])
        for ym in m["months"]:
            for v in sorted(m["lenders"][ym], key=lambda d: -d["vs_loans"]):
                if not v["vs_loans"]:
                    continue
                w.writerow([f"{ym[:4]}-{ym[4:]}", v["name"], v["vs_loans"], v["vs_upb"],
                            v["loans"], v["rate"], v["fn_vs"], v["fre_vs"]])
    # origination-vintage series (agency), with the partial-cohort flag
    with open(os.path.join(OUTDIR, "vintage.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cohort", "loans", "vs_loans", "vs_loan_pct", "upb", "vs_upb", "vs_upb_pct", "complete"])
        for v in m["vintage"]:
            w.writerow([f"{v['cohort'][:4]}-{v['cohort'][4:]}", v["loans"], v["vs_loans"],
                        v["pct"], v["upb"], v["vs_upb"], v["upb_pct"], int(v["complete"])])

def main():
    nz = extract_zips()
    print(f"[1/4] extracted {nz} new zip(s)")
    m = master_build.build()
    print(f"[2/4] built master.json  ({len(m['months'])} months: {', '.join(m['months'])})")
    out = generate_dashboard.generate()
    print(f"[3/4] wrote {os.path.relpath(out, os.path.join(HERE,'..'))}")
    write_csvs(m)
    print(f"[4/4] wrote output/monthly.csv + lender_by_month.csv + vintage.csv")
    latest = m["series"][-1]; t = latest["t"]
    print(f"\nLatest month {latest['label']}:  ${t[0]/1e9:.1f}B issued  |  "
          f"VS {t[5]:,} loans ({t[4]:.3f}% UPB / {t[6]:.3f}% loans)  |  {t[7]} pools with VS")
    edge = [v for v in m["vintage"] if v["loans"] >= 1000]
    if edge:
        e = edge[-1]
        done = [v for v in edge if v["complete"]]
        tail = f"  (last complete cohort {done[-1]['short']}: {done[-1]['pct']:.2f}%)" if done else ""
        print(f"Leading-edge vintage {e['short']}: {e['pct']:.2f}% of {e['loans']:,} loans"
              f"{' [partial]' if not e['complete'] else ''}{tail}")
    print("Now re-publish output/dashboard.html to the artifact (ask Claude, or open it).")

if __name__ == "__main__":
    main()
