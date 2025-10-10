import requests
from flask import flash, current_app
from app.models import Book
from app.extensions import db

def get_or_create_book(google_id, title, authors, thumbnail, language):
    # Validación mínima antes de consultar la API
    if not google_id or not title:
        flash("Faltan datos esenciales del libro.", "error")
        current_app.logger.warning(f"Datos incompletos: google_id={google_id}, title={title}")
        return None

    book = Book.query.filter_by(google_id=google_id).first()
    if book:
        return book

    try:
        response = requests.get(
            f"https://www.googleapis.com/books/v1/volumes/{google_id}", timeout=5
        )
    except requests.RequestException as e:
        flash("Error al conectar con Google Books API. Intenta más tarde.", "error")
        current_app.logger.error(f"Error de conexión con Google Books: {e}")
        return None

    if response.status_code != 200:
        flash("No se pudo obtener información del libro desde Google Books.", "error")
        current_app.logger.warning(f"Respuesta inválida para {google_id}: {response.status_code}")
        return None

    data = response.json()
    volume = data.get("volumeInfo", {})
    if not volume:
        flash("No se encontró información válida del libro.", "error")
        current_app.logger.warning(f"volumeInfo vacío para {google_id}")
        return None

    # Extracción segura de campos
    author = ", ".join(volume.get("authors", [])) if volume.get("authors") else authors
    description = volume.get("description", "")
    categories = volume.get("categories", [])
    categories_text = ", ".join(categories) if categories else ""
    image_links = volume.get("imageLinks", {})
    thumbnail_url = image_links.get("thumbnail", thumbnail)
    small_thumbnail_url = image_links.get("smallThumbnail", "")
    published_date = volume.get("publishedDate", "")
    publisher = volume.get("publisher", "")

    isbn = ""
    for identifier in volume.get("industryIdentifiers", []):
        if identifier.get("type") == "ISBN_13":
            isbn = identifier.get("identifier")
            break
    if not isbn:
        for identifier in volume.get("industryIdentifiers", []):
            if identifier.get("type") == "ISBN_10":
                isbn = identifier.get("identifier")
                break

    # Validación final antes de guardar
    if not title or not author:
        flash("No se pudo crear el libro por falta de título o autor.", "error")
        current_app.logger.warning(f"Faltan campos clave para {google_id}: title={title}, author={author}")
        return None

    book = Book(
        google_id=google_id,
        title=title,
        author=author,
        categories=categories_text,
        language=language,
        isbn=isbn,
        thumbnail=thumbnail_url,
        small_thumbnail=small_thumbnail_url,
        description=description,
        publisher=publisher,
        published_date=published_date,
    )

    db.session.add(book)
    db.session.commit()
    return book