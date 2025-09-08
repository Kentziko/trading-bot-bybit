python
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
MAX_LEVERAGE = 10
MIN_MARKET_CAP = 5_000_000
MIN_VOLUME_24H = 500_000
RISK_PERCENT = 0.01
STOP_LOSS_PERCENT = 0.02

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

def calculate_ma(df, period):
    return df['close'].rolling(window=period).mean()

def signal_generator(df):
    df['fast_ma'] = calculate_ma(df, FAST_MA)
df['slow_ma'] = calculate_ma(df, SLOW_MA)
    if df['fast_ma'].iloc[-1] > df['slow_ma'].iloc[-1] and df['fast_ma'].iloc[-2] <= df['slow_ma'].iloc[-2]:
        return 'buy'
    elif df['fast_ma'].iloc[-1] < df['slow_ma'].iloc[-1] and df['fast_ma'].iloc[-2] >= df['slow_ma'].iloc[-2]:
        return 'sell'
    else:
        return 'hold'

def get_market_data_coingecko():
    try:
        url = 'https://api.coingecko.com/api/v3/coins/markets'
        params = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': 250,
            'page': 1,
            'sparkline': 'false'
        }
        response = requests.get(url, params=params)
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching market data from CoinGecko: {e}")
        return []

def filter_gems(symbols):
    coins = get_market_data_coingecko()
    filtered = []
    for sym in symbols:
        coin_id = sym.split('/')[0].lower()
        coin_info = next((c for c in coins if c['symbol'] == coin_id), None)
        if coin_info:
            if coin_info['market_cap'] >= MIN_MARKET_CAP and coin_info['total_volume'] >= MIN_VOLUME_24H:
                filtered.append(sym)
            else:
logging.info(f"Filtered out {sym} due to low market cap or volume")
        else:
            logging.warning(f"{sym} not found in CoinGecko data")
    return filtered

def set_leverage(symbol, leverage):
    try:
        params = {
            'symbol': symbol.replace('/', ''),
            'leverage': leverage
        }
        exchange.private_post_positions_leverage(params)
        logging.info(f"Set leverage {leverage} for {symbol}")
    except Exception as e:
        logging.error(f"Failed to set leverage for {symbol}: {e}")

def get_balance():
    try:
        balance = exchange.fetch_balance()
        usdt = balance['total']['USDT']
        return usdt
    except Exception as e:
        logging.error(f"Error fetching balance: {e}")
        return 0

def get_position(symbol):
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if pos['symbol'] == symbol and pos['contracts'] != 0:
                return pos
        return None
    except Exception as e:
        logging.error(f"Error fetching position for {symbol}: {e}")
        return None

def place_futures_order(symbol, side, amount, price=None, stop_loss_price=None):
    try:
        params = {
            'symbol': symbol.replace('/', ''),
'side': side.upper(),
            'order_type': 'Market' if price is None else 'Limit',
            'qty': amount,
            'time_in_force': 'GoodTillCancel'
        }
        if price is not None:
            params['price'] = price

        order = exchange.private_post_contract_v3_order_create(params)
        logging.info(f"Placed {side} order for {amount} {symbol}")

        if stop_loss_price:
            sl_params = {
                'symbol': symbol.replace('/', ''),
                'side': 'Sell' if side.lower() == 'buy' else 'Buy',
                'order_type': 'StopMarket',
                'stop_px': stop_loss_price,
                'qty': amount,
                'time_in_force': 'GoodTillCancel',
                'trigger_by': 'LastPrice'
            }
            exchange.private_post_contract_v3_order_create(sl_params)
            logging.info(f"Stop-loss set at {stop_loss_price} for {symbol}")

        return order
    except Exception as e:
        logging.error(f"Error placing order for {symbol}: {e}")
        return None

def calculate_position_size(balance, price):
    risk_amount = balance * RISK_PERCENT
    size = risk_amount / (price * STOP_LOSS_PERCENT)
    return round(size, 3)

def main():
logging.info("Starting advanced Bybit futures trading bot")

    while True:
        try:
            balance = get_balance()
            gems = filter_gems(SYMBOLS)

            for symbol in gems:
                df = fetch_ohlcv(symbol, TIMEFRAME)
                if df is None or len(df) < SLOW_MA:
                    continue

                signal = signal_generator(df)
                last_price = df['close'].iloc[-1]
                position = get_position(symbol)
                size = calculate_position_size(balance, last_price)

                set_leverage(symbol, MAX_LEVERAGE)

                if signal == 'buy':
                    if position is None or position['contracts'] == 0:
                        place_futures_order(symbol, 'Buy', size)
                        stop_loss = last_price * (1 - STOP_LOSS_PERCENT)
                        place_futures_order(symbol, 'Buy', size, stop_loss_price=stop_loss)
                elif signal == 'sell':
                    if position and position['contracts'] > 0:
                        place_futures_order(symbol, 'Sell', position['contracts'])

            time.sleep(60)
        except Exception as e:
            logging.error(f"Unhandled error in main loop: {e}")
            time.sleep(60)

if _name_ == "_main_":main()


