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
        cols = ["upb", "loans", "wa_fico", "vs_upb", "vs_upb_pct", "vs_loans", "vs_loan_pct", "vs_pools"]
        w.writerow(["month"] + [f"fnm_{c}" for c in cols] + [f"fre_{c}" for c in cols] + [f"tot_{c}" for c in cols])
        for s in m["series"]:
            w.writerow([s["label"]] + s["f"] + s["r"] + s["t"])
    # lender by month (long form)
    with open(os.path.join(OUTDIR, "lender_by_month.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "seller", "vs_loans", "vs_upb", "seller_loans", "vs_rate_pct", "fannie_vs", "freddie_vs"])
        for ym in m["months"]:
            for s, v in sorted(m["lender"][ym].items(), key=lambda kv: -kv[1]["vs"]):
                rate = round(v["vs"] / v["all"] * 100, 3) if v["all"] else 0
                w.writerow([f"{ym[:4]}-{ym[4:]}", s, v["vs"], v["vs_upb"], v["all"], rate, v["fn_vs"], v["fre_vs"]])

def main():
    nz = extract_zips()
    print(f"[1/4] extracted {nz} new zip(s)")
    m = master_build.build()
    print(f"[2/4] built master.json  ({len(m['months'])} months: {', '.join(m['months'])})")
    out = generate_dashboard.generate()
    print(f"[3/4] wrote {os.path.relpath(out, os.path.join(HERE,'..'))}")
    write_csvs(m)
    print(f"[4/4] wrote output/monthly.csv + output/lender_by_month.csv")
    latest = m["series"][-1]; t = latest["t"]
    print(f"\nLatest month {latest['label']}:  ${t[0]/1e9:.1f}B issued  |  "
          f"VS {t[5]:,} loans ({t[4]:.3f}% UPB / {t[6]:.3f}% loans)  |  {t[7]} pools with VS")
    print("Now re-publish output/dashboard.html to the artifact (ask Claude, or open it).")

if __name__ == "__main__":
    main()
