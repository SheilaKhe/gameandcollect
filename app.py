import os
from flask import Flask, request, jsonify
import re
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse, parse_qs
from bs4 import BeautifulSoup
import cloudscraper

app = Flask(__name__)

SEARCH_BASE = "https://www.cardmarket.com/fr/Pokemon/Products/Search?category=-1&searchString="
DEFAULT_FILTERS = {
    "sellerCountry": "12",  # France
    "language": "2",        # Français
    "minCondition": "2",    # Near Mint
}
PRICE_REGEX = re.compile(r"(?:\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,]\d{2})?\s*€")

def make_session():
    sess = cloudscraper.create_scraper(browser={
        "browser": "chrome",
        "platform": "windows",
        "mobile": False
    })
    sess.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
        "Accept-Language": "fr-FR,fr;q=0.9"
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
    from urllib.parse import quote_plus
    import requests
    from bs4 import BeautifulSoup

    url = SEARCH_BASE + quote_plus(card_id)
    r = sess.get(url, allow_redirects=True, timeout=timeout)

    if "/Products/Singles/" in r.url:
        return r.url

    if r.status_code == 403:
        raise SystemExit("403 Forbidden : passe --cookie '...' ou installe cloudscraper (pip install cloudscraper).")
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # Nouvelle méthode simplifiée et plus robuste
    link = soup.select_one("a[href*='/Products/Singles/']")
    if link and link.get("href"):
        return urljoin("https://www.cardmarket.com", link.get("href"))

    raise RuntimeError(f"Aucun lien produit trouvé pour '{card_id}'.")
def extract_lowest_price(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for s in soup.find_all(string=lambda t: isinstance(t, str) and "€" in t):
        m = PRICE_REGEX.search(s)
        if m:
            return m.group(0).strip()
    return None

def extract_median_price(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    offers_container = soup.find("div", class_="table-body")
    if not offers_container:
        return None
    rows = offers_container.find_all("div", recursive=False)
    if not rows:
        return None
    median_index = (len(rows) + 1) // 2 - 1
    median_row = rows[median_index]
    price_texts = [s.strip() for s in median_row.stripped_strings if "€" in s]
    return price_texts[0] if price_texts else None

def get_prices_for_query(card_query: str):
    sess = make_session()
    product_url = find_product_url(card_query, sess)
    filtered_url = add_filters(product_url, DEFAULT_FILTERS)
    lowest_html = sess.get(filtered_url).text
    lowest_price = extract_lowest_price(lowest_html)

    median_filters = {
        "sellerCountry": "12", "sellerType": "1",
        "language": "2", "minCondition": "2"
    }
    median_url = add_filters(product_url, median_filters)
    median_html = sess.get(median_url).text
    median_price = extract_median_price(median_html)

    return lowest_price or "N/A", median_price or "N/A", filtered_url

@app.route("/getPrices", methods=["POST"])
def get_prices():
    try:
        data = request.get_json()
        query = data.get("query")
        if not query:
            return jsonify({"error": "Missing 'query' field"}), 400

        lowest, median, url = get_prices_for_query(query)
        return jsonify({
            "name": query,
            "lowest": lowest,
            "median": median,
            "url": url
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "Game & Collect API is running 🚀"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)