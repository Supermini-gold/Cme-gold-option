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
            print("❌ Price data is empty")
        else:
            current_price = price_data['Close'].iloc[-1]
            print(f"✅ Current Gold Price: {current_price:.2f}")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_graph():
    print("\nTesting matplotlib graph generation...")
    try:
        data = {
            'timestamp': pd.to_datetime(['2026-05-01', '2026-05-02', '2026-05-03']),
            'z5_score': [1.2, 2.5, -1.0]
        }
        df = pd.DataFrame(data)
        
        plt.figure(figsize=(10, 6))
        plt.style.use('dark_background')
        plt.plot(df['timestamp'], df['z5_score'], marker='o')
        plt.axhspan(2, 5, color='green', alpha=0.1)
        plt.axhspan(-5, -2, color='red', alpha=0.1)
        plt.close()
        print("✅ Graph generated successfully (no errors)")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_price()
    test_graph()
