import os, time, threading, math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, Any
import requests
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

APP_NAME = "Daksh Free Forex Scanner"
PAIRS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
    "USD/CHF": "CHF=X", "AUD/USD": "AUDUSD=X", "USD/CAD": "CAD=X",
    "NZD/USD": "NZDUSD=X", "EUR/JPY": "EURJPY=X", "GBP/JPY": "GBPJPY=X",
    "EUR/GBP": "EURGBP=X"
}
INTERVALS = {"5m": ("5m", "5d"), "15m": ("15m", "60d"), "1h": ("1h", "730d")}
DEFAULTS = {
    "ema_fast": 9, "ema_mid": 20, "ema_slow": 50,
    "rsi_period": 14, "rsi_buy": 52, "rsi_sell": 48,
    "sr_lookback": 80, "min_score": 60, "refresh_seconds": 90
}
settings = DEFAULTS.copy()
cache: Dict[str, Any] = {}
cache_lock = threading.Lock()
history = []
last_scan = None

app = FastAPI(title=APP_NAME, version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

def fetch_yahoo(symbol: str, interval: str, range_: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": interval, "range": range_, "events": "history"}
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, params=params, headers=headers, timeout=18)
    r.raise_for_status()
    payload = r.json()
    result = payload.get("chart", {}).get("result")
    if not result:
        err = payload.get("chart", {}).get("error")
        raise ValueError(str(err or "No market data returned"))
    item = result[0]
    timestamps = item.get("timestamp") or []
    quote = item.get("indicators", {}).get("quote", [{}])[0]
    df = pd.DataFrame({
        "time": pd.to_datetime(timestamps, unit="s", utc=True),
        "open": quote.get("open", []), "high": quote.get("high", []),
        "low": quote.get("low", []), "close": quote.get("close", []),
        "volume": quote.get("volume", [])
    })
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(df) < 55:
        raise ValueError("Not enough candles returned")
    return df

def enrich(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    f, m, s = settings["ema_fast"], settings["ema_mid"], settings["ema_slow"]
    d["ema9"] = d.close.ewm(span=f, adjust=False).mean()
    d["ema20"] = d.close.ewm(span=m, adjust=False).mean()
    d["ema50"] = d.close.ewm(span=s, adjust=False).mean()
    delta = d.close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/settings["rsi_period"], adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/settings["rsi_period"], adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["rsi"] = (100 - 100/(1+rs)).fillna(50)
    ema12 = d.close.ewm(span=12, adjust=False).mean()
    ema26 = d.close.ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_signal"] = d.macd.ewm(span=9, adjust=False).mean()
    lo = d.low.rolling(14).min()
    hi = d.high.rolling(14).max()
    d["stoch_k"] = (100*(d.close-lo)/(hi-lo).replace(0, np.nan)).fillna(50)
    d["stoch_d"] = d.stoch_k.rolling(3).mean().fillna(50)
    # Heikin-Ashi trend confirmation
    d["ha_close"] = (d.open+d.high+d.low+d.close)/4
    ha_open = [(d.open.iloc[0]+d.close.iloc[0])/2]
    for i in range(1, len(d)):
        ha_open.append((ha_open[-1]+d.ha_close.iloc[i-1])/2)
    d["ha_open"] = ha_open
    return d

def analyze_tf(df: pd.DataFrame) -> Dict[str, Any]:
    d = enrich(df)
    x = d.iloc[-1]
    bullish = x.ema9 > x.ema20 > x.ema50
    bearish = x.ema9 < x.ema20 < x.ema50
    score_buy = 0
    score_sell = 0
    score_buy += 25 if bullish else (8 if x.ema9 > x.ema20 else 0)
    score_sell += 25 if bearish else (8 if x.ema9 < x.ema20 else 0)
    score_buy += 20 if x.rsi >= settings["rsi_buy"] else 0
    score_sell += 20 if x.rsi <= settings["rsi_sell"] else 0
    score_buy += 15 if x.macd > x.macd_signal else 0
    score_sell += 15 if x.macd < x.macd_signal else 0
    score_buy += 10 if x.stoch_k > x.stoch_d and x.stoch_k < 85 else 0
    score_sell += 10 if x.stoch_k < x.stoch_d and x.stoch_k > 15 else 0
    score_buy += 10 if x.ha_close > x.ha_open else 0
    score_sell += 10 if x.ha_close < x.ha_open else 0
    recent = d.tail(settings["sr_lookback"])
    support = float(recent.low.min())
    resistance = float(recent.high.max())
    price = float(x.close)
    return {
        "price": price, "ema9": float(x.ema9), "ema20": float(x.ema20),
        "ema50": float(x.ema50), "rsi": float(x.rsi),
        "macd": float(x.macd), "macd_signal": float(x.macd_signal),
        "stoch_k": float(x.stoch_k), "stoch_d": float(x.stoch_d),
        "ha": "BULLISH" if x.ha_close > x.ha_open else "BEARISH",
        "trend": "BULLISH" if bullish else ("BEARISH" if bearish else "MIXED"),
        "support": support, "resistance": resistance,
        "buy_score": int(score_buy), "sell_score": int(score_sell),
        "candle_time": x.time.isoformat()
    }

def scan_pair(pair: str, symbol: str) -> Dict[str, Any]:
    tf_data, errors = {}, []
    for label, (interval, range_) in INTERVALS.items():
        try:
            df = fetch_yahoo(symbol, interval, range_)
            tf_data[label] = analyze_tf(df)
        except Exception as e:
            errors.append(f"{label}: {str(e)[:120]}")
    if len(tf_data) != 3:
        return {"pair": pair, "symbol": symbol, "signal": "DATA ERROR",
                "error": "; ".join(errors), "timeframes": tf_data}
    wave, tide, trend = tf_data["5m"], tf_data["15m"], tf_data["1h"]
    buy = (wave["buy_score"]*0.40 + tide["buy_score"]*0.35 + trend["buy_score"]*0.25)
    sell = (wave["sell_score"]*0.40 + tide["sell_score"]*0.35 + trend["sell_score"]*0.25)
    signal = "WAIT"
    confidence = max(buy, sell)
    if buy >= settings["min_score"] and buy > sell + 8 and tide["trend"] != "BEARISH" and trend["trend"] != "BEARISH":
        signal = "BUY"
    elif sell >= settings["min_score"] and sell > buy + 8 and tide["trend"] != "BULLISH" and trend["trend"] != "BULLISH":
        signal = "SELL"
    result = {
        "pair": pair, "symbol": symbol, "signal": signal,
        "confidence": round(confidence), "buy_score": round(buy),
        "sell_score": round(sell), "price": wave["price"],
        "change": None, "timeframes": tf_data,
        "updated": datetime.now(timezone.utc).isoformat()
    }
    if signal in ("BUY", "SELL"):
        result["entry"] = wave["price"]
        result["stop_loss"] = wave["support"] if signal == "BUY" else wave["resistance"]
        result["target_1R"] = (result["entry"] + abs(result["entry"]-result["stop_loss"])) if signal == "BUY" else (result["entry"] - abs(result["entry"]-result["stop_loss"]))
    return result

def run_scan(force=False):
    global last_scan, history
    with cache_lock:
        if not force and last_scan and time.time()-last_scan < settings["refresh_seconds"]:
            return cache.get("results", [])
    results = []
    # A small worker pool keeps the scan responsive without flooding the public endpoint.
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(scan_pair, pair, symbol): pair for pair, symbol in PAIRS.items()}
        for job in as_completed(jobs):
            try:
                results.append(job.result())
            except Exception as e:
                pair = jobs[job]
                results.append({"pair": pair, "symbol": PAIRS[pair], "signal": "DATA ERROR", "error": str(e)[:120], "timeframes": {}})
    results.sort(key=lambda x: list(PAIRS).index(x["pair"]))
    with cache_lock:
        cache["results"] = results
        last_scan = time.time()
        for r in results:
            if r.get("signal") in ("BUY", "SELL"):
                key = (r["pair"], r["signal"], round(r.get("price", 0), 5))
                if not any((h["pair"], h["signal"], round(h.get("price",0),5)) == key for h in history[-30:]):
                    history.append({k:r.get(k) for k in ("pair","signal","price","confidence","updated")})
        history = history[-100:]
    return results

@app.get("/", response_class=HTMLResponse)
def home():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()

@app.get("/api/health")
def health():
    return {"status":"ok","provider":"Yahoo Finance public chart endpoint","account_required":False,
            "pairs":len(PAIRS),"last_scan":datetime.fromtimestamp(last_scan,timezone.utc).isoformat() if last_scan else None}

@app.get("/api/pairs")
def pairs():
    return [{"pair":k,"symbol":v} for k,v in PAIRS.items()]

@app.get("/api/settings")
def get_settings():
    return settings

@app.post("/api/settings")
def update_settings(data: Dict[str, Any]):
    allowed = set(DEFAULTS)
    for k,v in data.items():
        if k not in allowed: continue
        if not isinstance(v, (int,float)) or isinstance(v,bool): raise HTTPException(400, f"{k} must be numeric")
        settings[k] = int(v)
    if not (2 <= settings["ema_fast"] < settings["ema_mid"] < settings["ema_slow"] <= 200):
        settings.update(DEFAULTS)
        raise HTTPException(400, "EMA periods must be in ascending order")
    settings["min_score"] = max(20,min(95,settings["min_score"]))
    settings["refresh_seconds"] = max(60,min(600,settings["refresh_seconds"]))
    settings["sr_lookback"] = max(20,min(300,settings["sr_lookback"]))
    return settings

@app.get("/api/scan")
def api_scan(force: bool = False):
    try:
        return {"results":run_scan(force), "history":history[-30:],
                "scanned_at":datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(502, str(e))

@app.get("/api/history")
def api_history():
    return history[-100:]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
