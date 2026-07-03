# Agency MBS — VantageScore 4.0 Adoption Tracker

Tracks how fast Fannie Mae and Freddie Mac lenders are delivering loans scored by
**VantageScore 4.0** instead of **Classic FICO**, from each GSE's month-end **loan-level**
disclosure. Produces a self-contained HTML dashboard (published as a claude.ai Artifact) plus CSVs.

**Live dashboard:** https://claude.ai/code/artifact/964d385d-ffba-408f-91d5-6e69b543094d

## What it shows

- VantageScore penetration over time (by UPB and by loan count), Total / Fannie / Freddie
- Fannie-vs-Freddie "race", stacked issuance and VS balance, WA Classic FICO
- **FICO-only / VS-only / Both / Neither** cross-tab (Both is always 0 — VS is delivered standalone)
- **Lender view**: who's driving adoption (UWM dominates), and each lender's penetration over time
- VS penetration by product term

Everything is loan-level (each loan counted once), so every view reconciles.

## Monthly refresh (the runbook)

1. **New files post** (~4th–6th business day of the following month). See `FETCH.md`.
2. **Log in** to both portals (Fannie + Freddie — separate logins).
3. **Download** `FNM_ILLD_YYYYMM.zip` and `FRE_ILLD_YYYYMM.zip` into `data/`
   (Claude can drive this once you're logged in; see `FETCH.md` for the URL trick).
4. **Rebuild:**
   ```
   python src/refresh.py
   ```
   This extracts the zips, rebuilds `master.json`, regenerates `output/dashboard.html`,
   and writes `output/monthly.csv` + `output/lender_by_month.csv`.
5. **Publish:** re-publish `output/dashboard.html` to the same Artifact URL (ask Claude,
   or open the file to view locally).

## Layout

```
agency-mbs-tracker/
  data/                     # *_ILLD_*.zip + extracted .txt   (local only, not published)
  src/
    master_build.py         # all loan-level files -> master.json (the one analysis)
    generate_dashboard.py   # master.json + template.html -> output/dashboard.html
    template.html           # the dashboard shell with a //__DATA__ injection marker
    refresh.py              # orchestrator: extract -> build -> generate -> CSVs
  output/                   # dashboard.html, monthly.csv, lender_by_month.csv
  master.json               # intermediate data (rebuilt each run)
  FETCH.md                  # how to download the monthly files
  README.md
```

## Method

- **Source:** month-end loan-level files `FNM_ILLD` / `FRE_ILLD`, both GSEs. Each loan once.
- **has FICO / has VS:** a valid 300–850 score in Classic FICO (or Origination Classic FICO
  for modified/reperforming loans); same for VantageScore 4.0. `9999`=N/A, `7777`=N/Applicable;
  `777` is a *valid* score.
- **VS-scored = VS-only**, since no loan carries both.
- **Penetration** = VS-only ÷ all newly-issued loans, by UPB and by loan count.
- **Products** bucketed by loan term; **lenders** by Seller Name.

## Regulatory context

FHFA authorized VantageScore 4.0 for GSE loans (Jul 2025); disclosure fields went live
Nov 17 2025; the interim phase permitting either Classic FICO or VS4 opened Apr 22 2026 to a
limited lender set. Not investment advice. Data is public GSE disclosure; keep local.
