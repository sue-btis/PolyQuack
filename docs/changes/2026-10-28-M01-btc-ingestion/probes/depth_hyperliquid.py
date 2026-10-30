import json, urllib.request
def post(body):
    r = urllib.request.Request("https://api.hyperliquid.xyz/info", json.dumps(body).encode(), {"Content-Type":"application/json","User-Agent":"polyquack-audit"})
    return json.load(urllib.request.urlopen(r, timeout=20))
for sf in [None, 5, 4, 3]:
    b = {"type":"l2Book","coin":"BTC"}
    if sf: b["nSigFigs"] = sf
    d = post(b)
    bids, asks = d["levels"]
    bb, ba = float(bids[0]["px"]), float(asks[0]["px"]); mid=(bb+ba)/2
    print(f"nSigFigs={sf} time={d.get('time')} nb={len(bids)} na={len(asks)} best={bb}/{ba} "
          f"bid_span={(mid-float(bids[-1]['px']))/mid:.4%} ask_span={(float(asks[-1]['px'])-mid)/mid:.4%} keys={list(bids[0].keys())}")
m = post({"type":"metaAndAssetCtxs"})
i = [x["name"] for x in m[0]["universe"]].index("BTC")
print("ctx BTC:", m[1][i]); print("universe BTC:", m[0]["universe"][i])
