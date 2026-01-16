"""
Japan Post HS Code Scraper
Downloads all HS Code data from Japan Post website and saves to JSON file.
"""
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

def scrape_japan_post_hscodes():
    """Scrape all HS Code data from Japan Post website."""
    url = "https://www.post.japanpost.jp/int/use/publication/contentslist/index.php?id=0&ie=utf8&lang=_ja"
    
    print(f"Fetching data from: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    response = requests.get(url, headers=headers)
    response.encoding = 'utf-8'
    
    if response.status_code != 200:
        print(f"Error: HTTP {response.status_code}")
        return None
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find the table with HS Code data
    tables = soup.find_all('table')
    
    data = []
    
    for table in tables:
        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 4:
                ja = cols[0].get_text(strip=True)
                cn = cols[1].get_text(strip=True)  # Chinese
                en = cols[2].get_text(strip=True)
                hscode = cols[3].get_text(strip=True).replace(' ', '')
                
                # Validate HS Code (6-10 digits)
                if hscode.isdigit() and 6 <= len(hscode) <= 10:
                    data.append({
                        "ja": ja,
                        "cn": cn,
                        "en": en,
                        "hscode": hscode
                    })
    
    print(f"Extracted {len(data)} items")
    return data

def save_to_json(data, filepath):
    """Save data to JSON file."""
    result = {
        "version": datetime.now().strftime("%Y-%m-%d"),
        "source": "https://www.post.japanpost.jp/int/use/publication/contentslist/index.php",
        "total_items": len(data),
        "items": data
    }
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to: {filepath}")

if __name__ == "__main__":
    data = scrape_japan_post_hscodes()
    if data:
        save_to_json(data, "data/japan_post_hscode.json")
        print("Done!")
