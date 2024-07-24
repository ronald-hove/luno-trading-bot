import math
import time
import pandas as pd
import numpy as np
import talib
from IPython.lib import backgroundjobs as bg
import os
import logging
from datetime import datetime
import json
import traceback
from logging.handlers import RotatingFileHandler

from luno_python.client import Client

# Fetching API credentials from environment variables
api_key_id = '<your_key_id>'
api_key_secret = '<your_key_secret>'

luno_api = Client(api_key_id=api_key_id, api_key_secret=api_key_secret)

# Set up logging
handler = RotatingFileHandler('trading_bot.log', maxBytes=2000, backupCount=10)
logging.basicConfig(handlers=[handler], level=logging.INFO, format='%(asctime)s %(message)s')

def log_and_print(message):
    print(message)
    logging.info(message)

def get_price():
    ticker = luno_api.get_ticker(pair='ETHZAR')
    if 'last_trade' not in ticker:
        raise ValueError('Invalid data from Luno API')
    price = float(ticker['last_trade'])
    log_and_print(f'Current price: {price}')
    return price

def place_order(volume):
    volume = '{:.2f}'.format(volume)
    log_and_print(f'Placing order: Buy ETH for {volume} ZAR at market price')
    try:
        luno_api.post_market_order(pair='ETHZAR', type='BID', counter_volume=volume)
        log_and_print(f'Order placed: Buy ETH for {volume} ZAR at market price')
    except Exception as e:
        log_and_print(f'An error occurred while placing order: {e}')

def sell_order(volume):
    eth_balance = get_balance()
    if eth_balance < volume:
        log_and_print(f'Insufficient funds to sell {volume} ETH. Current balance: {eth_balance} ETH')
        return

    volume_str = '{:.6f}'.format(volume)
    log_and_print(f'Placing order: Sell {volume_str} ETH at market price')
    luno_api.post_market_order(pair='ETHZAR', type='SELL', base_volume=volume_str)
    log_and_print(f'Order placed: Sell {volume_str} ETH at market price')

def get_balance():
    balance = luno_api.get_balances()
    for account in balance['balance']:
        if account['asset'] == 'ETH':
            eth_balance = float(account['balance'])
            log_and_print(f'Current ETH balance: {eth_balance}')
            return eth_balance
    raise ValueError('ETH balance not found')

def calculate_bollinger_bands(price_data, window_size=20, num_of_std=2):
    rolling_mean = price_data.rolling(window=window_size).mean()
    rolling_std = price_data.rolling(window=window_size).std()
    upper_band = rolling_mean + (rolling_std * num_of_std)
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return lower_band, upper_band

def calculate_RSI(price_data, period=14):
    return talib.RSI(price_data, timeperiod=period)

def calculate_MACD(price_data, short_period=12, long_period=26, signal_period=9):
    macd_line, signal_line, _ = talib.MACD(price_data, fastperiod=short_period, slowperiod=long_period, signalperiod=signal_period)
    return macd_line, signal_line

def calculate_moving_average(price_data, short_period=12, long_period=26):
    short_MA = talib.SMA(price_data, timeperiod=short_period)
    long_MA = talib.SMA(price_data, timeperiod=long_period)
    return short_MA, long_MA

def trading_bot(max_iterations=1000):
    iteration = 0
    initial_purchase_made = False
    insufficient_funds_logged = False

    while iteration < max_iterations:
        iteration += 1
        try:
            initial_balance = 100
            balance = initial_balance
            volume = 0
            bought_price = 0
            daily_profit_target = 1640
            daily_profit = 0
            max_trades_per_day = 10
            trades_today = 0
            trailing_stop_loss = 0.99  # 1% below the bought price
            profit_target = 1.01  # 1% above the bought price

            if os.path.exists('state.json'):
                with open('state.json', 'r') as f:
                    state = json.load(f)
                    if not state:
                        raise ValueError('state.json is empty')
                    balance = state.get('balance', initial_balance)
                    volume = state.get('volume', volume)
                    bought_price = state.get('bought_price', bought_price)
                    daily_profit = state.get('daily_profit', daily_profit)
                    trades_today = state.get('trades_today', trades_today)
                    initial_purchase_made = state.get('initial_purchase_made', initial_purchase_made)

            price = get_price()

            if os.path.exists('price_data.csv') and os.path.getsize('price_data.csv') > 0:
                price_data = pd.read_csv('price_data.csv', header=None, names=['Index', 'Price'])
                if price_data['Price'].iloc[-1] != price:  # Only append if the price is different
                    new_data = pd.DataFrame([[len(price_data), price]], columns=['Index', 'Price'])
                    price_data = pd.concat([price_data, new_data], ignore_index=True)
            else:
                price_data = pd.DataFrame([[0, price]], columns=['Index', 'Price'])

            price_data.to_csv('price_data.csv', index=False, header=False)

            eth_balance = get_balance()
            eth_value_in_zar = eth_balance * price

            if not initial_purchase_made and eth_value_in_zar < 100:
                available_balance = balance
                if available_balance < 100:
                    if not insufficient_funds_logged:
                        log_and_print(f'Insufficient funds to buy ETH. Available balance: {available_balance} ZAR')
                        insufficient_funds_logged = True
                    continue
                else:
                    volume_to_buy = 100 / price
                    if volume_to_buy >= 0.001:
                        place_order(100)
                        balance -= 100
                        initial_purchase_made = True
                        log_and_print(f'Initial purchase of {volume_to_buy} ETH at {price} ZAR made')
                    else:
                        log_and_print(f'Volume {volume_to_buy} ETH is less than the minimum order size. Initial purchase not made.')

            if len(price_data) >= 26:
                lower_band, upper_band = calculate_bollinger_bands(price_data['Price'])
                rsi = calculate_RSI(price_data['Price'])
                macd_line, signal_line = calculate_MACD(price_data['Price'])
                short_MA, long_MA = calculate_moving_average(price_data['Price'])

                if all([lower_band is not None, upper_band is not None, rsi is not None, macd_line is not None, signal_line is not None, short_MA is not None, long_MA is not None]):
                    overbought = rsi.iloc[-1] > 70
                    oversold = rsi.iloc[-1] < 30
                    macd_cross = macd_line.iloc[-1] > signal_line.iloc[-1]
                    ma_cross = short_MA.iloc[-1] > long_MA.iloc[-1]

                    buy_condition = oversold and macd_cross and ma_cross and price < lower_band.iloc[-1] and trades_today < max_trades_per_day
                    sell_condition = overbought and not macd_cross and not ma_cross and (price > bought_price * profit_target or price < bought_price * trailing_stop_loss)

                    log_and_print(f'Current volume value {volume}, Buy Condition:  {buy_condition}, Sell Condition: {sell_condition}')
                    if volume == 0 and buy_condition:
                        volume = balance / price
                        balance = 0
                        bought_price = price
                        trades_today += 1
                        place_order(balance)
                        log_and_print(f'Bought ETH at {bought_price}, total ETH: {volume}')
                    elif volume > 0 and sell_condition:
                        volume = get_balance()
                        if volume > 0:
                            balance = volume * price
                            daily_profit += balance - bought_price * volume
                            sell_order(volume)
                            log_and_print(f'Sold ETH at {price}, total ZAR: {balance}')
                            volume = 0
                        else:
                            log_and_print('Insufficient ETH balance to sell.')
                    else:
                        log_and_print(f'No trade executed. Current price: {price}, Lower band: {lower_band.iloc[-1]}, Upper band: {upper_band.iloc[-1]}, Bought price: {bought_price}, Profit target: {bought_price * profit_target}, Trailing stop loss: {bought_price * trailing_stop_loss}')

                    if daily_profit >= daily_profit_target:
                        log_and_print(f'Daily profit target of {daily_profit_target} ZAR reached. Total profit: {daily_profit} ZAR')
                        break

                    if balance < initial_balance and daily_profit > 0:
                        add_to_balance = min(daily_profit, initial_balance - balance)
                        balance += add_to_balance
                        daily_profit -= add_to_balance
                        log_and_print(f'Added {add_to_balance} ZAR from profits to balance. New balance: {balance} ZAR, Remaining profit: {daily_profit} ZAR')

                state = {'balance': balance, 'volume': volume, 'bought_price': bought_price, 'daily_profit': daily_profit, 'trades_today': trades_today, 'initial_purchase_made': initial_purchase_made}
                with open('state.json', 'w') as f:
                    json.dump(state, f)

                if datetime.now().hour == 0 and daily_profit <= 0:
                    log_and_print('No profit made for the day, resetting iteration count.')
                    iteration = 0

        except Exception as e:
            log_and_print(f'An error occurred: {e}')
            log_and_print(traceback.format_exc())
            break

        time.sleep(5)  # Increase sleep interval to reduce the rate of requests

jobs = bg.BackgroundJobManager()
jobs.new(trading_bot)