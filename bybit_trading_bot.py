
```python
import ccxt
import time
import pandas as pd
import requests
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
# ---------------- CONFIGURATION ----------------
API_KEY = os.getenv("AjWCWsPiCP7L6CMVnQ", "").strip()
API_SECRET = os.getenv("oDqCyfMMiv6iVVRWKapZ5hO1Ng5kpxnD2o4Z", "").strip()
# NOTE: these must exist on Bybit as linear USDT perpetual symbols.
SYMBOLS = ["SOL/USDT:USDT", "VRA/USDT:USDT"]  # remove unknown pairs that don’t exist on Bybit
TIMEFRAME = "5m"
FAST_MA = 5
SLOW_MA = 20
MAX_LEVERAGE = 10
# Filtering thresholds (skip coins that are too illiquid on CoinGecko)
MIN_MARKET_CAP = 5_000_000
MIN_VOLUME_24H = 500_000
# Risk management
RISK_PERCENT = 0.01          # 1% of account per trade
STOP_LOSS_PERCENT = 0.02      # 2% SL
# Behavior
POLL_SECONDS = 60
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")
# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("bybit-bot")
# ---------------- EXCHANGE ----------------
exchange = ccxt.bybit({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {
        # linear perpetual swaps
        "defaultType": "swap",
    },
})
def require_keys():
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "Missing API keys. Set env vars BYBIT_API_KEY and BYBIT_API_SECRET."
        )
def load_markets_once():
    try:
        exchange.load_markets()
    except Exception as e:
        log.exception(f"Failed to load markets: {e}")
        raise
# ---------------- DATA & SIGNALS ----------------
def fetch_ohlcv(symbol: str, timeframe: str) -> Optional[pandas.DataFrame]:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe)
        if not ohlcv:
            return None
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        log.error(f"Error fetching OHLCV for {symbol}: {e}")
        return None
def calculate_ma(df: pd.DataFrame, period: int) -> pd.Series:
    return df["close"].rolling(window=period).mean()

def signal_generator(df: pd.DataFrame) -> str:
    """
    Returns: 'buy' (bullish cross), 'sell' (bearish cross), or 'hold'.
    """
    if len(df) < max(FAST_MA, SLOW_MA) + 2:
        return "hold"
  df = df.copy()
    df["fast_ma"] = calculate_ma(df, FAST_MA)
    df["slow_ma"] = calculate_ma(df, SLOW_MA)
# Need two last values to detect fresh cross
    if pd.isna(df["fast_ma"].iloc[-2]) or pd.isna(df["slow_ma"].iloc[-2]):
        return "hold"
  fast_now, slow_now = df["fast_ma"].iloc[-1], df["slow_ma"].iloc[-1]
    fast_prev, slow_prev = df["fast_ma"].iloc[-2], df["slow_ma"].iloc[-2]
  if fast_now > slow_now and fast_prev <= slow_prev:
        return "buy"
    if fast_now < slow_now and fast_prev >= slow_prev:
        return "sell"
    return "hold"
# ---------------- COINGECKO FILTER ----------------
def get_market_data_coingecko() -> List[Dict[str, Any]]:
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": 1,
            "sparkline": "false",
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"Error fetching CoinGecko data: {e}")
        return []
def _extract_symbol(base_quote: str) -> str:
    # "SOL/USDT:USDT" -> "SOL"
    return base_quote.split("/")[0].split(":")[0]
def filter_gems(symbols: List[str]) -> List[str]:
    coins = get_market_data_coingecko()
    filtered = []
    for sym in symbols:
        base = _extract_symbol(sym).lower()
        # CoinGecko uses .symbol (ticker) like "sol"
        coin_info = next((c for c in coins if c.get("symbol", "").lower() == base), None)
        if coin_info:
            mc = coin_info.get("market_cap") or 0
            vol = coin_info.get("total_volume") or 0
            if mc >= MIN_MARKET_CAP and vol >= MIN_VOLUME_24H:
                filtered.append(sym)
            else:
                log.info(f"Filtered out {sym}: market_cap={mc}, volume={vol}")
        else:
            log.warning(f"{sym} not found on CoinGecko; keeping it for now.")
            filtered.append(sym)   # keep if unknown instead of dropping the pair
    return filtered
# ---------------- EXCHANGE HELPERS ----------------
def set_leverage(symbol: str, leverage: int) -> None:
    try:
        # ccxt unified
        exchange.set_leverage(leverage, symbol)
        log.info(f"Set leverage {leverage} for {symbol}")
    except Exception as e:
        log.error(f"Failed to set leverage for {symbol}: {e}")
def get_balance_usdt() -> float:
    try:
        bal = exchange.fetch_balance()
        # Bybit returns balances under 'USDT' in many cases, sometimes lowercase
        return float(bal.get("total", {}).get("USDT", 0.0))
    except Exception as e:
        log.error(f"Error fetching balance: {e}")
        return 0.0
def get_position(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        positions = exchange.fetch_positions([symbol])
        for p in positions:
            if p.get("symbol") == symbol and abs(float(p.get("contracts", 0) or 0)) > 0:
                return p
        return None
    except Exception as e:
        log.error(f"Error fetching position for {symbol}: {e}")
        return None
def calculate_position_size(balance_usdt: float, price: float) -> float:
    if price <= 0 or balance_usdt <= 0:
        return 0.0
    risk_amount = balance_usdt * RISK_PERCENT
    contracts = risk_amount / (price * STOP_LOSS_PERCENT)
    # Bybit often requires 3 decimal places for contracts on alt swaps
    return max(round(contracts, 3), 0.0)
def place_market_order(symbol: str, side: str, amount: float) -> Optional[Dict[str, Any]]:
    side = side.lower()
    try:
        if DRY_RUN:
            log.info(f"[DRY-RUN] create_order {symbol} {side} qty={amount}")
            return {"id": "dry-run", "status": "ok"}
     order = exchange.create_order(symbol, type="market", side=side, amount=amount)
        log.info(f"Placed MARKET {side} for {amount} {symbol} -> id={order.get('id')}")
        return order
    except Exception as e:
        log.error(f"Error placing market order for {symbol}: {e}")
        return None
def place_stop_loss(symbol: str, side_entered: str, amount: float, stop_loss_price: float) -> Optional[Dict[str, Any]]:
    """
    Attempts to place a stop-market in the *opposite* direction.
    On Bybit via ccxt V5, we can pass stop/trigger params.
    """
    try:
        opposite = "sell" if side_entered.lower() == "buy" else "buy"
        params = {
            "stop": True,
            "triggerPrice": float(stop_loss_price),
            "timeInForce": "GoodTillCancel",
            # Bybit specific extras (ccxt forwards them):
            "reduceOnly": True,
            "positionIdx": 0,  # one-way mode
        }
        if DRY_RUN:
            log.info(f"[DRY-RUN] stop-loss {symbol} {opposite} qty={amount} @ {stop_loss_price}")
            return {"id": "dry-run-sl", "status": "ok"}
    order = exchange.create_order(symbol, type="market", side=opposite, amount=amount, params=params)
        log.info(f"Placed STOP-LOSS for {symbol} at {stop_loss_price} (order {order.get('id')})")
        return order
    except Exception as e:
        log.error(f"Stop-loss placement failed for {symbol}: {e}")
        return None
# ---------------- MAIN LOOP ----------------
def main():
    if not DRY_RUN:
        require_keys()
    load_markets_once()
    log.info("Starting Bybit futures bot (MA cross). DRY_RUN=%s", DRY_RUN)
    while True:
        try:
            balance = get_balance_usdt()
            tradables = filter_gems(SYMBOLS)

            for symbol in tradables:
                df = fetch_ohlcv(symbol, TIMEFRAME)
                if df is None or len(df) < SLOW_MA + 2:
                    log.debug(f"Not enough candles for {symbol}")
                    continue
      signal = signal_generator(df)
                last_price = float(df["close"].iloc[-1])
                pos = get_position(symbol)
                set_leverage(symbol, MAX_LEVERAGE)
   size = calculate_position_size(balance, last_price)
                if size <= 0:
                    log.info(f"Size=0 for {symbol} (balance={balance}, price={last_price})")
                    continue
      if signal == "buy":
                    if pos is None:
                        place_market_order(symbol, "buy", size)
                        stop = last_price * (1 - STOP_LOSS_PERCENT)
                        place_stop_loss(symbol, "buy", size, stop)
                elif signal == "sell":
                    # if long open, close it
                    if pos and float(pos.get("contracts", 0)) > 0:
                        qty = float(pos["contracts"])
                        if DRY_RUN:
                            log.info(f"[DRY-RUN] Closing long {symbol} qty={qty}")
                        else:
                            exchange.create_order(symbol, "market", "sell", qty, params={"reduceOnly": True})
                            log.info(f"Closed LONG for {symbol} qty={qty}")
                else:
                    log.debug(f"{symbol}: HOLD")

            time.sleep(POLL_SECONDS)
        except Exception as e:
            log.exception(f"Unhandled error in loop: {e}")
            time.sleep(POLL_SECONDS)
if __name__ == "__main__":
    main()
