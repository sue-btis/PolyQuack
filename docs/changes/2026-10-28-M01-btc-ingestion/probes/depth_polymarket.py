import json, urllib.request
B="https://api.perpetuals.polymarket.com"
def get(p):
    r = urllib.request.Request(B+p, headers={"User-Agent":"polyquack-audit"})
    return json.load(urllib.request.urlopen(r, timeout=20))
ins = get("/v1/info/instruments")
ins = ins.get("data", ins) if isinstance(ins, dict) else ins
btc = [i for i in ins if i.get("base_asset")=="BTC" or str(i.get("symbol","")).startswith("BTC")]
print("BTC instruments:", [{k:i.get(k) for k in ("instrument_id","symbol","base_asset","quote_asset","funding_interval","price_decimals","close_only")} for i in btc])
iid = btc[0]["instrument_id"]
for depth in (10, 100):
    d = get(f"/v1/info/book?instrument_id={iid}&depth={depth}")
    d = d.get("data", d)
    bids, asks = d["bids"], d["asks"]
    bb, ba = float(bids[0][0]), float(asks[0][0]); mid=(bb+ba)/2
    def span(lv, i): return abs(float(lv[i][0])-mid)/mid
    print(f"depth={depth} nb={len(bids)} na={len(asks)} best={bb}/{ba} span20={span(bids,min(19,len(bids)-1)):.4%}/{span(asks,min(19,len(asks)-1)):.4%} span50={span(bids,min(49,len(bids)-1)):.4%}/{span(asks,min(49,len(asks)-1)):.4%} spanAll={span(bids,-1):.4%}/{span(asks,-1):.4%} ts={d.get('timestamp')} seq={d.get('sequence')}")
