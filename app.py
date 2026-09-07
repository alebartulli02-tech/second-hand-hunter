import os
import statistics
from flask import Flask, request, render_template_string
import requests
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="it">
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Second Hand Hunter</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f7;margin:0;padding:20px}
.card{max-width:760px;margin:auto}.box,.deal,.item{background:white;border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 2px 12px #0001}
input{width:100%;box-sizing:border-box;padding:13px;border:1px solid #ddd;border-radius:12px;margin:7px 0 14px;font-size:16px}
button{width:100%;padding:14px;border:0;border-radius:12px;font-size:17px;font-weight:700;background:#111;color:white}
.score{font-size:25px;font-weight:800}.green{color:#16803c}.orange{color:#b25b00}.red{color:#b42318}.muted{color:#666;font-size:14px}
a{display:inline-block;margin-top:10px;text-decoration:none}
.price{font-size:20px;font-weight:800}.tag{display:inline-block;background:#eee;border-radius:8px;padding:4px 8px;margin:3px;font-size:12px}
</style>
</head>
<body><div class="card">
<div class="box"><h1>🔥 Second Hand Hunter</h1>
<p class="muted">Trova potenziali affari nel second-hand.</p>
<form method="post">
<label>Prodotto / marca</label><input name="query" value="{{query}}" placeholder="es. Stone Island">
<label>Prezzo massimo (€)</label><input name="max_price" type="number" step="0.01" value="{{max_price}}">
<label>Margine minimo (€)</label><input name="min_margin" type="number" step="0.01" value="{{min_margin}}">
<button>CERCA AFFARI</button></form></div>

{% if error %}<div class="box">⚠️ <b>Errore:</b> {{error}}</div>{% endif %}

{% if searched and not error %}
<div class="box">
<b>🔎 Annunci ricevuti da Scrappa:</b> {{count}}
{% if market %}<br><span class="muted">Mediana dei prezzi trovati: €{{"%.2f"|format(market)}}</span>{% endif %}
{% if pages %}<br><span class="muted">Pagine disponibili: {{pages}}</span>{% endif %}
</div>

{% if deals %}<h2>🔥 Potenziali affari</h2>{% endif %}
{% for d in deals %}
<div class="deal">
<div class="score {% if d.score>=75 %}green{% elif d.score>=50 %}orange{% else %}red{% endif %}">{{d.score}}/100</div>
<h2>{{d.title}}</h2>
<p>{{d.brand}}{% if d.size %} · {{d.size}}{% endif %}{% if d.status %} · {{d.status}}{% endif %}</p>
<p><b>Acquisto:</b> €{{"%.2f"|format(d.price)}}<br>
<b>Valore stimato:</b> €{{"%.2f"|format(d.value)}}<br>
<b>Margine stimato:</b> €{{"%.2f"|format(d.margin)}}</p>
<a href="{{d.url}}" target="_blank">Apri annuncio →</a>
</div>
{% endfor %}

<h2>📋 Annunci ricevuti</h2>
{% for d in items %}
<div class="item">
<h3>{{d.title}}</h3>
<p class="price">€{{"%.2f"|format(d.price)}}</p>
<p>{{d.brand}}{% if d.size %} · taglia {{d.size}}{% endif %}{% if d.status %} · {{d.status}}{% endif %}</p>
<span class="tag">Score {{d.score}}/100</span>
{% if d.margin >= min_margin %}<span class="tag">Margine ≥ filtro</span>{% endif %}
<br><a href="{{d.url}}" target="_blank">Apri annuncio →</a>
</div>
{% endfor %}

{% if not items %}<div class="box">Nessun annuncio ricevuto da Scrappa per questa ricerca.</div>{% endif %}
{% endif %}
</div></body></html>
"""


def money(value):
    if isinstance(value, dict):
        value = value.get("amount", value.get("value", 0))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def make_url(x):
    url = x.get("url") or x.get("source_url") or x.get("item_url")
    if url:
        return url
    item_id = x.get("id") or x.get("item_id")
    return f"https://www.vinted.it/items/{item_id}" if item_id else "https://www.vinted.it/"


def normalize(x, value=0, score=0):
    price = money(x.get("price", 0))
    margin = value - price - 8
    return {
        "title": x.get("title") or "Senza titolo",
        "brand": x.get("brand") or x.get("brand_title") or "",
        "size": x.get("size") or "",
        "price": price,
        "value": value,
        "margin": margin,
        "score": score,
        "status": x.get("status") or x.get("listing_status") or "",
        "url": make_url(x),
        "id": x.get("id") or x.get("item_id") or "",
    }


def search(query, max_price):
    key = os.getenv("SCRAPPA_API_KEY")
    if not key:
        raise RuntimeError("Manca la chiave SCRAPPA_API_KEY su Render.")

    response = requests.get(
        "https://scrappa.co/api/vinted/search",
        params={
            "query": query,
            "country": "IT",
            "per_page": 50,
            "order": "newest_first",
            "price_to": max_price,
        },
        headers={"X-API-KEY": key, "Accept": "application/json"},
        timeout=30,
    )

    if response.status_code == 401:
        raise RuntimeError("Scrappa ha rifiutato la API key (401 Unauthenticated).")
    if response.status_code == 403:
        raise RuntimeError("Scrappa ha risposto 403: controlla crediti/account.")
    if response.status_code >= 400:
        raise RuntimeError(f"Scrappa HTTP {response.status_code}: {response.text[:300]}")

    data = response.json()
    # Scrappa wraps search results inside data.items.
    payload = data.get("data") or {} if isinstance(data, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    items = payload.get("items") or data.get("items") or data.get("results") or []
    pagination = payload.get("pagination") or data.get("pagination") or {}
    if isinstance(pagination, list):
        pages = 0
    else:
        pages = pagination.get("total_pages", 0) or 0
    return items, pages


@app.route("/", methods=["GET", "POST"])
def home():
    deals = []
    items_view = []
    error = ""
    searched = False
    count = 0
    market = 0
    pages = 0
    query = "Stone Island"
    max_price = 100
    min_margin = 30

    if request.method == "POST":
        searched = True
        query = request.form.get("query", "").strip()
        try:
            max_price = float(request.form.get("max_price", 100) or 100)
            min_margin = float(request.form.get("min_margin", 30) or 30)
        except ValueError:
            error = "Prezzo o margine non valido."

        if not error:
            try:
                raw_items, pages = search(query, max_price)
                count = len(raw_items)
                prices = [money(x.get("price", 0)) for x in raw_items if money(x.get("price", 0)) > 0]
                market = statistics.median(prices) if prices else 0

                scored = []
                for x in raw_items:
                    p = money(x.get("price", 0))
                    if not p:
                        continue
                    value = market * 0.92 if market else 0
                    margin = value - p - 8
                    pct = (margin / p * 100) if p else 0
                    favs = money(x.get("favourite_count", x.get("favorite_count", 0)))
                    score = max(0, min(100, round(pct * 1.15 + min(15, (favs ** 0.5) * 1.5), 1)))
                    row = normalize(x, value, score)
                    scored.append(row)
                    if margin >= min_margin and score >= 75:
                        deals.append(row)

                scored.sort(key=lambda d: d["score"], reverse=True)
                items_view = scored
                deals.sort(key=lambda d: d["score"], reverse=True)
            except requests.RequestException as e:
                error = f"Errore di collegamento a Scrappa: {e}"
            except Exception as e:
                error = str(e)

    return render_template_string(
        HTML,
        deals=deals,
        items=items_view,
        error=error,
        searched=searched,
        count=count,
        market=market,
        pages=pages,
        query=query,
        max_price=max_price,
        min_margin=min_margin,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
