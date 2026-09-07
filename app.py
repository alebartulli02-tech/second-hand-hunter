
import os, statistics
from flask import Flask, request, render_template_string
import requests
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

HTML = """
<!doctype html><html lang="it"><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Second Hand Hunter</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f7;margin:0;padding:20px}
.card{max-width:720px;margin:auto}.box,.deal{background:white;border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 2px 12px #0001}
input{width:100%;box-sizing:border-box;padding:13px;border:1px solid #ddd;border-radius:12px;margin:7px 0 14px;font-size:16px}
button{width:100%;padding:14px;border:0;border-radius:12px;font-size:17px;font-weight:700;background:#111;color:white}
.score{font-size:25px;font-weight:800}.green{color:#16803c}.red{color:#b42318}.muted{color:#666}
a{display:inline-block;margin-top:10px;text-decoration:none}
</style></head><body><div class="card">
<div class="box"><h1>🔥 Second Hand Hunter</h1>
<p class="muted">Trova potenziali affari nel second-hand.</p>
<form method="post">
<label>Prodotto / marca</label><input name="query" value="{{query}}" placeholder="es. Stone Island">
<label>Prezzo massimo (€)</label><input name="max_price" type="number" value="{{max_price}}">
<label>Margine minimo (€)</label><input name="min_margin" type="number" value="{{min_margin}}">
<button>CERCA AFFARI</button></form></div>
{% if error %}<div class="box">⚠️ {{error}}</div>{% endif %}
{% for d in deals %}<div class="deal">
<div class="score {% if d.score>=75 %}green{% else %}red{% endif %}">{{d.score}}/100</div>
<h2>{{d.title}}</h2><p>{{d.brand}} · {{d.size}}</p>
<p><b>Acquisto:</b> €{{"%.2f"|format(d.price)}}<br>
<b>Rivendita stimata:</b> €{{"%.2f"|format(d.value)}}<br>
<b>Margine:</b> €{{"%.2f"|format(d.margin)}}</p>
<a href="{{d.url}}" target="_blank">Apri annuncio →</a>
</div>{% endfor %}
</div></body></html>
"""

class Deal:
    def __init__(self, x, value, score):
        self.title=x.get("title","Senza titolo"); self.brand=x.get("brand","")
        self.size=x.get("size",""); self.price=float(x.get("price",0) or 0)
        self.value=value; self.margin=value-self.price-8; self.score=score
        self.url=x.get("url","")

def search(query, max_price):
    key=os.getenv("SCRAPPA_API_KEY")
    if not key: raise RuntimeError("Manca la chiave SCRAPPA_API_KEY.")
    r=requests.get("https://scrappa.co/api/vinted/search",
                   params={"query":query,"country":"it","per_page":50,"order":"newest_first"},
                   headers={"X-API-KEY":key,"Accept":"application/json"},timeout=30)
    r.raise_for_status()
    return [x for x in r.json().get("results",[]) if float(x.get("price",0) or 0)<=max_price]

@app.route("/", methods=["GET","POST"])
def home():
    deals=[]; error=""; query="Stone Island"; max_price=100; min_margin=30
    if request.method=="POST":
        query=request.form.get("query","").strip()
        max_price=float(request.form.get("max_price",100))
        min_margin=float(request.form.get("min_margin",30))
        try:
            items=search(query,max_price)
            prices=[float(x.get("price",0) or 0) for x in items if float(x.get("price",0) or 0)>0]
            market=statistics.median(prices) if prices else 0
            for x in items:
                p=float(x.get("price",0) or 0)
                value=market*0.92
                margin=value-p-8
                pct=margin/p*100 if p else 0
                score=max(0,min(100,round(pct*1.15+min(15,(float(x.get("favourite_count",0) or 0)**0.5)*1.5),1)))
                if margin>=min_margin and score>=75:
                    deals.append(Deal(x,value,score))
            deals.sort(key=lambda d:d.score,reverse=True)
        except Exception as e: error=str(e)
    return render_template_string(HTML,deals=deals,error=error,query=query,max_price=max_price,min_margin=min_margin)

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080)
