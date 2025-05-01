import ccxt
import pandas as pd
import numpy as np
import requests
import time
from flask import Flask
import os

app = Flask(__name__)

# Telegram Config
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8013140989:AAFzAIuF_32YBcyCMAB7qkJ9NJS1c1gvSps")  # Thay bằng Token từ BotFather
CHAT_ID = os.getenv("CHAT_ID", "-1002697550210")  # Thay bằng Chat ID của nhóm
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# Trading Config
SYMBOL = "BTC/USDT"  # Cặp giao dịch
TIMEFRAME = "4h"  # 1h hoặc 4h
BB_LENGTH = 20
BB_MULT = 2.0
VOL_LENGTH = 10
VOL_THRESHOLD = 1.3
STOP_LOSS_MULT = 1.0  # 1% dưới dải dưới/thượng
RR_RATIO = 2.0  # Risk:Reward 2:1

# Khởi tạo Binance API (không cần tài khoản)
exchange = ccxt.binance({
    'enableRateLimit': True
})

def send_telegram_message(message):
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(TELEGRAM_URL, json=payload)
        if response.status_code != 200:
            print(f"Error sending Telegram message: {response.text}")
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def get_ohlcv_data(symbol, timeframe, limit=100):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def calculate_indicators(df):
    # Bollinger Bands
    df['sma'] = df['close'].rolling(window=BB_LENGTH).mean()
    df['std'] = df['close'].rolling(window=BB_LENGTH).std()
    df['upper'] = df['sma'] + (df['std'] * BB_MULT)
    df['lower'] = df['sma'] - (df['std'] * BB_MULT)
    
    # Volume
    df['vol_ma'] = df['volume'].rolling(window=VOL_LENGTH).mean()
    df['vol_spike'] = df['volume'] > (df['vol_ma'] * VOL_THRESHOLD)
    
    return df

def generate_signal(df):
    # Tín hiệu Long: Giá vượt dải dưới + Volume tăng + nến tăng
    long_condition = (df['close'] > df['lower']) & (df['close'].shift(1) <= df['lower'].shift(1)) & \
                     (df['vol_spike']) & (df['close'] > df['open'])
    
    # Tín hiệu Short: Giá cắt xuống dải trên + Volume tăng + nến giảm
    short_condition = (df['close'] < df['upper']) & (df['close'].shift(1) >= df['upper'].shift(1)) & \
                      (df['vol_spike']) & (df['close'] < df['open'])
    
    return long_condition, short_condition

def run_bot():
    print(f"Starting bot for {SYMBOL} on {TIMEFRAME} timeframe...")
    last_signal_time = 0
    
    while True:
        try:
            # Lấy dữ liệu giá
            df = get_ohlcv_data(SYMBOL, TIMEFRAME, limit=BB_LENGTH + 1)
            df = calculate_indicators(df)
            
            # Tạo tín hiệu
            long_condition, short_condition = generate_signal(df)
            
            # Lấy thông tin nến mới nhất
            latest = df.iloc[-1]
            current_time = latest['timestamp']
            
            # Tính TP/SL
            sl_long = latest['lower'] * (1 - STOP_LOSS_MULT * 0.01)
            sl_short = latest['upper'] * (1 + STOP_LOSS_MULT * 0.01)
            tp_long = latest['close'] + (latest['close'] - sl_long) * RR_RATIO
            tp_short = latest['close'] - (sl_short - latest['close']) * RR_RATIO
            
            # Kiểm tra tín hiệu
            if long_condition.iloc[-1] and (current_time.timestamp() - last_signal_time) > 3600:
                message = f"📈 Long Signal\n" \
                          f"Pair: {SYMBOL}\n" \
                          f"Entry Price: {latest['close']:.2f}\n" \
                          f"Timeframe: {TIMEFRAME}\n" \
                          f"TP: {tp_long:.2f}\n" \
                          f"SL: {sl_long:.2f}"
                send_telegram_message(message)
                last_signal_time = current_time.timestamp()
            
            if short_condition.iloc[-1] and (current_time.timestamp() - last_signal_time) > 3600:
                message = f"📉 Short Signal\n" \
                          f"Pair: {SYMBOL}\n" \
                          f"Entry Price: {latest['close']:.2f}\n" \
                          f"Timeframe: {TIMEFRAME}\n" \
                          f"TP: {tp_short:.2f}\n" \
                          f"SL: {sl_short:.2f}"
                send_telegram_message(message)
                last_signal_time = current_time.timestamp()
            
            # Nghỉ 5 phút trước khi kiểm tra lại (tránh gọi API quá nhiều)
            time.sleep(300)
            
        except Exception as e:
            print(f"Error in bot loop: {e}")
            time.sleep(60)

# Route để Render giữ service chạy
@app.route('/')
def home():
    return "Crypto Signal Bot is running!"

if __name__ == "__main__":
    # Chạy bot trong một luồng riêng để Flask vẫn hoạt động
    import threading
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    app.run(host="0.0.0.0", port=5000)
