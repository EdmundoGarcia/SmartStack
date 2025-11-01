import requests
from flask import flash, current_app
from app.models import Book
from app.extensions import db

def clean_description(text):
    if not text:
        return ""
    import re
    text = re.sub(r"<[^>]+>", " ", text)  # HTML tags
    text = re.sub(r"http\S+|www\.\S+", " ", text)  # Enlaces
    # text = re.sub(r"Este libro.*?Google Books.*?\.", " ", text, flags=re.IGNORECASE)
    # text = re.sub(r"Este contenido.*?vista previa.*?\.", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\x00-\x7F]+", " ", text)  # ASCII no imprimible
    text = re.sub(r"[\n\r\t]+", " ", text)  # Saltos y tabulaciones
    text = re.sub(r"\s{2,}", " ", text)  # Espacios dobles
    return text.strip()


def truncate(value, max_length):
    return value[:max_length] if value and len(value) > max_length else value

def get_or_create_book(google_id, title, authors, thumbnail, language, isbn=None):
    if not google_id or not title:
        flash("Faltan datos esenciales del libro.", "error")
        current_app.logger.warning(f"[BOOK] Datos incompletos: google_id={google_id}, title={title}")
        return None

    isbn = isbn if isbn and isbn.lower() != "none" else None

    # Buscar por ISBN si existe, si no por google_id
    book = Book.query.filter_by(isbn=isbn).first() if isbn else Book.query.filter_by(google_id=google_id).first()
    if book:
        return book

    # Obtener datos desde Google Books API
    try:
        response = requests.get(
            f"https://www.googleapis.com/books/v1/volumes/{google_id}",
            params={"key": current_app.config["GOOGLE_BOOKS_API_KEY"]},
            timeout=5
        )
    except requests.RequestException as e:
        flash("Error al conectar con Google Books API. Intenta más tarde.", "error")
        current_app.logger.error(f"[BOOK] Error de conexión con Google Books: {e}")
        return None

    if response.status_code != 200:
        flash("No se pudo obtener información del libro desde Google Books.", "error")
        current_app.logger.warning(f"[BOOK] Respuesta inválida para {google_id}: {response.status_code}")
        return None

    data = response.json()
    volume = data.get("volumeInfo", {})
    if not volume:
        flash("No se encontró información válida del libro.", "error")
        current_app.logger.warning(f"[BOOK] volumeInfo vacío para {google_id}")
        return None

    author = ", ".join(volume.get("authors", [])) if volume.get("authors") else authors
    description = clean_description(volume.get("description", ""))
    categories = volume.get("categories", [])
    categories_text = ", ".join(categories) if categories else ""
    image_links = volume.get("imageLinks", {})

    thumbnail_url = (
        image_links.get("extraLarge")
        or image_links.get("large")
        or image_links.get("medium")
        or image_links.get("thumbnail")
        or thumbnail
    )

    small_thumbnail_url = (
        image_links.get("medium")
        or image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or ""
    )

    published_date = volume.get("publishedDate", "")
    publisher = volume.get("publisher", "")

    # Buscar ISBN si no se proporcionó
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

    # Validación final antes de crear el libro
    if not all([google_id, title, author, language]):
        flash("No se pudo crear el libro. Faltan datos esenciales.", "error")
        current_app.logger.warning(f"[BOOK] Datos incompletos: id={google_id}, title={title}, author={author}, language={language}")
        return None

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
    # Advertencia si el libro tiene metadatos incompletos
    if not book.author or not book.thumbnail or not book.isbn:
        flash("⚠️ El libro fue agregado, pero tiene metadatos incompletos.", "info")
        current_app.logger.warning(f"[BOOK] Metadatos incompletos: {book.title} ({book.google_id}) → author={book.author}, thumbnail={book.thumbnail}, isbn={book.isbn}")
    db.session.add(book)
    db.session.commit()
    current_app.logger.info(f"[BOOK] Libro creado: {book.title} ({book.google_id})")
    return book