# Clothing ID

Point it at photos of a garment's care tag and the garment itself. It reads the tag,
identifies the piece, checks the RN against the registry, and prices it **from real
sales** — comparable listings with dates and URLs, not a made-up multiplier.

```
$ clothing-id tag.jpg front.jpg

  Patagonia Synchilla Snap-T Pullover
  ----------------------------------------
  brand                  Patagonia
  category               sweatshirt / fleece pullover
  era                    1990s
  size                   M
  fabric                 100% polyester
  made in                United States
  RN                     RN 51884
  condition              good
  flaws                  light pilling on the body
  rarity signals         made in usa, single stitch
  id confidence          88%
  RN registrant          Patagonia, Inc. (confirms brand)

  Value estimate
  ----------------------------------------
  basis                  priced from observed sales
  resale range           $74 - $96 USD
  most likely            $95 USD
  model says             $54
  est. original retail   $98 USD
  confidence             59%

  Evidence
  listings used          8 (8 sold, 0 asking)
  covering               2026-04-27 to 2026-09-01
  sample median          $95
  spread (p20-p80)       23% of mid
  sources                ebay-sold: 6, history: 2

  Comparables
          $95  sold  2026-09-01  Patagonia Synchilla Snap-T M
                https://www.ebay.com/itm/...
          $88  sold  2026-08-14  Patagonia Snap-T Fleece Pullover Green M
                https://www.ebay.com/itm/...
```

## Where the numbers come from

Every estimate says which of three bases produced it, and never pretends to more:

| basis | meaning |
| --- | --- |
| `observed` | priced from real transactions alone |
| `blended` | too few observations to stand alone, mixed with the model in proportion to the evidence |
| `modeled` | no market data was available; heuristic tables, labelled as a guess |

**Sources of real data**, in the order they are used:

1. **Your local history database** (`~/.clothing-id/history.db`) — every price this tool
   has ever seen: your own past sales, imported marketplace exports, and everything
   fetched on previous runs. Works with no network. Import with
   `clothing-id import sold.csv`.
2. **eBay Marketplace Insights** — what comparable items *actually sold for* in the last
   90 days. Needs a production keyset with Buy API access
   (`EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`).
3. **eBay Browse** — current asking prices, available to any production keyset. Asks are
   weaker evidence and are stored as such.
4. **Cited web search** — the fallback when no eBay keyset is configured. The model
   reports listings it found on the resale market; rows without a price *and* a source
   URL are discarded rather than guessed at.

Everything fetched is written back into the history database, so the evidence base grows
with use and later valuations get cheaper and better.

**How observations become a price** (`pricing.py`):

- Each comparable is adjusted onto the target's **condition** grade. The ratios between
  grades are measured from the sample when there are enough sales in each grade, and
  fall back to documented priors otherwise — the report says which was used.
- **Asking prices are discounted to sold terms** by the sold/ask ratio measured in the
  same sample, or a 0.82 prior when it cannot be measured.
- **Older sales are carried forward to today's money** by a price trend fitted to the
  observations (least squares on log price vs. age), when there are ≥12 observations
  spanning ≥180 days. Otherwise no trend is applied and the report says so.
- What remains is weighted by **recency** (180-day half-life), evidence quality (a sale
  counts more than an ask) and size match, then reduced to a **weighted median with a
  real 20th–80th percentile band**. Gross outliers are trimmed with a median-absolute-
  deviation rule, so one mispriced lot cannot drag the estimate.
- **Confidence is earned**: it rises with effective sample size and the share of
  completed sales, and falls with spread and staleness.

The heuristic model (`valuation.py`) still exists, but only as the labelled fallback:

```
retail = category baseline × brand tier × fabric × construction
resale = retail × tier recovery × condition × era × rarity × flaws × size
```

Every multiplier it applies is reported in `value.factors`, so a modeled number can be
audited and re-tuned. Brand tiers live in `brands.py` (~300 brands, with tag aliases like
`Levi Strauss & Co.` → Levi's and sub-labels like RRL and Carhartt WIP).

## Identification, and checking it

The vision pass (`identify.py`) is one Claude Opus 5 call with structured output. It
transcribes the tag verbatim, records dating clues (logo variant, union label, "Made in
USA", care-symbol style), describes construction and condition, and gives an honest
confidence. Fields it cannot read stay `null` rather than being guessed.

The one hard check a garment carries is its **RN number**. `rn.py` compares the RN on the
tag with the company it is registered to, which catches relabels and fakes that copy a
logo but not a number. The FTC publishes no bulk file or public API for the RN database,
so this tool does not ship one and will not invent entries: supply a directory and it
verifies, otherwise it prints the [FTC lookup URL](https://rn.ftc.gov/rns) for the number
and claims nothing.

```bash
export CLOTHING_ID_RN_FILE=~/rn-directory.csv    # columns: rn,company
```

## Install

```bash
pip install -e ".[api,dev]"
export ANTHROPIC_API_KEY=sk-ant-...      # or: ant auth login

# optional, for sold-price data
export EBAY_CLIENT_ID=...                # production keyset with Buy API access
export EBAY_CLIENT_SECRET=...
export CLOTHING_ID_RN_FILE=~/rn.csv      # optional, for RN verification
```

## Use

**CLI**

```bash
clothing-id tag.jpg front.jpg            # identify, look up the market, price it
clothing-id tag.jpg --offline            # price from stored history only, no network
clothing-id tag.jpg --json               # full report incl. evidence and comparables
clothing-id tag.jpg --notes "small hole at the hem"

clothing-id import sold.csv              # load real sales into the history database
clothing-id import asks.csv --kind ask --source depop
clothing-id stats                        # what evidence is on file
```

`import` reads eBay sold-listing exports, Poshmark/Depop sales reports and hand-kept
spreadsheets: columns are matched case-insensitively (`sold price`/`price`/`sale price`,
`sold date`/`date`, `brand`, `category`, `size`, `condition`, `url`), rows without a
price and a date are skipped, and re-importing the same file adds nothing twice.

**HTTP**

```bash
uvicorn clothing_id.api:app --reload     # upload page at http://127.0.0.1:8000
curl -F images=@tag.jpg -F images=@front.jpg -F market=true \
     http://127.0.0.1:8000/identify
```

**Python**

```python
from clothing_id import SalesHistory, analyze_paths, estimate_value, import_csv

import_csv("my-sales.csv")                       # your real sales become the baseline
report = analyze_paths(["tag.jpg", "front.jpg"])

print(report.summary())
print(report.value.method)                       # observed | blended | modeled
print(report.value.evidence.observation_count, report.value.evidence.date_range)
for comp in report.value.comparables:
    print(comp.price, "sold" if comp.sold else "ask", comp.observed_on, comp.url)
```

Priced offline from history alone:

```python
with SalesHistory() as history:
    observations = history.query(brand="Patagonia", category="jacket")
value = estimate_value(read, observations=observations)
```

## Photo tips

One straight-on shot of the brand/care tag with the text in focus, one of the whole
garment flat, one of any flaw. Interior tags date a piece far more reliably than the
garment does — a single-stitch hem, a union label or a "Made in USA" line moves the
number more than the silhouette.

## Accuracy

This is a triage tool, not an appraisal.

- **A modeled estimate is a guess.** With no comparable sales on file and no market
  access, the number comes from brand and category tables. The report says `modeled`
  when that happens — treat it as an order of magnitude, not a price.
- eBay's sold-data window is **90 days**, so long-run trends only appear once your own
  history has accumulated. Until then the report will say a trend could not be fitted.
- Comparable *matching* is by brand, category, size and condition — not by exact model.
  A rare colorway priced against ordinary ones will read low.
- Counterfeits are not detected visually. RN verification is the only real check, and
  only when you have supplied a directory.
- Condition grading from photos is conservative; flaws you can feel but not see are
  missed, and every observation's condition comes from how the *seller* graded it.

## Tests

```bash
pytest        # 111 tests, no network or API key needed - clients and sources are stubbed
```

Covered: brand resolution, the observation store and CSV import, condition/ask-ratio
measurement, trend fitting, outlier trimming, recency weighting, observed vs. blended vs.
modeled selection, eBay response mapping and request shape, web-search hygiene (no price
without a URL), RN verification, the CLI and the HTTP layer.
