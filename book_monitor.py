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

# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------
DB_PATH = "book_master.db"
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
# Fetch trending books from ISBNdb
# ---------------------------------------------------------
def fetch_trending_books():
    """
    Fetch trending books from ISBNdb.
    Correct endpoint: /books/trending
    """
    url = "https://api2.isbndb.com/books/trending"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("books", [])


# ---------------------------------------------------------
# Save trending book (basic metadata only)
# ---------------------------------------------------------
def save_trending_book(book):
    """
    Insert trending book metadata into the price_history table.
    Trending endpoint does not include pricing, so those fields are NULL.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO price_history (
            isbn, title, lowest_price, highest_price,
            sales_rank, roi, checked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        book.get("isbn13"),
        book.get("title"),
        None,   # lowest_price not available
        None,   # highest_price not available
        None,   # sales_rank not available
        None,   # roi not available
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

    print("Fetching trending books from ISBNdb...")
    trending_books = fetch_trending_books()
    print(f"Found {len(trending_books)} trending books.\n")

    for book in trending_books:
        try:
            print(f"Saving trending book: {book.get('title')}")
            save_trending_book(book)
        except Exception as e:
            print(f"Error saving trending book: {e}")


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------
if __name__ == "__main__":
    main()
