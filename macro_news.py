import yfinance as yf
import xml.etree.ElementTree as ET
import urllib.request
import traceback

def get_yf_news(ticker_symbol="GC=F", limit=3):
    news_items = []
    try:
        ticker = yf.Ticker(ticker_symbol)
        news = ticker.news
        if news:
            for item in news[:limit]:
                content = item.get('content', {})
                title = content.get('title', 'No Title')
                provider = content.get('provider', {}).get('displayName', 'YF')
                news_items.append(f"- [{provider}] {title}")
    except Exception as e:
        print(f"Error fetching YF news: {e}")
    return news_items

def get_investing_rss(limit=3):
    news_items = []
    try:
        # Commodities RSS
        url = "https://th.investing.com/rss/news_301.rss"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            items = root.findall('./channel/item')
            for item in items[:limit]:
                title = item.find('title').text
                news_items.append(f"- [Investing.com] {title}")
    except Exception as e:
        print(f"Error fetching Investing RSS: {e}")
        # fallback to English if TH fails
        try:
            url = "https://www.investing.com/rss/news_301.rss"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                items = root.findall('./channel/item')
                for item in items[:limit]:
                    title = item.find('title').text
                    news_items.append(f"- [Investing.com] {title}")
        except Exception as e2:
            print(f"Error fetching English Investing RSS: {e2}")
            
    return news_items

def get_combined_macro_news():
    news_str = "--- ล่าสุดจากข่าว Macro & Commodities ---\n"
    yf_news = get_yf_news(limit=2)
    inv_news = get_investing_rss(limit=3)
    
    all_news = yf_news + inv_news
    if not all_news:
        news_str += "ไม่พบข่าวใหม่ในขณะนี้\n"
    else:
        for n in all_news:
            news_str += n + "\n"
    
    return news_str + "\n"

if __name__ == "__main__":
    print(get_combined_macro_news())
