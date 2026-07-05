import os
import sqlite3
import requests
from dotenv import load_dotenv
from datetime import datetime

# ---------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------
load_dotenv()
ISBNDB_API_KEY = os.getenv("ISBNDB_API_KEY")
KEEPA_API_KEY = os.getenv("KEEPA_API_KEY")

# ---------------------------------------------------------
# Constants (settings)
# ---------------------------------------------------------
DB_PATH = "book_master.db"
ISBN_FILE = "isbns.txt"

ISBNDB_URL = "https://api2.isbndb.com/book/"
KEEPA_URL = "https://api.keepa.com/product"

HEADERS = {"Authorization": ISBNDB_API_KEY}


# ---------------------------------------------------------
# Initialize SQLite database
# ---------------------------------------------------------
def init_db():
    """Create the price_history table if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isbn TEXT,
            title TEXT,
            lowest_price REAL,
            highest_price REAL,
            sales_rank INTEGER,
            roi REAL,
            checked_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# Read ISBNs from file
# ---------------------------------------------------------
def read_isbns():
    """Read ISBNs from isbns.txt, ignoring blank lines."""
    if not os.path.exists(ISBN_FILE):
        raise FileNotFoundError(f"ISBN file not found: {ISBN_FILE}")

    with open(ISBN_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]


# ---------------------------------------------------------
# Fetch real Amazon pricing data from Keepa
# ---------------------------------------------------------
def fetch_keepa_data(isbn):
    """
    Fetch real Amazon pricing data from Keepa.

    NOTE: Keepa normally uses ASINs. If your ISBNs are not ASINs,
    you may need a mapping step. For now, this assumes ISBN == ASIN
    for the books you're tracking.
    """
    if not KEEPA_API_KEY:
        raise RuntimeError("KEEPA_API_KEY is not set in your .env file.")

    params = {
        "key": KEEPA_API_KEY,
        "domain": 1,      # 1 = Amazon.com
        "asin": isbn,
        "buybox": 1,
        "offers": 1,
        "history": 1
    }

    resp = requests.get(KEEPA_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("products"):
        raise ValueError(f"No Keepa data found for ISBN/ASIN {isbn}")

    product = data["products"][0]

    # Keepa prices are in cents; convert to dollars
    def k(x):
        return round(x / 100, 2) if x and x > 0 else None

    stats = product.get("stats", {})
    new_price = k(stats.get("new"))
    used_price = k(stats.get("used"))
    buybox = k(product.get("buyBoxPrice"))

    sales_rank = product.get("salesRankCurrent", 0)
    if not sales_rank:
        sales_rank = stats.get("salesRank", 0)

    return {
        "buybox": buybox,
        "new_price": new_price,
        "used_price": used_price,
        "sales_rank": sales_rank or 0,
    }


# ---------------------------------------------------------
# Fetch eBay sold‑listing data
# ---------------------------------------------------------
def fetch_ebay_data(isbn):
    """
    Scrape eBay for real used book prices using the public search endpoint.
    No API key required.
    """
    url = "https://www.ebay.com/sch/i.html"
    params = {
        "_nkw": isbn,
        "_sacat": "0",
        "LH_Sold": "1",        # sold listings only
        "LH_Complete": "1"     # completed listings
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    html = resp.text

    import re

    prices = re.findall(r"\$([0-9]+\.[0-9]{2})", html)
    prices = [float(p) for p in prices]

    if not prices:
        return {
            "ebay_low": None,
            "ebay_avg": None,
            "ebay_count": 0
        }

    ebay_low = min(prices)
    ebay_avg = round(sum(prices) / len(prices), 2)

    return {
        "ebay_low": ebay_low,
        "ebay_avg": ebay_avg,
        "ebay_count": len(prices)
    }


# ---------------------------------------------------------
# Fetch book metadata + merge Keepa + eBay
# ---------------------------------------------------------
def fetch_book_data(isbn):
    """Fetch metadata (ISBNdb), Amazon prices (Keepa), and eBay comps."""
    if not ISBNDB_API_KEY:
        raise RuntimeError("ISBNDB_API_KEY is not set in your .env file.")

    # --- ISBNdb metadata ---
    url = ISBNDB_URL + isbn
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("book", {})

    title = data.get("title", "Unknown Title")
    msrp = float(data.get("msrp") or 0)

    # --- Keepa Amazon prices ---
    keepa = fetch_keepa_data(isbn)
    new_price = keepa["new_price"]
    used_price = keepa["used_price"]
    buybox = keepa["buybox"]
    sales_rank = keepa["sales_rank"]

    # --- eBay sold listings ---
    ebay = fetch_ebay_data(isbn)
    ebay_low = ebay["ebay_low"]
    ebay_avg = ebay["ebay_avg"]

    # --- Determine lowest and highest price for ROI ---
    candidates_low = [p for p in [used_price, ebay_low, new_price, buybox] if p]
    candidates_high = [p for p in [msrp, new_price, buybox, ebay_avg] if p]

    lowest_price = min(candidates_low) if candidates_low else (msrp or None)
    highest_price = max(candidates_high) if candidates_high else (msrp or None)

    roi = None
    if lowest_price and highest_price and lowest_price > 0:
        roi = (highest_price - lowest_price) / lowest_price * 100

    return {
        "isbn": isbn,
        "title": title,
        "lowest_price": lowest_price,
        "highest_price": highest_price,
        "sales_rank": sales_rank,
        "roi": roi,
        "ebay_low": ebay_low,
        "ebay_avg": ebay_avg,
        "ebay_sold_count": ebay["ebay_count"]
    }


# ---------------------------------------------------------
# Save results to SQLite
# ---------------------------------------------------------
def save_result(row):
    """Insert a row of book data into the price_history table."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO price_history (
            isbn, title, lowest_price, highest_price,
            sales_rank, roi, checked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        row["isbn"],
        row["title"],
        row["lowest_price"],
        row["highest_price"],
        row["sales_rank"],
        row["roi"],
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# Main workflow
# ---------------------------------------------------------
def main():
    print("Initializing database...")
    init_db()

    print("Reading ISBN list...")
    isbns = read_isbns()
    print(f"Found {len(isbns)} ISBNs. Processing...\n")

    for isbn in isbns:
        try:
            print(f"Fetching data for {isbn}...")
            data = fetch_book_data(isbn)
            save_result(data)
            print(
                f"Saved: {data['title']} | "
                f"Low: {data['lowest_price']} | "
                f"High: {data['highest_price']} | "
                f"ROI: {data['roi']} | "
                f"eBay Low: {data['ebay_low']} | "
                f"eBay Avg: {data['ebay_avg']} | "
                f"eBay Sold: {data['ebay_sold_count']}\n"
            )
        except Exception as e:
            print(f"Error processing {isbn}: {e}\n")


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------
if __name__ == "__main__":
    main()
