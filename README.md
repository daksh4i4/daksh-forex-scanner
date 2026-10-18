# Daksh Free Forex Scanner V1

A free, scanner-only FX dashboard designed to deploy on Render.

## No-account design
- No broker, MT5, funded-account, data-provider API key, or Telegram account is required.
- Market data is requested from Yahoo Finance's public chart endpoint.
- Browser alerts use your browser's built-in notification permission.
- No order execution or broker connection is included.

## Strategy
- Wave: 5-minute
- Tide: 15-minute
- Trend filter: 1-hour
- EMA 9 / 20 / 50 (editable)
- RSI 14, MACD 12/26/9, Stochastic 14/3/3
- Heikin-Ashi direction confirmation
- Rolling support/resistance levels
- Weighted score: 5m 40%, 15m 35%, 1h 25%
- BUY / SELL / WAIT output, signal history, browser notifications

## Deploy on Render (free)
1. Download and extract this ZIP.
2. Create a GitHub repository in your browser and upload all extracted files, including `main.py`, `requirements.txt`, `render.yaml`, and the `static` folder.
3. Open https://render.com and sign in or create a Render account. Render hosting requires a Render account; no separate Forex/data/broker account is needed.
4. In Render choose **New +** -> **Blueprint** and connect the GitHub repository.
5. Render reads `render.yaml`. Select the free instance if asked and deploy.
6. When deployment finishes, open the `onrender.com` URL shown by Render.
7. Click **Enable browser alerts** and allow notifications if you want desktop alerts.

## Alternative manual Render setup
- New + -> Web Service -> connect repository
- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Instance type: Free

## Important limitations
- Render account is required to host the app on Render. A GitHub account is also normally required to connect a repository to Render. The scanner itself needs no third-party market-data or broker account/API key.
- Yahoo Finance's public chart endpoint is unofficial. It can be delayed, interrupted, or rate-limited. It is not an exchange-grade feed.
- Forex volume is generally not centralized; volume-based conclusions are intentionally not used.
- Render free services can sleep when inactive and cold-start on the next visit. A free host cannot guarantee uninterrupted 24/7 scanning.
- Settings and signal history are held in app memory and reset when the service restarts/redeploys.
- Prices are indicative only. Verify all signals on your trading platform before making decisions.

## Run locally
Python 3.10+:
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
Open http://127.0.0.1:8000
