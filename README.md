# Clothing ID

Point it at photos of a garment's care tag and the garment itself. It reads the tag,
describes the piece, says what it is, and gives a rough resale value with the reasoning
behind the number.

```
$ clothing-id tag.jpg front.jpg back.jpg

  Patagonia Snap-T Fleece Pullover
  ----------------------------------------
  brand                  Patagonia
  category               sweatshirt / fleece pullover
  era                    1990s
  size                   M
  fabric                 100% polyester
  made in                United States
  RN                     51884
  color                  forest green
  condition              good
  flaws                  light pilling on the body
  rarity signals         made in usa, deadstock colorway
  id confidence          88%

  Value estimate
  ----------------------------------------
  est. original retail   $115 USD
  resale range           $52 - $98 USD
  most likely            $72 USD
  confidence             79%

  How it was priced
        55.00  category baseline  (sweatshirt @ mainstream retail)
         2.10  brand tier: outdoor  (Patagonia)
         0.85  fabric  (polyester)
         0.72  condition  (good)
         1.45  era  (1990s (collectible brand))
         1.15  rarity signals  (made in usa)
         0.38  resale recovery  (outdoor tier)
```

## How it works

1. **Vision pass** (`identify.py`) — one Claude Opus 5 call with all photos and a
   structured output schema. It transcribes the tag verbatim, records dating clues,
   describes construction and condition, and identifies the item with an honest
   confidence score. Fields it cannot read stay `null` rather than being guessed.
2. **Valuation** (`valuation.py`) — a deterministic engine, not a second model guess:

   ```
   retail = category baseline × brand tier × fabric × construction
   resale = retail × tier recovery × condition × era × rarity × flaws × size
   ```

   Every multiplier that moved the number is returned in `value.factors`, so any
   estimate can be audited or re-tuned. The low/high band widens as identification
   confidence drops.
3. **Market check** (optional, `--market-check`) — a second call with Claude's web
   search tool pulls live resale listings, and the median comp is blended 55/45 with
   the model-based mid. A failed search degrades to the model-based estimate.

Brand tiers live in `brands.py` (~300 brands across fast fashion → ultra luxury, with
tag aliases like `Levi Strauss & Co.` → Levi's and sub-labels like RRL and Carhartt WIP
resolving to their own tiers). Tier decides both what the piece cost new and what
fraction of that a used one recovers — a Supreme box logo recovers ~62% of retail, a
Gap tee ~16%.

## Install

```bash
pip install -e ".[api,dev]"
export ANTHROPIC_API_KEY=sk-ant-...   # or: ant auth login
```

## Use

**CLI**

```bash
clothing-id tag.jpg front.jpg              # human-readable report
clothing-id tag.jpg front.jpg --json       # full structured report
clothing-id tag.jpg --market-check         # anchor to live resale listings
clothing-id tag.jpg --notes "small hole at the hem"
```

**HTTP**

```bash
uvicorn clothing_id.api:app --reload       # upload page at http://127.0.0.1:8000
curl -F images=@tag.jpg -F images=@front.jpg -F market_check=true \
     http://127.0.0.1:8000/identify
```

**Python**

```python
from clothing_id import analyze_paths

report = analyze_paths(["tag.jpg", "front.jpg"], market_check=True)
print(report.summary())
print(report.value.mid, report.value.low, report.value.high)
for factor in report.value.factors:
    print(factor.name, factor.multiplier, factor.note)
```

`analyze_uploads([(bytes, media_type), ...])` is the in-memory equivalent for web
handlers.

## Photo tips

The estimate is only as good as the photos. Best results from: one straight-on shot of
the brand/care tag with the text in focus, one of the whole garment flat, and one of any
flaw. Interior tags date a piece far more reliably than the garment does — a single-stitch
hem, a union label or a "Made in USA" line moves the number more than the silhouette.

## Accuracy

This is a triage tool, not an appraisal. It prices the *category* of item well and the
*specific* item roughly. Known limits:

- Counterfeits are not detected. A convincing fake reads as the real brand.
- Unlisted brands fall back to a mainstream baseline; add them to `BRAND_TIERS`.
- Without `--market-check` the number comes from tier heuristics, not live demand.
  Hyped items (recent collabs, sneakers) move faster than the tables do — use the
  market check for those.
- Condition grading from photos is conservative; flaws you can feel but not see are missed.

## Tests

```bash
pytest        # 43 tests, no network or API key needed - the client is stubbed
```
