import re
import html
import ftfy
import requests
from flask import flash, current_app
from sqlalchemy.exc import IntegrityError
from app.models import Book
from app.extensions import db

def normalize_categories(raw_categories):
    flat = set()
    for cat in raw_categories:
        if not cat:
            continue
        parts = re.split(r"[\/,]", cat)
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                flat.add(cleaned)
    return list(flat)

def clean_description(text):
    if not text:
        return ""
    text = ftfy.fix_text(text)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"http\S+|www\.\S+", " ", text)
    text = re.sub(r"[\n\r\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

def truncate(value, max_length):
    return value[:max_length] if value and len(value) > max_length else value

def get_or_create_book(google_id, title, authors, thumbnail, language, isbn=None, categories_raw=None):
    def force_https(url):
        if url and url.startswith("http://"):
            return url.replace("http://", "https://")
        return url

    google_id = google_id.strip() if google_id else None
    if not google_id or not title:
        flash("Missing essential book data.", "error")
        current_app.logger.warning(f"[BOOK] Incomplete data: google_id={google_id}, title={title}")
        return None

    isbn = isbn if isbn and isbn.lower() != "none" else None

    # Check if book already exists by Google ID
    book = Book.query.filter_by(google_id=google_id).first()
    if book:
        current_app.logger.info(f"[BOOK] Retrieved from DB: {book.title} ({book.google_id})")
        return book

    # Fallback: check by ISBN
    if not book and isbn:
        book = Book.query.filter_by(isbn=isbn).first()
        if book:
            current_app.logger.info(f"[BOOK] Retrieved by ISBN: {book.title} ({book.google_id})")
            return book

    # Fetch from Google Books API
    try:
        response = requests.get(
            f"https://www.googleapis.com/books/v1/volumes/{google_id}",
            params={"key": current_app.config["GOOGLE_BOOKS_API_KEY"]},
            timeout=5
        )
    except requests.RequestException as e:
        flash("Failed to connect to Google Books API. Try again later.", "error")
        current_app.logger.error(f"[BOOK] Connection error: {e}")
        return None

    if response.status_code != 200:
        flash("Could not retrieve book information from Google Books.", "error")
        current_app.logger.warning(f"[BOOK] Invalid response for {google_id}: {response.status_code}")
        return None

    data = response.json()
    volume = data.get("volumeInfo", {})
    if not volume:
        flash("No valid book information found.", "error")
        current_app.logger.warning(f"[BOOK] Empty volumeInfo for {google_id}")
        return None

    # Extract metadata
    api_authors = volume.get("authors", [])
    final_authors = api_authors if api_authors else authors or []
    authors_string = ", ".join(final_authors)

    description = clean_description(volume.get("description", ""))
    categories = volume.get("categories", [])
    categories_text = ", ".join(categories) if categories else ""

    image_links = volume.get("imageLinks", {})
    thumbnail_url = force_https(image_links.get("thumbnail") or image_links.get("smallThumbnail") or thumbnail)
    small_thumbnail_url = force_https(image_links.get("smallThumbnail") or image_links.get("thumbnail") or thumbnail_url)

    published_date = volume.get("publishedDate", "")
    publisher = volume.get("publisher", "")

    # Prefer ISBN-13, fallback to ISBN-10
    isbn_13 = None
    isbn_10 = None
    for identifier in volume.get("industryIdentifiers", []):
        if identifier.get("type") == "ISBN_13":
            isbn_13 = identifier.get("identifier")
        elif identifier.get("type") == "ISBN_10":
            isbn_10 = identifier.get("identifier")
    isbn = isbn_13 or isbn_10 or isbn
    isbn = isbn if isbn and isbn.lower() != "none" else None

    # Final validation
    if not all([google_id, title, authors_string, language]):
        flash("Book creation failed. Missing essential data.", "error")
        current_app.logger.warning(f"[BOOK] Incomplete data: id={google_id}, title={title}, authors={authors_string}, language={language}")
        return None

    # Create book object
    book = Book(
        google_id=google_id,
        title=truncate(title, 255),
        authors=truncate(authors_string, 255),
        categories=truncate(categories_text, 1000),
        language=truncate(language, 20),
        isbn=truncate(isbn, 20),
        thumbnail=truncate(thumbnail_url, 500),
        small_thumbnail=truncate(small_thumbnail_url, 500),
        description=description,
        publisher=truncate(publisher, 255),
        published_date=truncate(published_date, 20),
    )

    # Warn if metadata is incomplete
    if not book.authors or not book.thumbnail or not book.isbn:
        flash("El libro se agregó con datos incompletos", "info")
        current_app.logger.warning(f"[BOOK] Incomplete metadata: {book.title} ({book.google_id}) → authors={book.authors}, thumbnail={book.thumbnail}, isbn={book.isbn}")

    # Save to database
    try:
        db.session.add(book)
        db.session.commit()
        current_app.logger.info(f"[BOOK] Book created: {book.title} ({book.google_id})")
    except IntegrityError:
        db.session.rollback()
        flash("Book already exists. Loaded from database.", "info")
        current_app.logger.warning(f"[BOOK] Duplicate detected during insert: {google_id}")
        book = Book.query.filter_by(google_id=google_id).first()

    return book
