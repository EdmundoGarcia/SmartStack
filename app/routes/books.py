from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app,
)
import requests
from flask_login import login_required, current_user
from app.models import Book, Wishlist, UserLibrary, User
from app.extensions import db
from app.utils.books import get_or_create_book
import math
import re
from sqlalchemy.orm import joinedload

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
    page = int(request.args.get("page", 1))

    RESULTS_PER_PAGE = 12
    results = []
    total_items = 0
    total_pages = 0

    # Limpiar caché si es demasiado grande
    MAX_CACHE_SIZE = 200
    if len(session.get("search_cache", {})) > MAX_CACHE_SIZE:
        session["search_cache"].clear()
        current_app.logger.info("Caché limpiado automáticamente por exceso de tamaño.")

    if not query:
        flash("Ingresa una palabra clave para buscar libros.", "warning")
        return render_template(
            "books/search.html",
            results=[],
            total_items=0,
            page=page,
            max_results=RESULTS_PER_PAGE,
            total_pages=total_pages,
            order_by=order_by,
            lang_filters=lang_filters,
            author=author,
            publisher=publisher,
            wishlist_ids=[],
            library_ids=[],
        )

    q = query
    if author:
        q += f"+inauthor:{author}"
    if publisher:
        q += f"+inpublisher:{publisher}"

    api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
    params = {"q": q, "startIndex": 0, "maxResults": 40, "orderBy": order_by, "key": api_key}

    try:
        response = requests.get("https://www.googleapis.com/books/v1/volumes", params=params, timeout=5)
    except requests.RequestException as e:
        flash(
            "Lo sentimos, ocurrió un error de conexión con Google Books API.", "error"
        )
        current_app.logger.error(f"Error de conexión: {e}")
        return render_template(
            "books/search.html",
            results=[],
            total_items=0,
            page=page,
            max_results=RESULTS_PER_PAGE,
            total_pages=total_pages,
            order_by=order_by,
            lang_filters=lang_filters,
            author=author,
            publisher=publisher,
            wishlist_ids=[],
            library_ids=[],
        )

    raw_results = []
    if response.status_code == 200:
        data = response.json()
        raw_results = data.get("items", [])
        current_app.logger.info(f"Resultados crudos recibidos: {len(raw_results)}")

        # Guardar solo los campos mínimos en sesión para evitar saturar la cookie
        for item in raw_results[:20]:
            session.setdefault("search_cache", {})[item["id"]] = {
                "title": item["volumeInfo"].get("title"),
                "authors": item["volumeInfo"].get("authors", []),
                "language": item["volumeInfo"].get("language"),
                "thumbnail": item["volumeInfo"].get("imageLinks", {}).get("thumbnail"),
                "description": item["volumeInfo"].get("description"),
                "publisher": item["volumeInfo"].get("publisher"),
                "publishedDate": item["volumeInfo"].get("publishedDate"),
                "categories": item["volumeInfo"].get("categories", []),
            }
    elif response.status_code == 429:
        flash(
            "Has realizado demasiadas búsquedas en poco tiempo. Espera unos minutos antes de intentar nuevamente.",
            "warning",
        )
        current_app.logger.warning("Google Books API rate limit alcanzado (429)")
        return render_template(
            "books/search.html",
            results=[],
            total_items=0,
            page=page,
            max_results=RESULTS_PER_PAGE,
            total_pages=total_pages,
            order_by=order_by,
            lang_filters=lang_filters,
            author=author,
            publisher=publisher,
            wishlist_ids=[],
            library_ids=[],
        )
    else:
        flash(
            "Lo sentimos, ocurrió un error de conexión con Google Books API.", "error"
        )
        current_app.logger.warning(f"Google Books API error: {response.status_code}")
        return render_template(
            "books/search.html",
            results=[],
            total_items=0,
            page=page,
            max_results=RESULTS_PER_PAGE,
            total_pages=total_pages,
            order_by=order_by,
            lang_filters=lang_filters,
            author=author,
            publisher=publisher,
            wishlist_ids=[],
            library_ids=[],
        )

    # Filtrar por idioma
    filtered = [item for item in raw_results if matches_language(item, lang_filters)]
    current_app.logger.info(f"Resultados tras filtro de idioma: {len(filtered)}")

    # Paginación local
    total_items = len(filtered)
    total_pages = max(1, math.ceil(total_items / RESULTS_PER_PAGE))
    start = (page - 1) * RESULTS_PER_PAGE
    end = start + RESULTS_PER_PAGE
    results = filtered[start:end]

    wishlist_ids = [
        book.google_id for book in getattr(current_user.wishlist, "books", [])
    ]
    library_ids = [
        book.google_id for book in getattr(current_user.library, "books", [])
    ]

    return render_template(
        "books/search.html",
        query=query,
        results=results,
        total_items=total_items,
        page=page,
        max_results=RESULTS_PER_PAGE,
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
    if not book:
        flash("No se pudo agregar el libro a la biblioteca.", "error")
        current_app.logger.warning(f"Falló get_or_create_book para {google_id}")
        return redirect(request.referrer or url_for("books.search_books"))

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


@books_bp.route("/remove_from_library", methods=["POST"])
@login_required
def remove_from_library():
    book_id = request.form.get("book_id")
    if not book_id:
        flash("No se especificó el libro a eliminar.", "error")
        return redirect(url_for("books.view_library"))

    book = Book.query.filter_by(google_id=book_id).first()
    if not book:
        flash("El libro no existe.", "error")
        return redirect(url_for("books.view_library"))

    user_library = current_user.library
    if book in user_library.books:
        user_library.books.remove(book)
        db.session.commit()
        flash(f'"{book.title}" fue eliminado de tu biblioteca.', "success")
    else:
        flash("Ese libro no está en tu biblioteca.", "warning")

    return redirect(url_for("books.view_library"))


@books_bp.route("/add_to_wishlist", methods=["POST"])
@login_required
def add_to_wishlist():
    google_id = request.form.get("book_id")
    title = request.form.get("title")
    authors = request.form.get("authors")
    thumbnail = request.form.get("thumbnail")
    language = request.form.get("language")

    book = get_or_create_book(google_id, title, authors, thumbnail, language)
    if not book:
        flash("No se pudo agregar el libro a la wishlist.", "error")
        current_app.logger.warning(f"Falló get_or_create_book para {google_id}")
        return redirect(request.referrer or url_for("books.search_books"))

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


@books_bp.route("/remove_from_wishlist", methods=["POST"])
@login_required
def remove_from_wishlist():
    book_id = request.form.get("book_id")
    if not book_id:
        flash("No se especificó el libro a eliminar.", "error")
        return redirect(url_for("books.view_wishlist"))

    book = Book.query.filter_by(google_id=book_id).first()
    if not book:
        flash("El libro no existe.", "error")
        return redirect(url_for("books.view_wishlist"))

    wishlist = current_user.wishlist
    if book in wishlist.books:
        wishlist.books.remove(book)
        db.session.commit()
        flash(f"'{book.title}' fue eliminado de tu wishlist.", "success")
    else:
        flash("Ese libro no está en tu wishlist.", "warning")

    return redirect(url_for("books.view_wishlist"))


@books_bp.route("/wishlist")
@login_required
def view_wishlist():
    books = current_user.wishlist.books if current_user.wishlist else []
    return render_template("books/wishlist.html", books=books)


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


@books_bp.route("/book/<id>")
@login_required
def book_detail(id):
    # Buscar primero en la base de datos
    book = Book.query.filter_by(google_id=id).first()

    # Intentar usar caché de búsqueda desde sesión
    cached_data = session.get("search_cache", {}).get(id)

    if book:
        info = {
            "title": book.title,
            "authors": [book.author],
            "language": book.language,
            "imageLinks": (
                {"thumbnail": book.small_thumbnail} if book.small_thumbnail else {}
            ),
            "description": getattr(book, "description", None),
            "publisher": getattr(book, "publisher", None),
            "publishedDate": getattr(book, "published_date", None),
            "categories": book.categories.split(",") if book.categories else [],
        }
    elif cached_data:
        info = {
            "title": cached_data.get("title"),
            "authors": cached_data.get("authors", []),
            "language": cached_data.get("language"),
            "imageLinks": (
                {"thumbnail": cached_data.get("thumbnail")}
                if cached_data.get("thumbnail")
                else {}
            ),
            "description": cached_data.get("description"),
            "publisher": cached_data.get("publisher"),
            "publishedDate": cached_data.get("publishedDate"),
            "categories": cached_data.get("categories", []),
        }
        book = None
    else:
        try:
            api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
            url = f"https://www.googleapis.com/books/v1/volumes/{id}"
            params = {"key": api_key}
            response = requests.get(url, params=params, timeout=5)
        except requests.RequestException as e:
            flash(
                "Lo sentimos, ocurrió un error de conexión con Google Books API.",
                "error",
            )
            current_app.logger.error(f"Error de conexión con Google Books: {e}")
            return redirect(url_for("books.search_books"))

        if response.status_code != 200:
            flash(
                "Lo sentimos, ocurrió un error de conexión con Google Books API.",
                "error",
            )
            current_app.logger.warning(
                f"Respuesta inválida para {id}: {response.status_code}"
            )
            return redirect(url_for("books.search_books"))

        data = response.json()
        volume = data.get("volumeInfo", {})
        info = {
            "title": volume.get("title"),
            "authors": volume.get("authors", []),
            "language": volume.get("language"),
            "imageLinks": (
                {"thumbnail": volume.get("imageLinks", {}).get("thumbnail")}
                if volume.get("imageLinks", {}).get("thumbnail")
                else {}
            ),
            "description": volume.get("description"),
            "publisher": volume.get("publisher"),
            "publishedDate": volume.get("publishedDate"),
            "categories": volume.get("categories", []),
        }
        book = None

    # Obtener IDs de libros en wishlist y biblioteca
    wishlist_ids = [b.google_id for b in getattr(current_user.wishlist, "books", [])]
    library_ids = [b.google_id for b in getattr(current_user.library, "books", [])]

    # Mostrar alerta si el libro ya está en wishlist
    if id in wishlist_ids:
        flash(f'⚠️ "{info.get("title", "Este libro")}" ya está en tu wishlist.', "info")

    return render_template(
        "books/book_detail.html",
        book=book,
        info=info,
        wishlist_ids=wishlist_ids,
        library_ids=library_ids,
    )
