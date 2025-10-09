from app.models import Book
from app.extensions import db

def get_or_create_book(google_id, title, authors, thumbnail, language):
    book = Book.query.filter_by(google_id=google_id).first()
    if not book:
        book = Book(
            google_id=google_id,
            title=title,
            author=authors,
            cover_url=thumbnail,
            language=language,
            source='google'
        )
        db.session.add(book)
    else:
        updated = False
        if not book.language and language:
            book.language = language
            updated = True
        if not book.cover_url and thumbnail:
            book.cover_url = thumbnail
            updated = True
        if not book.author and authors:
            book.author = authors
            updated = True
        if updated:
            db.session.add(book)
    db.session.commit()
    return book