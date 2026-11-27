import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime, time
from zoneinfo import ZoneInfo
from io import BytesIO
import time as time_module

st.set_page_config(page_title="20/50 EMA + MTF Supertrend Scanner", page_icon="📈", layout="wide")

IST = ZoneInfo("Asia/Kolkata")
CONSTITUENTS_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

st.title("NSE 500 | 20/50 EMA Pullback + MTF Supertrend")
st.caption("Research scanner based on your uploaded Pine Script v6. Confirmed daily signals only.")

with st.expander("Strategy rules reproduced from your Pine Script", expanded=False):
    st.markdown("""
    **BUY:** Daily 20 EMA crosses above daily 50 EMA → a later daily close establishes above 20 EMA → a subsequent (or same qualifying) candle's low touches/crosses 20 EMA → the 15-minute Supertrend direction is bullish.

    **SELL:** Reverse conditions: 20 EMA crosses below 50 EMA → later close below 20 EMA → candle high touches/crosses 20 EMA → 15-minute Supertrend direction is bearish.

    Defaults: EMA 20/50 on chart timeframe; setup expires at 30 daily candles; Supertrend 15 minutes, factor 3, ATR 10. One signal per EMA crossover.
    """)

st.warning(
    "Free-data limitations: Yahoo Finance intraday history is limited and can be delayed, incomplete, "
    "or unavailable for some NSE symbols. This scanner uses the latest available 15-minute bar for each "
    "daily session as the lower-timeframe confirmation. That is an approximation of TradingView's "
    "request.security() lower-timeframe selection, not a certified tick-for-tick match. Verify every signal "
    "on TradingView before trading. Missing data is shown as DATA GAP, never as WAIT."
)

@st.cache_data(ttl=3600, show_spinner=False)
def get_nifty500():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(CONSTITUENTS_URL, headers=headers, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(BytesIO(r.content))
    if "Symbol" not in df.columns:
        raise ValueError("Nifty 500 constituent CSV did not contain a Symbol column.")
    symbols = df["Symbol"].dropna().astype(str).str.strip().unique().tolist()
    return symbols, df

def _extract_ticker_frame(raw, ticker):
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        # yfinance commonly returns either (Price, Ticker) or (Ticker, Price)
        if ticker in raw.columns.get_level_values(-1):
            out = raw.xs(ticker, axis=1, level=-1, drop_level=True)
        elif ticker in raw.columns.get_level_values(0):
            out = raw.xs(ticker, axis=1, level=0, drop_level=True)
        else:
            return pd.DataFrame()
    else:
        out = raw.copy()
    out = out.copy()
    out.columns = [str(c).title() for c in out.columns]
    needed = ["Open", "High", "Low", "Close"]
    if not all(c in out.columns for c in needed):
        return pd.DataFrame()
    out = out.dropna(subset=needed)
    return out

def download_batch(symbols, interval, period):
    tickers = [s + ".NS" for s in symbols]
    try:
        raw = yf.download(
            tickers=tickers,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
            prepost=False
        )
    except Exception:
        return {}
    result = {}
    for symbol, ticker in zip(symbols, tickers):
        frame = _extract_ticker_frame(raw, ticker)
        if not frame.empty:
            result[symbol] = frame
    return result

def rma(series, length):
    # Wilder's RMA, corresponding to Pine ta.rma / ATR smoothing.
    arr = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    if len(arr) < length:
        return pd.Series(out, index=series.index)
    seed = np.nanmean(arr[:length])
    if np.isfinite(seed):
        out[length - 1] = seed
        for i in range(length, len(arr)):
            if np.isfinite(arr[i]) and np.isfinite(out[i - 1]):
                out[i] = (out[i - 1] * (length - 1) + arr[i]) / length
    return pd.Series(out, index=series.index)

def supertrend_tv(df, factor=3.0, period=10):
    """TradingView-style ta.supertrend calculation; direction < 0 is bullish."""
    h, l, c = df["High"], df["Low"], df["Close"]
    prev_close = c.shift(1)
    tr = pd.concat([(h-l), (h-prev_close).abs(), (l-prev_close).abs()], axis=1).max(axis=1)
    atr = rma(tr, period)
    hl2 = (h + l) / 2.0
    basic_upper = hl2 + factor * atr
    basic_lower = hl2 - factor * atr
    upper = np.full(len(df), np.nan)
    lower = np.full(len(df), np.nan)
    st = np.full(len(df), np.nan)
    direction = np.full(len(df), np.nan)
    for i in range(len(df)):
        if not np.isfinite(atr.iloc[i]):
            continue
        bu = basic_upper.iloc[i]
        bl = basic_lower.iloc[i]
        if i == 0 or not np.isfinite(upper[i-1]):
            upper[i] = bu
            lower[i] = bl
            direction[i] = 1.0
            st[i] = upper[i]
            continue
        pc = c.iloc[i-1]
        upper[i] = bu if (bu < upper[i-1] or pc > upper[i-1]) else upper[i-1]
        lower[i] = bl if (bl > lower[i-1] or pc < lower[i-1]) else lower[i-1]
        prev_st = st[i-1]
        if np.isfinite(prev_st) and np.isclose(prev_st, upper[i-1], equal_nan=False):
            direction[i] = -1.0 if c.iloc[i] > upper[i] else 1.0
        else:
            direction[i] = 1.0 if c.iloc[i] < lower[i] else -1.0
        st[i] = lower[i] if direction[i] < 0 else upper[i]
    return pd.DataFrame({"ST": st, "Direction": direction}, index=df.index)

def normalize_to_ist(frame):
    out = frame.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is None:
        # Yahoo intraday timestamps are generally timezone-aware; daily bars are not.
        return out
    out.index = idx.tz_convert(IST)
    return out

def daily_supertrend_direction(intraday):
    intraday = normalize_to_ist(intraday)
    st = supertrend_tv(intraday, 3.0, 10)
    temp = pd.DataFrame({"date": pd.DatetimeIndex(intraday.index).date,
                         "direction": st["Direction"].values,
                         "bar_time": pd.DatetimeIndex(intraday.index)})
    # Last available 15-minute bar per Indian trading date, matching the intended
    # end-of-session lower-timeframe confirmation as closely as Yahoo data permits.
    temp = temp.dropna(subset=["direction"]).sort_values("bar_time")
    if temp.empty:
        return {}
    return temp.groupby("date").tail(1).set_index("date")["direction"].to_dict()

def run_pine_state_machine(daily, st_by_date, expiry=30):
    d = daily.copy()
    d.columns = [str(c).title() for c in d.columns]
    d["EMA20"] = d["Close"].ewm(span=20, adjust=False, min_periods=20).mean()
    d["EMA50"] = d["Close"].ewm(span=50, adjust=False, min_periods=50).mean()
    d["BullCross"] = (d["EMA20"] > d["EMA50"]) & (d["EMA20"].shift(1) <= d["EMA50"].shift(1))
    d["BearCross"] = (d["EMA20"] < d["EMA50"]) & (d["EMA20"].shift(1) >= d["EMA50"].shift(1))

    state, setup_bar = 0, None
    established_above = False
    established_below = False
    rows = []
    dates = pd.DatetimeIndex(d.index)
    for i, (idx, row) in enumerate(d.iterrows()):
        bull_cross = bool(row["BullCross"]) if pd.notna(row["BullCross"]) else False
        bear_cross = bool(row["BearCross"]) if pd.notna(row["BearCross"]) else False

        if bull_cross:
            state, setup_bar = 1, i
            established_above = established_below = False
        if bear_cross:
            state, setup_bar = -1, i
            established_above = established_below = False

        if state == 1 and setup_bar is not None and i > setup_bar and row["Close"] > row["EMA20"]:
            established_above = True
        if state == -1 and setup_bar is not None and i > setup_bar and row["Close"] < row["EMA20"]:
            established_below = True

        age = (i - setup_bar) if state != 0 and setup_bar is not None else None
        expired = state != 0 and age is not None and age >= expiry
        if expired:
            state, setup_bar = 0, None
            if bull_cross or (age is not None and not established_below):
                established_above = False
            if bear_cross or (age is not None and not established_above):
                established_below = False

        long_tap = (state == 1 and established_above and setup_bar is not None
                    and i > setup_bar and row["Low"] <= row["EMA20"])
        short_tap = (state == -1 and established_below and setup_bar is not None
                     and i > setup_bar and row["High"] >= row["EMA20"])

        day = idx.date() if hasattr(idx, "date") else idx
        st_dir = st_by_date.get(day, np.nan)
        buy = bool(long_tap and pd.notna(st_dir) and st_dir < 0)
        sell = bool(short_tap and pd.notna(st_dir) and st_dir > 0)

        signal = "BUY" if buy else "SELL" if sell else "—"
        if buy or sell:
            state, setup_bar = 0, None
            established_above = established_below = False

        rows.append({
            "Date": pd.Timestamp(idx).date(),
            "Close": float(row["Close"]),
            "EMA20": float(row["EMA20"]) if pd.notna(row["EMA20"]) else np.nan,
            "EMA50": float(row["EMA50"]) if pd.notna(row["EMA50"]) else np.nan,
            "15m ST": "Bullish" if pd.notna(st_dir) and st_dir < 0 else "Bearish" if pd.notna(st_dir) and st_dir > 0 else "DATA GAP",
            "Signal": signal,
            "Setup": "Bullish armed" if state == 1 else "Bearish armed" if state == -1 else "None",
            "Setup age": age if age is not None else np.nan,
            "Expired": bool(expired)
        })
    return pd.DataFrame(rows)

def is_daily_bar_confirmed(date_value):
    now = datetime.now(IST)
    # Exclude today's candle until after the NSE regular session closes.
    return not (date_value == now.date() and now.time() < time(15, 35))

# Controls
c1, c2, c3 = st.columns([1.2, 1, 1])
with c1:
    st.selectbox("Universe", ["Nifty 500"], index=0, disabled=True)
with c2:
    st.selectbox("Signal mode", ["Confirmed daily signals"], index=0, disabled=True)
with c3:
    lookback = st.selectbox("Signal history", ["Last 5 sessions", "Last 10 sessions", "Last 20 sessions"], index=1)

st.markdown("### Scan")
st.write("The scanner downloads daily candles for EMA/setup history and 15-minute candles for Supertrend confirmation.")
scan_button = st.button("🔎 Scan Nifty 500", type="primary", use_container_width=True)

if scan_button:
    try:
        symbols, constituents = get_nifty500()
        st.info(f"Loaded {len(symbols)} Nifty 500 constituents. Starting data downloads in batches.")
        daily_map, intra_map = {}, {}
        progress = st.progress(0)
        status = st.empty()
        batch_size = 25
        batches = [symbols[i:i+batch_size] for i in range(0, len(symbols), batch_size)]
        for n, batch in enumerate(batches):
            status.write(f"Downloading batch {n+1}/{len(batches)} ({len(batch)} symbols)…")
            daily_map.update(download_batch(batch, "1d", "2y"))
            intra_map.update(download_batch(batch, "15m", "60d"))
            progress.progress((n+1)/len(batches))
            time_module.sleep(0.25)

        results, gaps = [], []
        latest_dates = []
        for j, symbol in enumerate(symbols):
            daily = daily_map.get(symbol)
            intra = intra_map.get(symbol)
            if daily is None or daily.empty or intra is None or intra.empty:
                gaps.append({"Symbol": symbol, "Reason": "Daily or 15-minute data unavailable"})
                continue
            # Drop unconfirmed current daily bar.
            daily = daily.copy()
            daily.index = pd.DatetimeIndex(daily.index).tz_localize(None) if getattr(daily.index, "tz", None) is not None else pd.DatetimeIndex(daily.index)
            daily = daily.sort_index()
            daily = daily[daily.index.date.astype(object) != datetime.now(IST).date()] if not is_daily_bar_confirmed(datetime.now(IST).date()) else daily
            if len(daily) < 60:
                gaps.append({"Symbol": symbol, "Reason": "Insufficient daily history"})
                continue
            st_dates = daily_supertrend_direction(intra)
            if not st_dates:
                gaps.append({"Symbol": symbol, "Reason": "15-minute Supertrend unavailable"})
                continue
            signal_history = run_pine_state_machine(daily, st_dates, expiry=30)
            session_count = {"Last 5 sessions": 5, "Last 10 sessions": 10, "Last 20 sessions": 20}[lookback]
            recent_session_dates = set(pd.DatetimeIndex(daily.index[-session_count:]).date)
            signal_history = signal_history[
                signal_history["Signal"].isin(["BUY", "SELL"])
                & signal_history["Date"].isin(recent_session_dates)
            ]
            if not signal_history.empty:
                last = signal_history.iloc[-1]
                results.append({
                    "Symbol": symbol,
                    "Signal": last["Signal"],
                    "Signal date": str(last["Date"]),
                    "Close": round(last["Close"], 2),
                    "EMA20": round(last["EMA20"], 2),
                    "EMA50": round(last["EMA50"], 2),
                    "15m Supertrend": last["15m ST"],
                    "Age (sessions)": int((pd.Timestamp(daily.index[-1]).date() - pd.Timestamp(last["Date"])).days)
                })
        status.empty()
        progress.empty()
        result_df = pd.DataFrame(results)
        if not result_df.empty:
            result_df = result_df.sort_values(["Signal date", "Symbol"], ascending=[False, True])
        st.session_state["scan_results"] = result_df
        st.session_state["scan_gaps"] = pd.DataFrame(gaps)
        st.session_state["scan_time"] = datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")
        st.success(f"Scan completed. {len(result_df)} symbols had a BUY/SELL signal in the downloaded history; {len(gaps)} symbols had data gaps.")
    except Exception as e:
        st.error(f"Scan could not complete: {e}")
        st.info("Check your internet connection and try again. Free market-data providers can temporarily throttle requests.")

if "scan_results" in st.session_state:
    st.markdown("### Latest matching signals")
    st.caption(f"Last scan: {st.session_state.get('scan_time','')}. Showing the latest BUY/SELL signal per stock within your selected completed-session window; not necessarily signals generated today.")
    df = st.session_state["scan_results"]
    if df.empty:
        st.info("No BUY/SELL signals were found in the available data. This is not proof that no signals exist: inspect the data-gap table.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Download signals CSV", df.to_csv(index=False).encode("utf-8"), "nse_ema_mtf_signals.csv", "text/csv")
    gaps = st.session_state.get("scan_gaps", pd.DataFrame())
    with st.expander(f"Data gaps ({len(gaps)})"):
        if not gaps.empty:
            st.dataframe(gaps, use_container_width=True, hide_index=True)
            st.download_button("Download data gaps CSV", gaps.to_csv(index=False).encode("utf-8"), "nse_ema_mtf_data_gaps.csv", "text/csv")
        else:
            st.write("No data gaps reported.")

st.markdown("---")
st.header("Validation against TradingView")
st.write("Before relying on this scanner, compare its output with your original TradingView indicator on the same symbol and completed daily candle.")
v1, v2, v3 = st.columns(3)
with v1:
    validation_symbol = st.text_input("NSE symbol", value="RELIANCE").strip().upper()
with v2:
    validation_date = st.date_input("TradingView signal date")
with v3:
    expected = st.selectbox("Signal shown on TradingView", ["BUY", "SELL", "No signal"])
st.caption("After scanning, search the symbol in the results or use the downloadable CSV. Record the expected TradingView signal/date and compare manually. This first version does not claim automatic parity.")
if st.button("Record validation check"):
    checks = st.session_state.get("validation_checks", [])
    checks.append({"Symbol": validation_symbol, "Date": str(validation_date), "TradingView": expected,
                   "Recorded at": datetime.now(IST).strftime("%d %b %Y %H:%M IST")})
    st.session_state["validation_checks"] = checks
    st.success("Validation check recorded in this browser session.")
if st.session_state.get("validation_checks"):
    st.dataframe(pd.DataFrame(st.session_state["validation_checks"]), use_container_width=True, hide_index=True)

st.markdown("---")
st.caption("Not investment advice. A historical signal is not a prediction of future returns. Validate entries, exits, slippage, liquidity, corporate actions and risk controls independently.")
