```python
import ccxt
import time
import pandas as pd
import requests
import logging
from datetime import datetime

-------- CONFIGURATION --------
API_KEY = 'AjWCWsPiCP7L6CMVnQ'
API_SECRET = 'oDqCyfMMiv6iVVRWKapZ5hO1Ng5kpxnD2o4Z'

SYMBOLS = ['SOL/USDT', 'SAPIEN/USDT', 'ALU/USDT', 'VRA/USDT', 'WLFI/USDT']
TIMEFRAME = '5m'
FAST_MA = 5
SLOW_MA = 20

logging.basicConfig(filename='bot.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

exchange = ccxt.bybit({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'},
})

def fetch_ohlcv(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logging.error(f"Error fetching OHLCV for {symbol}: {e}")
        return None

def main():
    for symbol in SYMBOLS:
        df = fetch_ohlcv(symbol, TIMEFRAME)
        if df is not None:
            last_close = df['close'].iloc[-1]
            print(f"{symbol} last close: {last_close}")
            logging.info(f"{symbol} last close: {last_close}")
        else:
            print(f"Failed to fetch data for {symbol}")

if _name_ == "_main_":
    while True:
        main()
        time.sleep(60)
