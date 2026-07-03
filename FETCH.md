# Fetching the monthly loan-level files

Each refresh needs exactly **two files** for the new month:

- `FNM_ILLD_YYYYMM.zip` — Fannie Mae month-end loan-level issuance
- `FRE_ILLD_YYYYMM.zip` — Freddie Mac month-end loan-level issuance

They usually post on the **4th–6th business day** of the following month.

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
// returns [{name, href}] for this-and-next month's loan-level files
[...document.querySelectorAll('a')]
  .map(a => ({name:a.textContent.trim(), href:a.getAttribute('href')}))
  .filter(x => /^F(NM|RE)_ILLD_\d{6}\.zip$/.test(x.name));
```

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
- Mid-month peek: the intraday files (`FNM_ILLD_YYYYMMDD_N.zip`) aggregate to a
  month-to-date snapshot — opt-in, more files to pull. Not wired into `refresh.py` yet.
