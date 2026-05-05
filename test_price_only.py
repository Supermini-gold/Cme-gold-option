import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import io

def test_price():
    print("Testing yfinance price fetching...")
    try:
        gold = yf.Ticker("GC=F")
        price_data = gold.history(period="1d")
        if price_data.empty:
            print("Price data is empty")
        else:
            current_price = price_data['Close'].iloc[-1]
            print(f"Current Gold Price: {current_price:.2f}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_price()
