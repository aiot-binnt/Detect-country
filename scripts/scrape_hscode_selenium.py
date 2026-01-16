"""
Japan Post HS Code Scraper using Selenium
Downloads all HS Code data from Japan Post website (JavaScript-rendered page).
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import json
import os
from datetime import datetime
import time


def setup_driver():
    """Setup Chrome WebDriver with headless mode."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def scrape_all_hscodes(driver):
    """Scrape all HS Code data from Japan Post."""
    url = "https://www.post.japanpost.jp/int/use/publication/contentslist/index.php?id=0&ie=utf8&lang=_ja"
    
    print(f"Opening: {url}")
    driver.get(url)
    
    # Wait for table to load
    print("Waiting for table to load...")
    time.sleep(5)  # Give JavaScript time to render
    
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
    except:
        print("Table not found after 20 seconds")
        return []
    
    # Scroll to load all content
    print("Scrolling to load all content...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    
    # Extract data using JavaScript
    print("Extracting data...")
    script = """
    const data = [];
    const rows = document.querySelectorAll('table tr');
    rows.forEach(row => {
        const cols = row.querySelectorAll('td');
        if (cols.length >= 4) {
            const ja = cols[0].innerText.trim();
            const cn = cols[1].innerText.trim();
            const en = cols[2].innerText.trim();
            const hscode = cols[3].innerText.trim().replace(/\\s+/g, '');
            
            if (/^\\d{6,10}$/.test(hscode)) {
                data.push({ ja, cn, en, hscode });
            }
        }
    });
    return data;
    """
    
    data = driver.execute_script(script)
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


def main():
    driver = None
    try:
        driver = setup_driver()
        data = scrape_all_hscodes(driver)
        
        if data:
            save_to_json(data, "data/japan_post_hscode.json")
            print(f"✅ Successfully scraped {len(data)} HS Codes!")
        else:
            print("❌ No data extracted")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
