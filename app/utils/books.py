import requests
from flask import flash, current_app
from app.models import Book
from app.extensions import db

# Normalize category strings by splitting on slashes and commas
def normalize_categories(raw_categories):
    flat = set()
    for cat in raw_categories:
        if not cat:
            continue
        # Split by slashes and commas, then strip whitespace
        parts = re.split(r"[\/,]", cat)
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                flat.add(cleaned)
    return list(flat)


import html
import re
import ftfy

# Clean and normalize book descriptions from Google Books API
def clean_description(text):
    if not text:
        return ""

    # Fix broken encoding artifacts (e.g. â, ä, Å)
    text = ftfy.fix_text(text)

    # Decode HTML entities (e.g. &aacute;, &lt;)
    text = html.unescape(text)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Remove URLs
    text = re.sub(r"http\S+|www\.\S+", " ", text)

    # Normalize whitespace
    text = re.sub(r"[\n\r\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)

    return text.strip()

# Truncate strings to avoid exceeding database column limits
def truncate(value, max_length):
    return value[:max_length] if value and len(value) > max_length else value

# Retrieve a book from the database or create it using Google Books API
def get_or_create_book(google_id, title, authors, thumbnail, language, isbn=None, categories_raw=None):
    google_id = google_id.strip() if google_id else None
    if not google_id or not title:
        flash("Missing essential book data.", "error")
        current_app.logger.warning(f"[BOOK] Incomplete data: google_id={google_id}, title={title}")
        return None

    isbn = isbn if isbn and isbn.lower() != "none" else None

    # Check if book already exists by google_id
    book = Book.query.filter_by(google_id=google_id).first()
    if book:
        current_app.logger.info(f"[BOOK] Retrieved from DB: {book.title} ({book.google_id})")
        return book

    # If not found by google_id, try ISBN
    if not book and isbn:
        book = Book.query.filter_by(isbn=isbn).first()
        if book:
            current_app.logger.info(f"[BOOK] Retrieved by ISBN: {book.title} ({book.google_id})")
            return book

    # Fetch book data from Google Books API
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

    # Extract metadata from API response
    author = ", ".join(volume.get("authors", [])) if volume.get("authors") else authors
    description = clean_description(volume.get("description", ""))

    categories = volume.get("categories", [])
    categories_text = ", ".join(categories) if categories else ""

    image_links = volume.get("imageLinks", {})
    thumbnail_url = image_links.get("thumbnail") or image_links.get("smallThumbnail") or thumbnail
    small_thumbnail_url = image_links.get("smallThumbnail") or image_links.get("thumbnail") or thumbnail_url

    published_date = volume.get("publishedDate", "")
    publisher = volume.get("publisher", "")

    # Extract ISBN if not already provided
    if not isbn:
        for identifier in volume.get("industryIdentifiers", []):
            if identifier.get("type") == "ISBN_13":
                isbn = identifier.get("identifier")
                break
        if not isbn:
            for identifier in volume.get("industryIdentifiers", []):
                if identifier.get("type") == "ISBN_10":
                    isbn = identifier.get("identifier")
                    break
    isbn = isbn if isbn and isbn.lower() != "none" else None

    # Validate essential fields before creating
    if not all([google_id, title, author, language]):
        flash("Book creation failed. Missing essential data.", "error")
        current_app.logger.warning(f"[BOOK] Incomplete data: id={google_id}, title={title}, author={author}, language={language}")
        return None

    # Create new Book instance
    book = Book(
        google_id=google_id,
        title=truncate(title, 255),
        author=truncate(author, 255),
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
    if not book.author or not book.thumbnail or not book.isbn:
        flash("Book added with incomplete metadata.", "info")
        current_app.logger.warning(f"[BOOK] Incomplete metadata: {book.title} ({book.google_id}) → author={book.author}, thumbnail={book.thumbnail}, isbn={book.isbn}")

    # Attempt to save to database
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
