import os
import re
import statistics
import time
from functools import lru_cache

import requests
from flask import Flask, request, render_template_string
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

SCRAPPA_BASE = "https://scrappa.co/api/vinted"
COUNTRY = "IT"
REQUEST_TIMEOUT = 30

# Conservative liquidity prior based on recent resale-market research.
# It affects the score, NOT the market-price estimate.
BRAND_LIQUIDITY = {
    "hermes": 1.00,
    "goyard": 0.98,
    "chanel": 0.96,
    "louis vuitton": 0.96,
    "the row": 0.94,
    "miu miu": 0.93,
    "prada": 0.91,
    "gucci": 0.90,
    "bottega veneta": 0.89,
    "dior": 0.89,
    "fendi": 0.88,
    "loewe": 0.88,
    "saint laurent": 0.87,
    "celine": 0.87,
    "balenciaga": 0.84,
}

DEFAULT_BRANDS = [
    "Hermès", "Chanel", "Louis Vuitton", "Goyard", "Prada", "Gucci",
    "Dior", "Fendi", "Bottega Veneta", "Saint Laurent", "Celine",
    "Loewe", "Miu Miu", "Balenciaga", "The Row"
]

HTML = r"""
<!doctype html>
<html lang="it">
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Second Hand Hunter — Deal Engine</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f5f7;margin:0;padding:18px;color:#111}
.card{max-width:850px;margin:auto}.box,.deal,.item{background:#fff;border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 2px 12px #0001}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:650px){.grid{grid-template-columns:1fr}}
label{font-weight:700;font-size:14px}.hint{font-size:12px;color:#777;margin:4px 0 12px}
input,select{width:100%;box-sizing:border-box;padding:12px;border:1px solid #ddd;border-radius:12px;margin:6px 0 12px;font-size:16px;background:#fff}
select[multiple]{min-height:210px}.checks{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 12px;margin:8px 0 14px}.checks label{font-weight:500}
button{width:100%;padding:14px;border:0;border-radius:12px;font-size:17px;font-weight:800;background:#111;color:white}
.score{font-size:28px;font-weight:900}.green{color:#16803c}.orange{color:#b25b00}.red{color:#b42318}
.muted{color:#666;font-size:14px}.price{font-size:21px;font-weight:850}.tag{display:inline-block;background:#eee;border-radius:8px;padding:4px 8px;margin:3px;font-size:12px}
a{color:#111;font-weight:700}.warn{background:#fff8e6}.danger{background:#fff0ef}
.metric{display:inline-block;margin:6px 12px 0 0}.metric b{display:block;font-size:18px}
</style>
</head>
<body><div class="card">
<div class="box">
<h1>🔥 Second Hand Hunter</h1>
<p class="muted">Motore di ricerca e valutazione per potenziali affari nel second-hand.</p>
<form method="post">
<div class="grid">
<div>
<label>Keyword aggiuntive</label>
<input name="query" value="{{query}}" placeholder="es. Re-Edition, Baguette, Speedy">
<div class="hint">Lascia vuoto per analizzare le borse in generale.</div>
</div>
<div>
<label>Prezzo massimo d'acquisto (€)</label>
<input name="max_price" type="number" step="1" min="1" value="{{max_price}}">
</div>
<div>
<label>Profitto minimo stimato (€)</label>
<input name="min_profit" type="number" step="1" min="0" value="{{min_profit}}">
</div>
<div>
<label>Sconto minimo sul mercato (%)</label>
<input name="min_discount" type="number" step="1" min="0" max="90" value="{{min_discount}}">
</div>
<div>
<label>Deal Score minimo</label>
<input name="min_score" type="number" step="1" min="0" max="100" value="{{min_score}}">
</div>
<div>
<label>Candidati da arricchire</label>
<input name="enrich_limit" type="number" step="1" min="0" max="12" value="{{enrich_limit}}">
<div class="hint">0 = niente chiamate extra. 6–10 è un buon compromesso.</div>
</div>
</div>
<label>Brand da cercare</label>
<select name="brands" multiple>
{% for b in brands %}<option value="{{b}}" {% if b in selected_brands %}selected{% endif %}>{{b}}</option>{% endfor %}
</select>
<div class="hint">Su iPhone tieni premuto per selezionare più brand.</div>
<button>CERCA E VALUTA GLI AFFARI</button>
</form>
</div>

{% if error %}<div class="box danger">⚠️ <b>Errore:</b> {{error}}</div>{% endif %}

{% if searched and not error %}
<div class="box">
<div class="metric"><span class="muted">Annunci analizzati</span><b>{{count}}</b></div>
<div class="metric"><span class="muted">Potenziali affari</span><b>{{deal_count}}</b></div>
<div class="metric"><span class="muted">Ricerche API</span><b>{{api_calls}}</b></div>
{% if note %}<p class="muted">{{note}}</p>{% endif %}
</div>

{% if deals %}<h2>🚨 Affari rilevati</h2>{% endif %}
{% for d in deals %}
<div class="deal">
<div class="score {% if d.score>=80 %}green{% elif d.score>=65 %}orange{% else %}red{% endif %}">{{d.score}}/100</div>
<h2>{{d.title}}</h2>
<p>{{d.brand}}{% if d.condition %} · {{d.condition}}{% endif %}</p>
<p><span class="tag">{{d.label}}</span><span class="tag">{{d.discount_pct}}% sotto mercato</span></p>
<p>
<b>Acquisto:</b> €{{"%.2f"|format(d.price)}}<br>
<b>Mercato richiesto:</b> €{{"%.2f"|format(d.market_value)}}<br>
<b>Prezzo di rivendita prudente:</b> €{{"%.2f"|format(d.resale_value)}}<br>
<b>Profitto potenziale lordo:</b> €{{"%.2f"|format(d.profit)}}
</p>
{% if d.risk_flags %}<p class="muted">⚠️ {{d.risk_flags|join(' · ')}}</p>{% endif %}
<a href="{{d.url}}" target="_blank">Apri annuncio →</a>
</div>
{% endfor %}

<h2>📋 Migliori risultati</h2>
{% for d in items %}
<div class="item">
<div class="score {% if d.score>=80 %}green{% elif d.score>=65 %}orange{% else %}red{% endif %}">{{d.score}}/100</div>
<h3>{{d.title}}</h3>
<p class="price">€{{"%.2f"|format(d.price)}}</p>
<p>{{d.brand}}{% if d.condition %} · {{d.condition}}{% endif %}</p>
<span class="tag">Mercato €{{"%.0f"|format(d.market_value)}}</span>
<span class="tag">{{d.discount_pct}}% sotto</span>
<span class="tag">Profitto €{{"%.0f"|format(d.profit)}}</span>
<br><a href="{{d.url}}" target="_blank">Apri annuncio →</a>
</div>
{% endfor %}
{% if not items %}<div class="box">Nessun risultato utilizzabile.</div>{% endif %}
{% endif %}
</div></body></html>
"""


def api_headers():
    key = os.getenv("SCRAPPA_API_KEY")
    if not key:
        raise RuntimeError("Manca la variabile SCRAPPA_API_KEY su Render.")
    return {"X-API-KEY": key, "Accept": "application/json"}


def money(value):
    if isinstance(value, dict):
        value = value.get("amount", value.get("value", value.get("price", 0)))
    try:
        return float(str(value).replace(",", ".") or 0)
    except (TypeError, ValueError):
        return 0.0


def make_url(x):
    url = x.get("url") or x.get("source_url") or x.get("item_url") or x.get("path")
    if url:
        if str(url).startswith("http"):
            return url
        if str(url).startswith("/"):
            return "https://www.vinted.it" + str(url)
        return str(url)
    item_id = x.get("id") or x.get("item_id")
    return f"https://www.vinted.it/items/{item_id}" if item_id else "https://www.vinted.it/"


def response_items(data):
    if not isinstance(data, dict):
        return [], {}
    payload = data.get("data")
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("results") or []
        pagination = payload.get("pagination") or {}
    else:
        items = data.get("items") or data.get("results") or []
        pagination = data.get("pagination") or {}
    return items if isinstance(items, list) else [], pagination


def api_get(path, params):
    r = requests.get(SCRAPPA_BASE + path, params=params, headers=api_headers(), timeout=REQUEST_TIMEOUT)
    if r.status_code == 401:
        raise RuntimeError("Scrappa ha rifiutato la API key (401).")
    if r.status_code == 403:
        raise RuntimeError("Scrappa ha risposto 403: controlla crediti/account.")
    if r.status_code >= 400:
        raise RuntimeError(f"Scrappa HTTP {r.status_code}: {r.text[:250]}")
    return r.json()


def search_items(query, max_price=None, per_page=50):
    params = {"query": query, "country": COUNTRY, "per_page": per_page, "order": "newest_first"}
    if max_price is not None:
        params["price_to"] = max_price
    data = api_get("/search", params)
    return response_items(data)


def similar_items(item_id):
    data = api_get("/similar-items", {"item_id": str(item_id), "country": COUNTRY, "page": 1})
    return response_items(data)[0]


def item_details(item_id):
    data = api_get("/item-details", {"item_id": str(item_id), "country": COUNTRY})
    if not isinstance(data, dict):
        return {}
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    item = payload.get("item") if isinstance(payload, dict) else None
    return item if isinstance(item, dict) else {}


def title_tokens(title):
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", (title or "").lower())
    stop = {"borsa","bag","pelle","vera","nuova","nuovo","ottime","ottima","come","da","donna","women","woman","con","the","di","in","per","del","della"}
    return [w for w in words if len(w) >= 3 and w not in stop][:8]


def condition_score(condition):
    c = (condition or "").lower()
    if any(k in c for k in ["nuovo", "new", "mai indoss", "nuova con cartell"]): return 1.0
    if any(k in c for k in ["ottimo", "very good", "excellent"]): return .92
    if any(k in c for k in ["buono", "good"]): return .78
    if any(k in c for k in ["soddisfacente", "satisfactory"]): return .62
    return .72


def brand_key(brand):
    return re.sub(r"[^a-z0-9 ]", "", (brand or "").lower()).strip()


def liquidity_for(brand):
    b = brand_key(brand)
    for name, value in BRAND_LIQUIDITY.items():
        if name in b or b in name:
            return value
    return .72


def extract_brand(x):
    return x.get("brand") or x.get("brand_title") or ""


def extract_condition(x):
    return x.get("condition") or x.get("status") or x.get("listing_status") or ""


def normalize_raw(x):
    return {
        "id": x.get("id") or x.get("item_id") or "",
        "title": x.get("title") or "Senza titolo",
        "brand": extract_brand(x),
        "condition": extract_condition(x),
        "price": money(x.get("price")),
        "url": make_url(x),
        "favs": money(x.get("favourite_count", x.get("favorite_count", x.get("favorites", 0)))),
        "views": money(x.get("view_count", x.get("views", 0))),
        "description": x.get("description") or "",
    }


def comparable_prices(candidate, pool):
    p = candidate["price"]
    tokens = set(title_tokens(candidate["title"]))
    brand = brand_key(candidate["brand"])
    prices = []
    for x in pool:
        q = money(x.get("price"))
        if q <= 0 or abs(q - p) < 0.01:
            continue
        xb = brand_key(extract_brand(x))
        if brand and xb and brand not in xb and xb not in brand:
            continue
        xt = set(title_tokens(x.get("title", "")))
        overlap = len(tokens & xt)
        # If the title contains a likely model name, favour listings sharing it.
        if len(tokens) >= 2 and overlap == 0:
            continue
        prices.append(q)
    return prices


def estimate_market(candidate, brand_pool):
    prices = comparable_prices(candidate, brand_pool)
    if len(prices) >= 5:
        prices = sorted(prices)
        # Trim extremes so one absurd listing does not dominate.
        lo = max(0, int(len(prices) * .10))
        hi = max(lo + 1, int(len(prices) * .90))
        trimmed = prices[lo:hi]
        return statistics.median(trimmed), len(trimmed), "model/title comparables"
    # Fall back to same-brand/category market, but use a conservative haircut.
    brand_prices = [money(x.get("price")) for x in brand_pool if money(x.get("price")) > 0]
    if len(brand_prices) >= 5:
        return statistics.median(brand_prices), len(brand_prices), "brand market"
    return 0, 0, "insufficient comparables"


def risk_flags(item):
    text = ((item.get("title") or "") + " " + (item.get("description") or "")).lower()
    flags = []
    if not item.get("description"):
        flags.append("descrizione assente")
    suspicious = ["replica", "fake", "falso", "inspired", "1:1", "super clone", "non so se originale", "non autentica"]
    if any(k in text for k in suspicious):
        flags.append("parole d'allerta autenticità")
    if item.get("price", 0) > 0 and item.get("market_value", 0) > item.get("price", 0) * 2.5:
        flags.append("prezzo eccezionalmente basso: verificare autenticità")
    return flags


def score_deal(item, market_value, comparable_count, detail=None):
    p = item["price"]
    if not p or not market_value:
        return 0, 0, 0, "NON VALUTABILE"

    # Active asking prices are not sold prices, so estimate a realizable resale value conservatively.
    resale = market_value * 0.92
    discount = max(0, (resale - p) / resale * 100) if resale else 0
    profit = resale - p

    liq = liquidity_for(item["brand"])
    cond = condition_score((detail or {}).get("condition") or item.get("condition"))
    evidence = min(1.0, comparable_count / 12.0)

    # 100-point score: economics 50, evidence 20, liquidity 15, condition 10, listing quality 5.
    economics = min(50, max(0, discount) * 0.72 + min(20, max(0, profit) / 10))
    evidence_points = 20 * evidence
    liquidity_points = 15 * liq
    condition_points = 10 * cond
    text_quality = 5 if (detail or {}).get("description") else 2
    raw = economics + evidence_points + liquidity_points + condition_points + text_quality

    # Penalty for extremely thin evidence: do not call a 1-comparable result a 90/100 deal.
    if comparable_count < 5:
        raw *= 0.78

    score = int(round(max(0, min(100, raw))))
    if score >= 85 and discount >= 35 and profit >= 100:
        label = "🔥 ECCELLENTE"
    elif score >= 75 and discount >= 25 and profit >= 60:
        label = "🟢 AFFARE"
    elif score >= 65 and discount >= 18 and profit >= 40:
        label = "🟡 INTERESSANTE"
    else:
        label = "🔴 DA LASCIARE"
    return score, resale, profit, label


def enrich_candidate(item):
    if not item["id"]:
        return item, None
    try:
        d = item_details(item["id"])
        if d:
            item["condition"] = d.get("condition") or item["condition"]
            item["description"] = d.get("description") or item["description"]
            item["brand"] = d.get("brand") or item["brand"]
            item["url"] = d.get("url") or d.get("source_url") or item["url"]
            item["favs"] = money(d.get("favorite_count", d.get("favourite_count", item["favs"])))
            item["views"] = money(d.get("view_count", d.get("views", item["views"])))
        return item, d
    except Exception:
        return item, None


def run_engine(query, brands, max_price, min_profit, min_discount, min_score, enrich_limit):
    all_candidates = []
    brand_pools = {}
    api_calls = 0

    for brand in brands:
        q = f"{brand} borsa"
        if query:
            q += f" {query}"
        cheap, _ = search_items(q, max_price=max_price, per_page=50)
        api_calls += 1
        market, _ = search_items(q, max_price=None, per_page=50)
        api_calls += 1
        brand_pools[brand] = market
        for x in cheap:
            row = normalize_raw(x)
            if row["price"] > 0 and row["price"] <= max_price:
                row["search_brand"] = brand
                all_candidates.append(row)

    # Deduplicate by listing ID.
    seen = set()
    candidates = []
    for x in all_candidates:
        key = x["id"] or x["url"]
        if key in seen:
            continue
        seen.add(key)
        candidates.append(x)

    # First-pass valuation without extra credits.
    scored = []
    for item in candidates:
        pool = brand_pools.get(item["search_brand"], [])
        market, comp_count, evidence = estimate_market(item, pool)
        if not market:
            continue
        score, resale, profit, label = score_deal(item, market, comp_count)
        item.update({
            "market_value": market,
            "resale_value": resale,
            "profit": profit,
            "discount_pct": round(max(0, (resale-item["price"])/resale*100), 1) if resale else 0,
            "score": score,
            "label": label,
            "comparable_count": comp_count,
            "evidence": evidence,
            "risk_flags": [],
        })
        scored.append(item)

    scored.sort(key=lambda x: (x["score"], x["profit"]), reverse=True)

    # Enrich only the strongest candidates to protect the free Scrappa quota.
    for item in scored[:max(0, enrich_limit)]:
        item, detail = enrich_candidate(item)
        api_calls += 1
        # Re-score after condition/description enrichment.
        score, resale, profit, label = score_deal(item, item["market_value"], item["comparable_count"], detail)
        item.update({
            "score": score,
            "resale_value": resale,
            "profit": profit,
            "discount_pct": round(max(0, (resale-item["price"])/resale*100), 1) if resale else 0,
            "label": label,
        })
        item["risk_flags"] = risk_flags(item)

    scored.sort(key=lambda x: (x["score"], x["profit"]), reverse=True)
    deals = [x for x in scored if x["score"] >= min_score and x["profit"] >= min_profit and x["discount_pct"] >= min_discount]
    return scored[:30], deals[:15], api_calls


@app.route("/", methods=["GET", "POST"])
def home():
    error = ""
    searched = False
    items = []
    deals = []
    count = 0
    api_calls = 0
    note = ""
    query = ""
    max_price = 300
    min_profit = 75
    min_discount = 25
    min_score = 70
    enrich_limit = 8
    selected_brands = DEFAULT_BRANDS[:]

    if request.method == "POST":
        searched = True
        query = request.form.get("query", "").strip()
        selected_brands = request.form.getlist("brands") or DEFAULT_BRANDS[:]
        try:
            max_price = float(request.form.get("max_price", 300) or 300)
            min_profit = float(request.form.get("min_profit", 75) or 75)
            min_discount = float(request.form.get("min_discount", 25) or 25)
            min_score = int(request.form.get("min_score", 70) or 70)
            enrich_limit = int(request.form.get("enrich_limit", 8) or 8)
            if max_price <= 0 or min_profit < 0 or not (0 <= min_discount <= 90) or not (0 <= min_score <= 100) or not (0 <= enrich_limit <= 12):
                raise ValueError
        except ValueError:
            error = "Controlla i filtri numerici."

        if not error:
            try:
                items, deals, api_calls = run_engine(
                    query, selected_brands, max_price, min_profit, min_discount, min_score, enrich_limit
                )
                count = len(items)
                note = "La stima usa prezzi richiesti attivi su Vinted; non equivale a prezzi di vendita conclusi. Per prudenza applichiamo un -8% alla mediana comparabile. L'autenticità non viene certificata dal bot."
            except requests.RequestException as e:
                error = f"Errore di collegamento a Scrappa: {e}"
            except Exception as e:
                error = str(e)

    return render_template_string(
        HTML,
        error=error, searched=searched, items=items, deals=deals, count=count,
        deal_count=len(deals), api_calls=api_calls, note=note, query=query,
        max_price=max_price, min_profit=min_profit, min_discount=min_discount,
        min_score=min_score, enrich_limit=enrich_limit, brands=DEFAULT_BRANDS,
        selected_brands=selected_brands,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
