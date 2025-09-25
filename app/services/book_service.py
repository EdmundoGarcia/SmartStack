import requests
from app.extensions import db
from app.models import Book
from flask import current_app

def fetch_book_by_isbn(isbn):
    api_key = current_app.config['GOOGLE_BOOKS_API_KEY']
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&key={api_key}"
    response = requests.get(url)

    if response.status_code != 200:
        return None

    data = response.json()
    if 'items' not in data:
        return None

    volume = data['items'][0]['volumeInfo']

    # Extraer campos
    title = volume.get('title')
    authors = ', '.join(volume.get('authors', []))
    genre = ', '.join(volume.get('categories', []))
    language = volume.get('language')
    published_year = volume.get('publishedDate', '')[:4]
    description = volume.get('description')
    cover_url = volume.get('imageLinks', {}).get('thumbnail')
    isbn_13 = next((id['identifier'] for id in volume.get('industryIdentifiers', []) if id['type'] == 'ISBN_13'), None)

    # Verificar si ya existe
    existing = Book.query.filter_by(isbn=isbn_13).first()
    if existing:
        return existing

    # Crear nuevo libro
    new_book = Book(
        title=title,
        author=authors,
        genre=genre,
        language=language,
        isbn=isbn_13,
        cover_url=cover_url,
        published_year=int(published_year) if published_year.isdigit() else None,
        description=description,
        source='GoogleBooks'
    )
    db.session.add(new_book)
    db.session.commit()
    return new_book