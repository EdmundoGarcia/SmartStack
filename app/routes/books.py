from flask import Blueprint, render_template, request, redirect, url_for, flash
import requests
from flask_login import login_required, current_user
from app.models import Book, Wishlist, UserLibrary, User
from app.extensions import db
from app.utils.books import get_or_create_book
import math
import re

books_bp = Blueprint("books", __name__)


def is_spanish(text):
    return bool(
        re.search(
            r"\b(el|la|los|las|de|una|un|y|con|por|para|más|menos)\b", text.lower()
        )
    )


def is_english(text):
    return bool(
        re.search(r"\b(the|and|of|in|to|with|for|from|more|less)\b", text.lower())
    )


def matches_language(item, filters):
    lang = item.get("volumeInfo", {}).get("language", "").lower()
    title = item.get("volumeInfo", {}).get("title", "")
    authors = ", ".join(item.get("volumeInfo", {}).get("authors", []))

    if "es" in filters and (
        lang.startswith("es") or is_spanish(title) or is_spanish(authors)
    ):
        return True
    if "en" in filters and (
        lang.startswith("en") or is_english(title) or is_english(authors)
    ):
        return True
    return False


@books_bp.route("/search")
@login_required
def search_books():
    query = request.args.get("q", "").strip()
    lang_filters = request.args.getlist("lang") or ["es", "en"]
    author = request.args.get("author", "").strip()
    publisher = request.args.get("publisher", "").strip()
    order_by = request.args.get("order", "relevance")
    max_results = int(request.args.get("max", 10))
    page = int(request.args.get("page", 1))

    results = []
    total_items = 0
    total_pages = 0

    if query:
        q = query
        if author:
            q += f"+inauthor:{author}"
        if publisher:
            q += f"+inpublisher:{publisher}"

        params = {"q": q, "startIndex": 0, "maxResults": 40, "orderBy": order_by}

        response = requests.get(
            "https://www.googleapis.com/books/v1/volumes", params=params
        )
        if response.status_code == 200:
            data = response.json()
            raw_results = data.get("items", [])
            filtered = [
                item for item in raw_results if matches_language(item, lang_filters)
            ]

            total_items = len(filtered)
            total_pages = math.ceil(total_items / max_results)
            results = filtered[(page - 1) * max_results : page * max_results]

    wishlist_ids = (
        [book.google_id for book in current_user.wishlist.books]
        if current_user.wishlist
        else []
    )
    library_ids = (
        [book.google_id for book in current_user.library.books]
        if current_user.library
        else []
    )

    return render_template(
        "books/search.html",
        query=query,
        results=results,
        total_items=total_items,
        page=page,
        max_results=max_results,
        total_pages=total_pages,
        order_by=order_by,
        lang_filters=lang_filters,
        author=author,
        publisher=publisher,
        wishlist_ids=wishlist_ids,
        library_ids=library_ids,
    )


@books_bp.route("/add_to_library", methods=["POST"])
@login_required
def add_to_library():
    google_id = request.form.get("book_id")
    title = request.form.get("title")
    authors = request.form.get("authors")
    thumbnail = request.form.get("thumbnail")
    language = request.form.get("language")

    book = get_or_create_book(google_id, title, authors, thumbnail, language)

    if not current_user.library:
        library = UserLibrary(user=current_user)
        db.session.add(library)
        db.session.commit()
        current_user.library = library

    if current_user.wishlist and book in current_user.wishlist.books:
        current_user.wishlist.books.remove(book)
        flash(f'📚 "{title}" fue movido de tu wishlist a la biblioteca.', "success")

    if book not in current_user.library.books:
        current_user.library.books.append(book)
        flash(f'📚 "{title}" fue añadido a tu biblioteca.', "success")
    else:
        flash(f'⚠️ "{title}" ya está en tu biblioteca.', "info")

    db.session.commit()
    return redirect(request.referrer or url_for("books.search_books"))


@books_bp.route("/add_to_wishlist", methods=["POST"])
@login_required
def add_to_wishlist():
    google_id = request.form.get("book_id")
    title = request.form.get("title")
    authors = request.form.get("authors")
    thumbnail = request.form.get("thumbnail")
    language = request.form.get("language")

    book = get_or_create_book(google_id, title, authors, thumbnail, language)

    if current_user.library and book in current_user.library.books:
        flash(
            f'📚 "{title}" ya está en tu biblioteca. No se puede agregar a la wishlist.',
            "info",
        )
        return redirect(request.referrer or url_for("books.search_books"))

    if not current_user.wishlist:
        wishlist = Wishlist(user=current_user)
        db.session.add(wishlist)
        db.session.commit()
        current_user.wishlist = wishlist

    if book not in current_user.wishlist.books:
        current_user.wishlist.books.append(book)
        flash(f'📌 "{title}" fue añadido a tu wishlist.', "success")
    else:
        flash(f'⚠️ "{title}" ya está en tu wishlist.', "info")

    db.session.commit()
    return redirect(request.referrer or url_for("books.search_books"))


@books_bp.route("/wishlist")
@login_required
def view_wishlist():
    books = current_user.wishlist.books if current_user.wishlist else []
    return render_template("books/wishlist.html", books=books)


from sqlalchemy.orm import joinedload


@books_bp.route("/library")
@login_required
def view_library():
    user = (
        db.session.query(User)
        .options(joinedload(User.library).joinedload(UserLibrary.books))
        .filter_by(id=current_user.id)
        .first()
    )

    books = user.library.books if user and user.library else []
    return render_template("books/library.html", books=books)
