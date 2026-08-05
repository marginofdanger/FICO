# Fetching the loan-level files

## The three file families

| Family | Files | Cadence | What it feeds |
|---|---|---|---|
| **Month-end loan-level** (required) | `FNM_ILLD_YYYYMM.zip`, `FRE_ILLD_YYYYMM.zip` | monthly, 1st business day of the following month | everything — the `series`, cross-tab, lenders, product mix, and cohorts |
| **Intraday loan-level** (optional) | `FNM_ILLD_YYYYMMDD_N.zip`, `FRE_ILLD_YYYYMMDD_N.zip` | mid-month cuts | the origination-cohort chart + a provisional month-to-date headline. **Wired up** — just drop them in `data/`. |
| **Daily new-issue security-level** (optional) | *name TBC — enumerate from the portal* | daily at issuance | not parsed yet; would give a daily read on pools-containing-VS ahead of any loan-level file |

Month-end files post on the **first business day** of the following month (June
2026 issuance posted Jul 1, 2026). The intraday cuts are the reason the tracker
can see a ramp weeks before the month-end file lands — during a fast ramp the
cohort view moves a lot between cuts.

**Do not** mix families for the same month: `master_build` ignores intraday files
for any month that already has its month-end file, because the month-end file is
a superset. Within a month, loans are deduped on `Loan Identifier`, so it does
not matter whether the cuts are cumulative or incremental.

## Where they live

Both GSEs use the same platform (`mbs-securities.com`), and the files sit behind a
**free login on each site separately**:

- Fannie: <https://fanniemae.mbs-securities.com/> → *Data Files and Reports* → Single-Class → Issuance → **MBS Month-end Issuance Loan Level**
- Freddie: <https://freddiemac.mbs-securities.com/> → same path

## Download mechanism (why this is scripted)

- The security *detail* pages render to a canvas and can't be scraped — always use the **data-file downloads**, not the UI.
- Clicking a file link via automation does **not** trigger a download. Instead, navigate directly to the file's API URL:
  `https://{fanniemae|freddiemac}.mbs-securities.com/api/report/download/{REPORT_ID}/{FILE}.zip`
- The `REPORT_ID` **changes every month**, so grab the current one from the page. With the data-files page open and logged in, run this in the browser console (or have Claude run it):

```js
// Enumerate every downloadable file on the page, tagged by family.
// Run on the Data Files and Reports listing, logged in.
[...document.querySelectorAll('a')]
  .map(a => ({name: a.textContent.trim(), href: a.getAttribute('href')}))
  .filter(x => /\.(zip|txt|csv)$/i.test(x.name))
  .map(x => ({
    ...x,
    family: /^F(NM|RE)_ILLD_\d{6}\.zip$/.test(x.name)     ? 'month-end loan-level'
          : /^F(NM|RE)_ILLD_\d{8}(_\d+)?\.zip$/.test(x.name) ? 'intraday loan-level'
          : 'other'
  }));
```

Anything landing in `other` is worth a look — that is where the daily
new-issue security-level files will show up, and their exact names are what the
third family above is still missing.

Then navigate the logged-in tab to `https://<host>{href}` to download. Files land in your
Downloads folder.

## After downloading

Drop both `.zip` files into `agency-mbs-tracker/data/`, then run `python src/refresh.py`
(see README). `refresh.py` extracts and rebuilds everything; the raw `.zip`/`.txt` stay
local and are never published.

## Notes

- **Only loan-level (`_ILLD_`) is needed** — it yields issuance, WA FICO, VantageScore
  penetration, the FICO/VS/Both cross-tab, the lender breakdown, and the product mix.
  The `_IS_`/`_ISS_` security files are not required.
- Backfill: to rebuild history, download `FNM_ILLD` + `FRE_ILLD` for every month you want
  (VantageScore was zero before **April 2026**, so earlier months only set the denominator).
- Backfill also *sharpens the cohort chart*: a cohort is only marked complete once the
  issuance files for cohort−2 … cohort are all present, so more history means more
  solid bars and fewer hatched ones.
- Mid-month peek: drop any `F{NM,RE}_ILLD_YYYYMMDD_N.zip` into `data/` and re-run
  `refresh.py`. They are excluded from the month-end `series` on purpose and only
  move the cohort chart and the month-to-date line.
