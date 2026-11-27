# NSE 500 20/50 EMA Pullback + MTF Supertrend Scanner

## Run locally (free software)

1. Install Python 3.10 or newer.
2. Extract this ZIP.
3. Open Command Prompt/Terminal in the extracted folder.
4. Run:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

5. Your browser should open the scanner at `http://localhost:8501`.

## What it implements

- Nifty 500 constituents from the Nifty Indices constituent CSV.
- Daily EMA 20 / EMA 50.
- Bullish/bearish EMA crossover arms a setup.
- Setup requires a later close on the correct side of EMA 20.
- Pullback touch: daily low <= EMA20 for BUY; daily high >= EMA20 for SELL.
- Setup expiry after 30 daily candles.
- One signal per crossover.
- 15-minute Supertrend, factor 3, ATR 10.
- Confirmed daily candles only.

## Important fidelity / data limitations

This is a research implementation of the supplied Pine Script, not a certified identical TradingView engine.

The Pine script uses `request.security()` to request a lower timeframe (15m) from a daily chart. TradingView's lower-timeframe selection behavior can differ from simply selecting the last intraday bar. This app uses the last available Yahoo 15-minute bar per trading date as an explicit approximation. Verify signals against TradingView before use.

Yahoo Finance's free 15-minute history is limited (commonly around 60 days), can be delayed, can throttle requests, and may omit symbols/bars. The app shows data gaps separately. It scans the latest available signals in the retrieved history; it does not promise a live signal feed.

The Supertrend implementation uses Wilder/RMA ATR and the conventional TradingView direction convention (negative = bullish, positive = bearish). Small differences can still occur because of data vendors, session timestamps, adjustments, and lower-timeframe request semantics.

The app intentionally excludes the current daily candle until after 15:35 India time. This is a conservative confirmed-candle rule.

## Validation checklist

Before relying on results:
1. Open the same NSE ticker in TradingView.
2. Set chart to 1D.
3. Apply the original `20/50 EMA Pullback + MTF Supertrend` indicator with EMA timeframe Chart, EMA 20/50, setup expiry 30, Supertrend 15m, factor 3, ATR 10.
4. Compare several completed historical BUY and SELL signal dates.
5. Investigate every mismatch. Do not trade from this scanner until discrepancies are understood.

## Not included

- Broker integration or order placement.
- Guaranteed live quotes.
- Automated stop-loss/target (the supplied Pine script does not define these).
- Alerts that run when your computer is off.
