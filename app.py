import os
from flask import Flask, request, jsonify
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus, urlparse, urlunparse, urlencode, parse_qs

app = Flask(__name__)

SEARCH_BASE = "https://www.cardmarket.com/fr/Pokemon/Products/Search?category=-1&searchString="

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")

DEFAULT_FILTERS = {
    "sellerCountry": "12",  # France
    "language": "2",        # Français
    "minCondition": "2",    # Near Mint
}

PRICE_REGEX = re.compile(r"(?:\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?\s*€")

def make_session():
    try:
        import cloudscraper
        sess = cloudscraper.create_scraper(browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False
        })
    except Exception as e:
        print("cloudscraper failed, falling back to requests:", e)
        sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.cardmarket.com/"
    })
    return sess

def add_filters(base_url: str, filters: dict) -> str:
    parts = list(urlparse(base_url))
    query = parse_qs(parts[4])
    for k, v in filters.items():
        query[k] = [v]
    parts[4] = urlencode(query, doseq=True)
    return urlunparse(parts)

def find_product_url(card_id: str, sess: requests.Session, timeout: int = 30) -> str:
    url = SEARCH_BASE + quote_plus(card_id)
    r = sess.get(url, allow_redirects=True, timeout=timeout)
    print("[DEBUG] Request URL:", r.url)
    print("[DEBUG] Status Code:", r.status_code)

    if "/Products/Singles/" in r.url:
        return r.url

    soup = BeautifulSoup(r.text, "html.parser")
    a = soup.select_one("a[href*='/Products/Singles/']")
    if a and a.get("href"):
        return urljoin("https://www.cardmarket.com", a.get("href"))

    raise Exception(f"Aucun produit trouvé pour '{card_id}'.")

def extract_lowest_price(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(string=re.compile("€")):
        m = PRICE_REGEX.search(el)
        if m:
            return m.group(0).strip()
    return None

def extract_median_price(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    offers = soup.find("div", class_="table-body")
    if not offers:
        return None
    rows = offers.find_all("div", recursive=False)
    if not rows:
        return None
    median_index = (len(rows) + 1) // 2 - 1
    price_texts = [s.strip() for s in rows[median_index].stripped_strings if "€" in s]
    return price_texts[0] if price_texts else None

def get_prices_for_query(query: str):
    sess = make_session()
    product_url = find_product_url(query, sess=sess)
    filtered_url = add_filters(product_url, DEFAULT_FILTERS)

    html_lowest = sess.get(filtered_url, timeout=30).text
    lowest = extract_lowest_price(html_lowest)

    median_filters = {**DEFAULT_FILTERS, "sellerType": "1"}
    median_url = add_filters(product_url, median_filters)
    html_median = sess.get(median_url, timeout=30).text
    median = extract_median_price(html_median)

    return lowest, median, filtered_url

# === API FLASK ===
@app.route("/getPrices", methods=["POST"])
def get_prices():
    data = request.get_json()
    query = data.get("query")

    if not query:
        return jsonify({"error": "Champ 'query' manquant"}), 400

    try:
        lowest, median, url = get_prices_for_query(query)
        return jsonify({
            "lowest": lowest or "N/A",
            "median": median or "N/A",
            "url": url
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === LAUNCH SERVER ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)