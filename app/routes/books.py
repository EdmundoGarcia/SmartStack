from flask import Blueprint, request, render_template
from app.services.book_service import fetch_book_by_isbn

books_bp = Blueprint('books', __name__)

@books_bp.route('/search', methods=['GET', 'POST'])
def search_book():
    if request.method == 'POST':
        isbn = request.form.get('isbn')
        book = fetch_book_by_isbn(isbn)
        return render_template('book_result.html', book=book)
    return render_template('search_form.html')