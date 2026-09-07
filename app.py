import os
import re
import statistics
from functools import lru_cache

import requests
from flask import Flask, request, render_template_string
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

SCRAPPA_BASE = "https://scrappa.co/api/vinted"
COUNTRY = "IT"
REQUEST_TIMEOUT = 30

# Research prior: used only as a small liquidity component, never as the market-price source.
# 2025 resale reports show very different retention/demand by brand and model.
BRAND_LIQUIDITY = {
    "hermes": 1.00, "goyard": .98, "chanel": .96, "louis vuitton": .96,
    "the row": .94, "miu miu": .93, "prada": .91, "gucci": .90,
    "bottega veneta": .89, "dior": .89, "fendi": .88, "loewe": .88,
    "saint laurent": .87, "celine": .87, "balenciaga": .84,
    "valentino": .82, "givenchy": .80, "chloe": .82, "jacquemus": .80,
}

DEFAULT_BRANDS = [
    "Hermès", "Chanel", "Louis Vuitton", "Goyard", "Prada", "Gucci",
    "Dior", "Fendi", "Bottega Veneta", "Saint Laurent", "Celine",
    "Loewe", "Miu Miu", "Balenciaga", "The Row", "Valentino", "Chloé",
]

HTML = r"""
<!doctype html><html lang="it"><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Second Hand Hunter — Deal Engine</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f5f7;margin:0;padding:18px;color:#111}
.card{max-width:900px;margin:auto}.box,.deal,.item{background:#fff;border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 2px 12px #0001}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:650px){.grid{grid-template-columns:1fr}}
label{font-weight:700;font-size:14px}.hint{font-size:12px;color:#777;margin:4px 0 12px}
input,select{width:100%;box-sizing:border-box;padding:12px;border:1px solid #ddd;border-radius:12px;margin:6px 0 12px;font-size:16px;background:#fff}
select[multiple]{min-height:210px}.checks{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 12px;margin:8px 0 14px}.checks label{font-weight:500}
button{width:100%;padding:14px;border:0;border-radius:12px;font-size:17px;font-weight:800;background:#111;color:white}
.score{font-size:28px;font-weight:900}.green{color:#16803c}.orange{color:#b25b00}.red{color:#b42318}
.muted{color:#666;font-size:14px}.price{font-size:21px;font-weight:850}.tag{display:inline-block;background:#eee;border-radius:8px;padding:4px 8px;margin:3px;font-size:12px}
a{color:#111;font-weight:700}.danger{background:#fff0ef}.metric{display:inline-block;margin:6px 12px 0 0}.metric b{display:block;font-size:18px}
</style></head><body><div class="card">
<div class="box"><h1>🔥 Second Hand Hunter</h1><p class="muted">Ricerca mirata + stima mercato + Deal Score.</p>
<form method="post"><div class="grid">
<div><label>Modello / keyword opzionale</label><input name="query" value="{{query}}" placeholder="es. Re-Edition, Baguette, Speedy"><div class="hint">Vuoto = ricerca generale di borse per i brand selezionati.</div></div>
<div><label>Prezzo massimo d'acquisto (€)</label><input name="max_price" type="number" step="1" min="1" value="{{max_price}}"></div>
<div><label>Profitto minimo stimato (€)</label><input name="min_profit" type="number" step="1" min="0" value="{{min_profit}}"></div>
<div><label>Sconto minimo sul mercato (%)</label><input name="min_discount" type="number" step="1" min="0" max="90" value="{{min_discount}}"></div>
<div><label>Deal Score minimo</label><input name="min_score" type="number" step="1" min="0" max="100" value="{{min_score}}"></div>
<div><label>Candidati da arricchire</label><input name="enrich_limit" type="number" step="1" min="0" max="10" value="{{enrich_limit}}"><div class="hint">Dettagli completi Scrappa solo sui migliori candidati.</div></div>
</div>
<label>Brand</label><select name="brands" multiple>{% for b in brands %}<option value="{{b}}" {% if b in selected_brands %}selected{% endif %}>{{b}}</option>{% endfor %}</select>
<div class="hint">Su iPhone tieni premuto per selezionare più brand.</div>
<button>CERCA E VALUTA</button></form></div>
{% if error %}<div class="box danger">⚠️ <b>Errore:</b> {{error}}</div>{% endif %}
{% if searched and not error %}<div class="box"><div class="metric"><span class="muted">Risultati valutati</span><b>{{count}}</b></div><div class="metric"><span class="muted">Affari</span><b>{{deal_count}}</b></div><div class="metric"><span class="muted">Chiamate Scrappa</span><b>{{api_calls}}</b></div><p class="muted">{{note}}</p></div>
{% if deals %}<h2>🚨 Affari rilevati</h2>{% endif %}
{% for d in deals %}<div class="deal"><div class="score {% if d.score>=80 %}green{% elif d.score>=65 %}orange{% else %}red{% endif %}">{{d.score}}/100</div><h2>{{d.title}}</h2><p>{{d.brand}}{% if d.condition %} · {{d.condition}}{% endif %}</p>
<p><span class="tag">{{d.label}}</span><span class="tag">{{d.discount_pct}}% sotto mercato</span><span class="tag">{{d.comparable_count}} comparabili</span></p>
<p><b>Acquisto:</b> €{{"%.2f"|format(d.price)}}<br><b>Mercato osservato:</b> €{{"%.2f"|format(d.market_value)}}<br><b>Rivendita prudente:</b> €{{"%.2f"|format(d.resale_value)}}<br><b>Profitto potenziale lordo:</b> €{{"%.2f"|format(d.profit)}}</p>
{% if d.risk_flags %}<p class="muted">⚠️ {{d.risk_flags|join(' · ')}}</p>{% endif %}<a href="{{d.url}}" target="_blank">Apri annuncio →</a></div>{% endfor %}
<h2>📋 Migliori risultati</h2>{% for d in items %}<div class="item"><div class="score {% if d.score>=80 %}green{% elif d.score>=65 %}orange{% else %}red{% endif %}">{{d.score}}/100</div><h3>{{d.title}}</h3><p class="price">€{{"%.2f"|format(d.price)}}</p><p>{{d.brand}}{% if d.condition %} · {{d.condition}}{% endif %}</p><span class="tag">Mercato €{{"%.0f"|format(d.market_value)}}</span><span class="tag">{{d.discount_pct}}% sotto</span><span class="tag">Profitto €{{"%.0f"|format(d.profit)}}</span><br><a href="{{d.url}}" target="_blank">Apri annuncio →</a></div>{% endfor %}
{% if not items %}<div class="box">Nessun risultato sufficientemente documentato.</div>{% endif %}{% endif %}
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
        if str(url).startswith("http"): return str(url)
        if str(url).startswith("/"): return "https://www.vinted.it" + str(url)
        return str(url)
    item_id = x.get("id") or x.get("item_id")
    return f"https://www.vinted.it/items/{item_id}" if item_id else "https://www.vinted.it/"


def response_items(data):
    if not isinstance(data, dict): return [], {}
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    items = payload.get("items") or payload.get("results") or []
    pagination = payload.get("pagination") or {}
    return (items if isinstance(items, list) else []), pagination


def api_get(path, params):
    r = requests.get(SCRAPPA_BASE + path, params=params, headers=api_headers(), timeout=REQUEST_TIMEOUT)
    if r.status_code == 401: raise RuntimeError("Scrappa ha rifiutato la API key (401).")
    if r.status_code == 403: raise RuntimeError("Scrappa ha risposto 403: controlla crediti/account.")
    if r.status_code >= 400: raise RuntimeError(f"Scrappa HTTP {r.status_code}: {r.text[:250]}")
    return r.json()


def unwrap(data):
    if isinstance(data, dict) and isinstance(data.get("data"), dict): return data["data"]
    return data if isinstance(data, dict) else {}


def named_options(data, preferred_key=None):
    """Extract {normalized name: id} from common Scrappa filter/category shapes."""
    out = {}
    def walk(obj, parent_key=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, list) and (preferred_key is None or k.lower() == preferred_key.lower()):
                    for z in v:
                        if isinstance(z, dict):
                            ident = z.get("id") or z.get("catalog_id") or z.get("brand_id")
                            name = z.get("title") or z.get("name") or z.get("label")
                            if ident is not None and name:
                                out[re.sub(r"[^a-z0-9à-ÿ]+", " ", str(name).lower()).strip()] = str(ident)
                walk(v, k)
        elif isinstance(obj, list):
            for v in obj: walk(v, parent_key)
    walk(data)
    return out


def normalize_name(s):
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", (s or "").lower()).strip()


@lru_cache(maxsize=1)
def resolve_vinted_filters():
    """Resolve Bags category and selected brand IDs once per worker; fallback is textual search."""
    result = {"catalog_id": None, "brand_ids": {}}
    try:
        cats = unwrap(api_get("/categories", {"country": COUNTRY}))
        options = named_options(cats)
        for wanted in ("borse", "bags", "handbags"):
            if wanted in options:
                result["catalog_id"] = options[wanted]; break
        if not result["catalog_id"]:
            for name, ident in options.items():
                if "bors" in name or "handbag" in name or name == "bags":
                    result["catalog_id"] = ident; break
        params = {"country": COUNTRY}
        if result["catalog_id"]: params["catalog_ids"] = result["catalog_id"]
        filt = unwrap(api_get("/filters", params))
        # First try the explicit brands list, then any nested brand-like list.
        brands = named_options(filt, "brands")
        if not brands:
            brands = named_options(filt)
        for wanted in DEFAULT_BRANDS:
            wn = normalize_name(wanted)
            exact = brands.get(wn)
            if exact:
                result["brand_ids"][wanted] = exact
                continue
            for name, ident in brands.items():
                if wn in name or name in wn:
                    result["brand_ids"][wanted] = ident; break
    except Exception:
        # Never make the whole app unusable because filter metadata changed.
        pass
    return result


def search_items(query, max_price=None, per_page=100, brand_ids=None, catalog_id=None):
    params = {"query": query, "country": COUNTRY, "per_page": min(100, per_page), "order": "newest_first"}
    if max_price is not None: params["price_to"] = max_price
    if brand_ids: params["brand_ids"] = ",".join(map(str, brand_ids))
    if catalog_id: params["catalog_ids"] = str(catalog_id)
    return response_items(api_get("/search", params))


def item_details(item_id):
    data = unwrap(api_get("/item-details", {"item_id": str(item_id), "country": COUNTRY}))
    item = data.get("item") if isinstance(data, dict) else None
    return item if isinstance(item, dict) else (data if isinstance(data, dict) and data.get("id") else {})


def title_tokens(title):
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", (title or "").lower())
    stop = {"borsa","bag","pelle","vera","nuova","nuovo","ottime","ottima","come","da","donna","women","woman","con","the","di","in","per","del","della","originale","original"}
    return [w for w in words if len(w) >= 3 and w not in stop][:10]


def condition_score(condition):
    c = (condition or "").lower()
    if any(k in c for k in ["nuovo", "new", "mai indoss", "nuova con cartell"]): return 1.0
    if any(k in c for k in ["ottimo", "very good", "excellent"]): return .92
    if any(k in c for k in ["buono", "good"]): return .78
    if any(k in c for k in ["soddisfacente", "satisfactory"]): return .62
    return .72


def brand_key(brand):
    return normalize_name(brand)


def liquidity_for(brand):
    b = brand_key(brand)
    for name, value in BRAND_LIQUIDITY.items():
        if name in b or b in name: return value
    return .72


def extract_brand(x): return x.get("brand") or x.get("brand_title") or ""

def extract_condition(x): return x.get("condition") or x.get("status") or x.get("listing_status") or ""


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


def relevant_brand(x, brand):
    xb, target = brand_key(extract_brand(x)), brand_key(brand)
    return not target or not xb or target in xb or xb in target


def estimate_market(candidate, pool):
    p = candidate["price"]
    brand = candidate["brand"] or candidate.get("search_brand", "")
    tokens = set(title_tokens(candidate["title"]))
    exact_model = []
    brand_prices = []
    for x in pool:
        q = money(x.get("price"))
        if q <= 0 or abs(q-p) < .01 or not relevant_brand(x, brand): continue
        brand_prices.append(q)
        overlap = len(tokens & set(title_tokens(x.get("title", ""))))
        if len(tokens) >= 2 and overlap >= min(2, len(tokens)):
            exact_model.append(q)
        elif len(tokens) == 1 and overlap >= 1:
            exact_model.append(q)
    if len(exact_model) >= 5:
        vals = sorted(exact_model)
        lo, hi = int(len(vals)*.10), max(int(len(vals)*.90), int(len(vals)*.10)+1)
        vals = vals[lo:hi]
        return statistics.median(vals), len(vals), "comparabili modello/titolo"
    if len(brand_prices) >= 7:
        vals = sorted(brand_prices)
        lo, hi = int(len(vals)*.15), max(int(len(vals)*.85), int(len(vals)*.15)+1)
        vals = vals[lo:hi]
        return statistics.median(vals), len(vals), "mercato stesso brand"
    return 0, 0, "comparabili insufficienti"


def risk_flags(item):
    text = ((item.get("title") or "") + " " + (item.get("description") or "")).lower()
    flags=[]
    if not item.get("description"): flags.append("descrizione assente")
    suspicious=["replica","fake","falso","inspired","1:1","super clone","non so se originale","non autentica","non autentico"]
    if any(k in text for k in suspicious): flags.append("parole d'allerta autenticità")
    if item.get("market_value",0)>0 and item.get("price",0)>0 and item["market_value"]>item["price"]*3.0:
        flags.append("prezzo eccezionalmente basso: verificare autenticità")
    return flags


def score_deal(item, market_value, comparable_count, detail=None):
    p=item["price"]
    if not p or not market_value: return 0,0,0,"NON VALUTABILE"
    # Active asking prices are not sold prices: haircut to create a conservative resale proxy.
    resale=market_value*.92
    discount=max(0,(resale-p)/resale*100) if resale else 0
    profit=resale-p
    liq=liquidity_for(item["brand"])
    cond=condition_score((detail or {}).get("condition") or item.get("condition"))
    evidence=min(1, comparable_count/12)
    # Economics dominates; evidence and quality prevent thin/weak comps from becoming false positives.
    economics=min(52,max(0,discount*.70 + min(20,max(0,profit)/12)))
    evidence_points=18*evidence
    liquidity_points=12*liq
    condition_points=12*cond
    listing_quality=6 if (detail or {}).get("description") and ((detail or {}).get("photos") or (detail or {}).get("photo_urls")) else 3
    raw=economics+evidence_points+liquidity_points+condition_points+listing_quality
    if comparable_count<5: raw*=.72
    score=int(round(max(0,min(100,raw))))
    if score>=85 and discount>=35 and profit>=100: label="🔥 ECCELLENTE"
    elif score>=75 and discount>=25 and profit>=60: label="🟢 AFFARE"
    elif score>=65 and discount>=18 and profit>=40: label="🟡 INTERESSANTE"
    else: label="🔴 DA LASCIARE"
    return score,resale,profit,label


def enrich_candidate(item):
    try:
        d=item_details(item["id"]) if item.get("id") else {}
        if d:
            item["condition"]=d.get("condition") or item["condition"]
            item["description"]=d.get("description") or item["description"]
            item["brand"]=d.get("brand") or item["brand"]
            item["url"]=d.get("url") or d.get("source_url") or item["url"]
            item["favs"]=money(d.get("favorite_count",d.get("favourite_count",item["favs"])))
            item["views"]=money(d.get("view_count",d.get("views",item["views"])))
        return item,d
    except Exception:
        return item,None


def run_engine(query, brands, max_price, min_profit, min_discount, min_score, enrich_limit):
    meta=resolve_vinted_filters()
    api_calls=2  # categories + filters; cached after the first request per worker
    catalog_id=meta.get("catalog_id")
    resolved_ids=[meta["brand_ids"][b] for b in brands if b in meta.get("brand_ids",{})]
    all_candidates=[]; pools={}

    # One cheap search + one market search per brand: this preserves model-level comparables.
    market_cap=max(1000, max_price*4)
    for brand in brands:
        bid=meta.get("brand_ids",{}).get(brand)
        q=f"{brand} borsa" + (f" {query}" if query else "")
        cheap,_=search_items(q,max_price=max_price,per_page=100,brand_ids=[bid] if bid else None,catalog_id=catalog_id)
        market,_=search_items(q,max_price=market_cap,per_page=100,brand_ids=[bid] if bid else None,catalog_id=catalog_id)
        api_calls+=2
        pools[brand]=market
        for x in cheap:
            row=normalize_raw(x)
            if row["price"]>0 and row["price"]<=max_price:
                row["search_brand"]=brand
                # If the API omitted brand, keep the controlled search brand for scoring.
                if not row["brand"]: row["brand"]=brand
                all_candidates.append(row)

    seen=set(); candidates=[]
    for x in all_candidates:
        key=x["id"] or x["url"]
        if key in seen: continue
        seen.add(key); candidates.append(x)

    scored=[]
    for item in candidates:
        pool=pools.get(item["search_brand"],[])
        market,comp_count,evidence=estimate_market(item,pool)
        if not market: continue
        score,resale,profit,label=score_deal(item,market,comp_count)
        item.update({"market_value":market,"resale_value":resale,"profit":profit,
                     "discount_pct":round(max(0,(resale-item["price"])/resale*100),1),
                     "score":score,"label":label,"comparable_count":comp_count,"evidence":evidence,"risk_flags":[]})
        scored.append(item)
    scored.sort(key=lambda x:(x["score"],x["profit"]),reverse=True)

    for item in scored[:max(0,min(10,enrich_limit))]:
        item,detail=enrich_candidate(item); api_calls+=1
        score,resale,profit,label=score_deal(item,item["market_value"],item["comparable_count"],detail)
        item.update({"score":score,"resale_value":resale,"profit":profit,
                     "discount_pct":round(max(0,(resale-item["price"])/resale*100),1),"label":label})
        item["risk_flags"]=risk_flags(item)
    scored.sort(key=lambda x:(x["score"],x["profit"]),reverse=True)
    deals=[x for x in scored if x["score"]>=min_score and x["profit"]>=min_profit and x["discount_pct"]>=min_discount and not any("parole d'allerta" in f for f in x["risk_flags"])]
    return scored[:30],deals[:15],api_calls


@app.route("/",methods=["GET","POST"])
def home():
    error=""; searched=False; items=[]; deals=[]; count=0; api_calls=0
    query=""; max_price=300; min_profit=75; min_discount=25; min_score=70; enrich_limit=8
    selected_brands=DEFAULT_BRANDS[:]
    if request.method=="POST":
        searched=True; query=request.form.get("query","").strip(); selected_brands=request.form.getlist("brands") or DEFAULT_BRANDS[:]
        try:
            max_price=float(request.form.get("max_price",300) or 300); min_profit=float(request.form.get("min_profit",75) or 75)
            min_discount=float(request.form.get("min_discount",25) or 25); min_score=int(request.form.get("min_score",70) or 70)
            enrich_limit=int(request.form.get("enrich_limit",8) or 8)
            if max_price<=0 or min_profit<0 or not 0<=min_discount<=90 or not 0<=min_score<=100 or not 0<=enrich_limit<=10: raise ValueError
        except ValueError: error="Controlla i filtri numerici."
        if not error:
            try:
                items,deals,api_calls=run_engine(query,selected_brands,max_price,min_profit,min_discount,min_score,enrich_limit)
                count=len(items)
                note=("Il motore usa la categoria Borse e i brand filtrati da Scrappa quando i relativi ID sono disponibili; "
                      "altrimenti usa la ricerca testuale come fallback. Il valore è una stima del mercato attivo: "
                      "i prezzi richiesti non sono prezzi di vendita conclusi. Applichiamo un -8% prudenziale alla mediana. "
                      "L'autenticità non viene certificata dal bot.")
            except Exception as e: error=str(e)
    return render_template_string(HTML,error=error,searched=searched,items=items,count=count,deal_count=len(deals),deals=deals,
        api_calls=api_calls,note=note if 'note' in locals() else '',query=query,max_price=max_price,min_profit=min_profit,
        min_discount=min_discount,min_score=min_score,enrich_limit=enrich_limit,brands=DEFAULT_BRANDS,selected_brands=selected_brands)

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))
