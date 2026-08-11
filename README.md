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
- **Loan purpose**: purchase vs cash-out refi vs rate/term refi over time, plus a
  **loan-type filter** that re-cuts every lender and vintage card within one purpose

Everything is loan-level (each loan counted once), so every view reconciles.

### The loan-type filter

The `Loan Type Filter` bar sits above the lender block and governs the four cards
below it — top-10 lenders, adoption over time, month-to-date, and origination
vintage. Picking a purpose re-cuts those cards *entirely* within it: the lender
ranking, the penetration denominator and the share-of-market denominator all
move together, so a lender's purchase rate and its cash-out rate are directly
comparable. Everything above the bar always covers all loan types.

Why it matters: refis run roughly 3x purchase penetration, and that is not just a
mix effect from refi-heavy adopters — it holds *within* every lender that has
adopted. UWM leads in rate/term, Rocket in cash-out, AmeriSave is cash-out-only.

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
   and writes the CSVs (`monthly`, `lender_by_month`, `vintage`, `purpose_by_month`,
   `lender_by_purpose`).
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
  output/                   # dashboard.html + the CSVs
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
- **Loan purpose** from the `Loan Purpose` field: `P` purchase, `C` cash-out refi,
  `N` rate/term refi. A fourth code `M` (modified, reperforming pools) is not a new
  origination and carries no VantageScore — it is excluded from the three purpose
  series but stays in the unfiltered totals. In `master.json` every `*_p` key mirrors
  its unsplit counterpart, and the splits reconcile to the totals exactly.

## Regulatory context

FHFA authorized VantageScore 4.0 for GSE loans (Jul 2025); disclosure fields went live
Nov 17 2025; the interim phase permitting either Classic FICO or VS4 opened Apr 22 2026 to a
limited lender set. Not investment advice. Data is public GSE disclosure; keep local.
