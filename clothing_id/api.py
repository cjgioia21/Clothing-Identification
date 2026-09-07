"""HTTP service: POST photos, get an identification and a value estimate back.

    uvicorn clothing_id.api:app --reload
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from .identify import DEFAULT_MODEL
from .images import MAX_IMAGES, ImageError
from .models import Report
from .pipeline import analyze_uploads

app = FastAPI(title="Clothing ID", version="0.1.0")

MAX_UPLOAD_BYTES = 12 * 1024 * 1024

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clothing ID</title>
<style>
  :root { color-scheme: light dark; --fg:#141414; --bg:#faf9f7; --muted:#6b6b6b; --line:#e0ddd7; --accent:#1b4d3e; }
  @media (prefers-color-scheme: dark) {
    :root { --fg:#ececec; --bg:#131313; --muted:#9a9a9a; --line:#2c2c2c; --accent:#7fd1b3; }
  }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
  main { max-width:720px; margin:0 auto; padding:40px 20px 80px; }
  h1 { font-size:24px; margin:0 0 4px; letter-spacing:-0.01em; }
  p.sub { color:var(--muted); margin:0 0 28px; }
  form { border:1px solid var(--line); border-radius:12px; padding:20px; background:transparent; }
  label { display:block; font-weight:600; margin:16px 0 6px; font-size:13px;
          text-transform:uppercase; letter-spacing:0.04em; color:var(--muted); }
  label:first-child { margin-top:0; }
  input[type=file], input[type=text] { width:100%; box-sizing:border-box; padding:9px 10px;
          border:1px solid var(--line); border-radius:8px; background:transparent; color:inherit; }
  .row { display:flex; align-items:center; gap:8px; margin-top:16px; color:var(--muted); font-size:14px; }
  button { margin-top:20px; width:100%; padding:11px; border:0; border-radius:8px;
           background:var(--accent); color:var(--bg); font-size:15px; font-weight:600; cursor:pointer; }
  button[disabled] { opacity:.6; cursor:progress; }
  #out { margin-top:28px; }
  .card { border:1px solid var(--line); border-radius:12px; padding:20px; }
  .price { font-size:30px; font-weight:650; letter-spacing:-0.02em; }
  .range { color:var(--muted); margin-top:2px; }
  dl { display:grid; grid-template-columns:auto 1fr; gap:6px 16px; margin:18px 0 0; font-size:14px; }
  dt { color:var(--muted); }
  dd { margin:0; }
  table { width:100%; border-collapse:collapse; margin-top:18px; font-size:13px; }
  td { padding:4px 0; border-bottom:1px solid var(--line); }
  td.m { text-align:right; width:70px; font-variant-numeric:tabular-nums; }
  .err { color:#b3261e; }
</style>
</head>
<body>
<main>
  <h1>Clothing ID</h1>
  <p class="sub">Photograph the care tag and the garment. Get the brand, the details and a rough resale range.</p>
  <form id="f">
    <label for="images">Photos (tag + garment, up to {max_images})</label>
    <input id="images" name="images" type="file" accept="image/*" multiple required>
    <label for="notes">Notes (optional)</label>
    <input id="notes" name="notes" type="text" placeholder="thrifted, small hole at the hem">
    <div class="row"><input id="market" name="market_check" type="checkbox"><label for="market" style="margin:0;text-transform:none;letter-spacing:0;font-weight:400;">Search live resale listings (slower)</label></div>
    <button type="submit">Identify</button>
  </form>
  <div id="out"></div>
</main>
<script>
const f = document.getElementById('f'), out = document.getElementById('out');
const money = n => '$' + Math.round(n).toLocaleString();
f.addEventListener('submit', async e => {
  e.preventDefault();
  const btn = f.querySelector('button');
  btn.disabled = true; btn.textContent = 'Reading tags\\u2026';
  out.innerHTML = '';
  const fd = new FormData();
  for (const file of document.getElementById('images').files) fd.append('images', file);
  const notes = document.getElementById('notes').value;
  if (notes) fd.append('notes', notes);
  if (document.getElementById('market').checked) fd.append('market_check', 'true');
  try {
    const res = await fetch('/identify', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    out.innerHTML = render(data);
  } catch (err) {
    out.innerHTML = '<p class="err">' + err.message + '</p>';
  } finally {
    btn.disabled = false; btn.textContent = 'Identify';
  }
});
function render(r) {
  const v = r.value, i = r.identification, t = r.tag, vis = r.visual;
  const rows = v.factors.map(x =>
    `<tr><td>${esc(x.name)}${x.note ? ' <span style="color:var(--muted)">(' + esc(x.note) + ')</span>' : ''}</td>` +
    `<td class="m">${x.multiplier.toFixed(2)}</td></tr>`).join('');
  const facts = [
    ['Brand', i.brand || 'unidentified'], ['Line', i.sub_label], ['Category', i.category],
    ['Era', i.era], ['Size', t.size], ['Made in', t.country_of_origin],
    ['Color', vis.primary_color], ['Condition', vis.condition_grade],
    ['Flaws', (vis.flaws || []).join(', ')],
    ['Rarity', (i.rarity_signals || []).join(', ')],
    ['Est. retail', money(v.retail_estimate)],
    ['Confidence', Math.round(v.confidence * 100) + '%'],
  ].filter(([, val]) => val).map(([k, val]) => `<dt>${k}</dt><dd>${esc(String(val))}</dd>`).join('');
  return `<div class="card">
    <div class="price">${money(v.mid)}</div>
    <div class="range">likely range ${money(v.low)} \\u2013 ${money(v.high)} ${esc(v.currency)}</div>
    <dl>${facts}</dl>
    <table>${rows}</table>
    ${(v.notes || []).map(n => '<p class="range">' + esc(n) + '</p>').join('')}
  </div>`;
}
function esc(s) { return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
</script>
</body>
</html>
""".replace("{max_images}", str(MAX_IMAGES))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/identify", response_model=Report)
async def identify(
    images: List[UploadFile] = File(..., description="photos of the tag and the garment"),
    notes: Optional[str] = Form(None),
    market_check: bool = Form(False),
    model: str = Form(DEFAULT_MODEL),
    currency: str = Form("USD"),
) -> Report:
    if not images:
        raise HTTPException(status_code=400, detail="At least one photo is required.")
    if len(images) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_IMAGES} photos.")

    uploads: List[tuple[bytes, str]] = []
    for upload in images:
        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"{upload.filename} is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"{upload.filename} is larger than 12 MB.")
        uploads.append((data, upload.content_type or "image/jpeg"))

    try:
        return analyze_uploads(
            uploads,
            model=model,
            notes=notes,
            market_check=market_check,
            currency=currency,
        )
    except ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc
