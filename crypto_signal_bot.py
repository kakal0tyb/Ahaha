import ccxt
import pandas as pd
import numpy as np
import requests
import time
from flask import Flask
import os
import logging

app = Flask(__name__)

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Telegram Config
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "YOUR_CHAT_ID")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# CoinMarketCap API Config
CMC_API_KEY = os.getenv("CMC_API_KEY", "YOUR_CMC_API_KEY")
CMC_API_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

# Trading Config
TIMEFRAMES = ["1h", "4h"]
BB_LENGTH = 20
BB_MULT = 2.0
VOL_LENGTH = 10
VOL_THRESHOLD = 1.1
STOP_LOSS_MULT = 1.0
RR_RATIO = 2.0

# Khởi tạo Binance API
exchange = ccxt.binance({'enableRateLimit': True})

def send_telegram_message(message):
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(TELEGRAM_URL, json=payload)
        if response.status_code != 200:
            logger.error(f"Error sending Telegram message: {response.text}")
        else:
            logger.info(f"Sent message: {message}")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")

def get_top_10_coins():
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accept": "application/json"
    }
    params = {
        "start": "1",
        "limit": "50",
        "convert": "USDT"
    }
    try:
        response = requests.get(CMC_API_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        # Loại bỏ USDT và USDC ngay từ đầu
        filtered_coins = [coin for coin in data['data'] if coin['symbol'] not in ['USDT', 'USDC']]
        symbols = [f"{coin['symbol']}/USDT" for coin in filtered_coins]
        return symbols[:10]  # Lấy top 10 sau khi lọc
    except Exception as e:
        logger.error(f"Error fetching top 10 coins: {e}")
        return ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", 
                "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "DOT/USDT", "LINK/USDT"]

def get_ohlcv_data(symbol, timeframe, limit=100):
    # Kiểm tra trước khi gọi API
    if symbol in ["USDT/USDT", "USDC/USDT"]:
        logger.error(f"Invalid symbol {symbol}, skipping...")
        return None

    for attempt in range(3):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Error fetching data for {symbol} (attempt {attempt + 1}/3): {e}")
            time.sleep(5)
    logger.error(f"Failed to fetch data for {symbol} after 3 attempts")
    return None

def calculate_indicators(df):
    df['sma'] = df['close'].rolling(window=BB_LENGTH).mean()
    df['std'] = df['close'].rolling(window=BB_LENGTH).std()
    df['upper'] = df['sma'] + (df['std'] * BB_MULT)
    df['lower'] = df['sma'] - (df['std'] * BB_MULT)
    df['vol_ma'] = df['volume'].rolling(window=VOL_LENGTH).mean()
    df['vol_spike'] = df['volume'] > (df['vol_ma'] * VOL_THRESHOLD)
    return df

def generate_signal(df):
    long_condition = (df['close'] > df['lower']) & (df['close'].shift(1) <= df['lower'].shift(1)) & \
                     (df['vol_spike']) & (df['close'] > df['open'])
    short_condition = (df['close'] < df['upper']) & (df['close'].shift(1) >= df['upper'].shift(1)) & \
                      (df['vol_spike']) & (df['close'] < df['open'])
    return long_condition, short_condition

def run_bot():
    logger.info(f"Starting bot to monitor top 10 coins on {TIMEFRAMES} timeframes...")
    last_signal_times = {symbol: {tf: 0 for tf in TIMEFRAMES} for symbol in get_top_10_coins()}

    while True:
        try:
            symbols = get_top_10_coins()
            logger.info(f"Monitoring coins: {symbols}")

            for symbol in symbols:
                for timeframe in TIMEFRAMES:
                    df = get_ohlcv_data(symbol, timeframe, limit=BB_LENGTH + 1)
                    if df is None:
                        continue

                    df = calculate_indicators(df)
                    long_condition, short_condition = generate_signal(df)

                    latest = df.iloc[-1]
                    current_time = latest['timestamp']

                    sl_long = latest['lower'] * (1 - STOP_LOSS_MULT * 0.01)
                    sl_short = latest['upper'] * (1 + STOP_LOSS_MULT * 0.01)
                    tp_long = latest['close'] + (latest['close'] - sl_long) * RR_RATIO
                    tp_short = latest['close'] - (sl_short - latest['close']) * RR_RATIO

                    if long_condition.iloc[-1] and (current_time.timestamp() - last_signal_times[symbol][timeframe]) > 3600:
                        message = f"📈 Long Signal\n" \
                                  f"Pair: {symbol}\n" \
                                  f"Entry Price: {latest['close']:.2f}\n" \
                                  f"Timeframe: {timeframe}\n" \
                                  f"Time: {current_time}\n" \
                                  f"TP: {tp_long:.2f}\n" \
                                  f"SL: {sl_long:.2f}"
                        send_telegram_message(message)
                        last_signal_times[symbol][timeframe] = current_time.timestamp()

                    if short_condition.iloc[-1] and (current_time.timestamp() - last_signal_times[symbol][timeframe]) > 3600:
                        message = f"📉 Short Signal\n" \
                                  f"Pair: {symbol}\n" \
                                  f"Entry Price: {latest['close']:.2f}\n" \
                                  f"Timeframe: {timeframe}\n" \
                                  f"Time: {current_time}\n" \
                                  f"TP: {tp_short:.2f}\n" \
                                  f"SL: {sl_short:.2f}"
                        send_telegram_message(message)
                        last_signal_times[symbol][timeframe] = current_time.timestamp()

            time.sleep(300)  # 5 phút

        except Exception as e:
            logger.error(f"Error in bot loop: {e}")
            time.sleep(60)

@app.route('/')
def home():
    return "Crypto Signal Bot is running!"

if __name__ == "__main__":
    import threading
    # Gửi tin nhắn khi server khởi động
    startup_message = f"🔔 Em làm việc đây sếp\nTop 10 coin trên khung {TIMEFRAMES}"
    send_telegram_message(startup_message)
    # Khởi động bot trong thread riêng
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
