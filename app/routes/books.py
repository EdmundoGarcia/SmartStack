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
from app.models import Book, Wishlist, UserLibrary, User, WishlistBook, LibraryBook
from app.extensions import db
from app.utils.books import get_or_create_book, clean_description
import math
import hashlib
from datetime import datetime, timedelta

import re
from sqlalchemy.orm import joinedload

from app.utils.recommend_engine import (
    build_user_profile,
    fetch_google_books,
    group_books_by_category,
    CATEGORY_GROUPS,
)

import numpy as np

books_bp = Blueprint("books", __name__)


@books_bp.route("/")
@login_required
def dashboard():
    return render_template("user/dashboard.html")


@books_bp.route("/search")
@login_required
def search_books():
    import re

    def is_incomplete(volume):
        return not volume.get("title") or not volume.get("authors")

    def get_book_id_by_isbn(isbn):
        api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
        params = {"q": f"isbn:{isbn}", "maxResults": 1, "key": api_key}
        try:
            response = requests.get(
                "https://www.googleapis.com/books/v1/volumes", params=params, timeout=5
            )
            items = (
                response.json().get("items", []) if response.status_code == 200 else []
            )
            return items[0]["id"] if items else None
        except requests.RequestException:
            return None

    query = request.args.get("q", "").strip()
    lang_filters = request.args.getlist("lang") or ["es", "en"]
    author_filter = request.args.get("author", "").strip()
    publisher = request.args.get("publisher", "").strip()
    order_by = request.args.get("order", "relevance")
    page = int(request.args.get("page", 1))

    RESULTS_PER_PAGE = 10
    MAX_RESULTS = 40
    MAX_CACHE_SIZE = 200
    start_index = (page - 1) * RESULTS_PER_PAGE

    # Cache cleanup
    if len(session.get("search_cache", {})) > MAX_CACHE_SIZE:
        session["search_cache"].clear()
        session["query_cache"] = {}

    if not query and not author_filter and not publisher:
        flash(
            "Ingresa una palabra clave, autor o editorial para buscar libros.",
            "warning",
        )
        return render_template(
            "books/search.html", results=[], page=page, total_pages=0
        )

    # Si el query es un ISBN válido, redirige al detalle
    if re.fullmatch(r"97[89]\d{10}", query):
        book_id = get_book_id_by_isbn(query)
        if book_id:
            return redirect(url_for("books.book_detail", google_id=book_id))
        else:
            flash(f"No se encontró ningún libro con ISBN {query}.", "warning")
            return render_template(
                "books/search.html", results=[], page=page, total_pages=0
            )

    q = query or ""
    if author_filter and not query:
        q = f"inauthor:{author_filter}"
    if publisher:
        q += f"+inpublisher:{publisher}"

    cache_key = f"{q}|{publisher}|{order_by}|{','.join(lang_filters)}|page:{page}"
    query_cache = session.setdefault("query_cache", {})

    if cache_key in query_cache:
        current_app.logger.info(
            f"[CACHE HIT] Página {page} recuperada de caché para: {cache_key}"
        )
        filtered = query_cache[cache_key]
    else:
        api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
        params = {
            "q": q,
            "maxResults": RESULTS_PER_PAGE,
            "startIndex": start_index,
            "orderBy": order_by,
            "key": api_key,
            "langRestrict": ",".join(lang_filters),
        }

        try:
            response = requests.get(
                "https://www.googleapis.com/books/v1/volumes", params=params, timeout=5
            )
            raw_results = (
                response.json().get("items", []) if response.status_code == 200 else []
            )
        except requests.RequestException:
            flash("Error de conexión con Google Books API.", "error")
            return render_template(
                "books/search.html", results=[], page=page, total_pages=0
            )

        filtered = []
        for item in raw_results:
            volume = item.get("volumeInfo", {})
            if is_incomplete(volume):
                continue
            if author_filter:
                author_lower = author_filter.lower()
                if not any(
                    author_lower in a.lower() for a in volume.get("authors", [])
                ):
                    continue
            lang = volume.get("language", "")
            if lang not in lang_filters:
                continue

            session.setdefault("search_cache", {})[item["id"]] = {
                "google_id": item["id"],
                "title": volume.get("title"),
                "authors": volume.get("authors", []),
                "authors_list": volume.get("authors", []),
                "language": lang,
                "thumbnail": volume.get("imageLinks", {}).get("thumbnail"),
                "description": clean_description(volume.get("description", "")),
                "publisher": volume.get("publisher", "").strip(),
                "publishedDate": volume.get("publishedDate"),
                "categories": volume.get("categories", []),
                "categories_list": volume.get("categories", []),
                "isbn": next(
                    (
                        i["identifier"].replace("-", "").strip()
                        for i in volume.get("industryIdentifiers", [])
                        if i["type"] in ("ISBN_13", "ISBN_10")
                    ),
                    None,
                ),
            }
            filtered.append(item)

        query_cache[cache_key] = filtered

    total_items = len(filtered)
    total_pages = min(4, math.ceil(MAX_RESULTS / RESULTS_PER_PAGE))
    results = filtered

    wishlist_ids = [
        book.google_id for book in getattr(current_user.wishlist, "books", [])
    ]
    library_ids = [
        book.google_id for book in getattr(current_user.library, "books", [])
    ]

    return render_template(
        "books/search.html",
        results=results,
        page=page,
        total_pages=total_pages,
        query=query,
        lang_filters=lang_filters,
        author=author_filter,
        publisher=publisher,
        order_by=order_by,
        wishlist_ids=wishlist_ids,
        library_ids=library_ids,
        total_items=total_items,
        search_cache=session.get("search_cache", {}),
    )


@books_bp.route("/add_to_library", methods=["POST"])
@login_required
def add_to_library():
    google_id = request.form.get("book_id", "").strip()
    title = request.form.get("title", "").strip()
    authors_raw = request.form.get("authors", "").strip()
    thumbnail = request.form.get("thumbnail", "").strip()
    language = request.form.get("language", "").strip().lower()
    isbn = request.form.get("isbn", "").strip()

    authors = [a.strip() for a in authors_raw.split(",") if a.strip()]

    if not google_id or not title or not authors:
        flash("❌ Faltan datos esenciales para agregar el libro.", "error")
        return redirect(request.referrer or url_for("books.search_books"))

    if request.form.get("submitted") == session.get("last_submission"):
        flash("⚠️ Ya procesamos esta acción. Evita enviar el formulario dos veces.", "warning")
        return redirect(request.referrer or url_for("books.search_books"))
    session["last_submission"] = request.form.get("submitted")

    book = get_or_create_book(google_id, title, authors, thumbnail, language, isbn)
    if not book:
        flash("❌ No se pudo agregar el libro a la biblioteca.", "error")
        current_app.logger.warning(f"[LIBRARY] Falló get_or_create_book para {google_id}")
        return redirect(request.referrer or url_for("books.search_books"))

    if not current_user.library:
        db.session.add(UserLibrary(user=current_user))
        db.session.commit()

    library = current_user.library
    existing = LibraryBook.query.filter_by(library_id=library.id, book_id=book.id).first()
    was_in_wishlist = current_user.wishlist and any(b.id == book.id for b in current_user.wishlist.books)

    if not existing:
        lb = LibraryBook(library_id=library.id, book_id=book.id)
        db.session.add(lb)
        flash(f'📚 "{title}" fue añadido a tu biblioteca.', "success")
    else:
        flash(f'⚠️ "{title}" ya está en tu biblioteca.', "info")

    if was_in_wishlist:
        wb = WishlistBook.query.filter_by(wishlist_id=current_user.wishlist.id, book_id=book.id).first()
        if wb:
            db.session.delete(wb)
            flash(f'📚 "{title}" fue movido de tu wishlist a la biblioteca.', "success")

    db.session.commit()
    current_app.logger.info(f"[LIBRARY] Usuario {current_user.id} agregó {title} ({google_id})")
    return redirect(request.referrer or url_for("books.search_books"))



@books_bp.route("/remove_from_library", methods=["POST"])
@login_required
def remove_from_library():
    book_id = request.form.get("book_id", "").strip()
    if not book_id:
        flash("❌ No se especificó el libro a eliminar.", "error")
        return redirect(url_for("books.view_library"))

    book = Book.query.filter_by(google_id=book_id).first()
    if not book:
        flash("❌ El libro no existe.", "error")
        return redirect(url_for("books.view_library"))

    if current_user.library:
        link = LibraryBook.query.filter_by(
            library_id=current_user.library.id,
            book_id=book.id
        ).first()

        if link:
            db.session.delete(link)
            db.session.commit()
            flash(f'"{book.title}" fue eliminado de tu biblioteca.', "success")
            current_app.logger.info(f"[LIBRARY] Usuario {current_user.id} eliminó {book.title}")
        else:
            flash("⚠️ Ese libro no está en tu biblioteca.", "warning")
    else:
        flash("⚠️ No tienes una biblioteca activa.", "warning")

    return redirect(url_for("books.view_library"))



@books_bp.route("/add_to_wishlist", methods=["POST"])
@login_required
def add_to_wishlist():
    google_id = request.form.get("book_id", "").strip()
    title = request.form.get("title", "").strip()
    authors = request.form.get("authors", "").strip()
    thumbnail = request.form.get("thumbnail", "").strip()
    language = request.form.get("language", "").strip().lower()
    isbn = request.form.get("isbn", "").strip()

    if not google_id or not title or not authors:
        flash("❌ Faltan datos esenciales para agregar el libro.", "error")
        return redirect(request.referrer or url_for("books.search_books"))

    # Prevent double submission
    if request.form.get("submitted") == session.get("last_submission"):
        flash(
            "⚠️ Ya procesamos esta acción. Evita enviar el formulario dos veces.",
            "warning",
        )
        return redirect(request.referrer or url_for("books.search_books"))
    session["last_submission"] = request.form.get("submitted")

    book = get_or_create_book(google_id, title, authors, thumbnail, language, isbn)
    if not book:
        flash("❌ No se pudo agregar el libro a la wishlist.", "error")
        current_app.logger.warning(
            f"[WISHLIST] Falló get_or_create_book para {google_id}"
        )
        return redirect(request.referrer or url_for("books.search_books"))

    # Verify if the book is already on user's library
    if current_user.library and any(
        b.id == book.id for b in current_user.library.books
    ):
        flash(
            f'📚 "{title}" ya está en tu biblioteca. No se puede agregar a la wishlist.',
            "info",
        )
        return redirect(request.referrer or url_for("books.search_books"))

    # Create wishlist if it doesn't exist
    if not current_user.wishlist:
        wishlist = Wishlist(user=current_user)
        db.session.add(wishlist)
        db.session.commit()
    else:
        wishlist = current_user.wishlist

    # Verify if the book is already on the user's wishlist
    already_in_wishlist = any(wb.book_id == book.id for wb in wishlist.wishlist_books)

    if not already_in_wishlist:
        wb = WishlistBook(
            wishlist_id=wishlist.id, book_id=book.id, added_at=datetime.utcnow()
        )
        db.session.add(wb)
        flash(f'📌 "{title}" fue añadido a tu wishlist.', "success")
    else:
        flash(f'⚠️ "{title}" ya está en tu wishlist.', "info")

    db.session.commit()
    current_app.logger.info(f"[WISHLIST] Usuario {current_user.id} agregó {title}")
    return redirect(request.referrer or url_for("books.search_books"))


@books_bp.route("/remove_from_wishlist", methods=["POST"])
@login_required
def remove_from_wishlist():
    book_id = request.form.get("book_id", "").strip()
    if not book_id:
        flash("❌ No se especificó el libro a eliminar.", "error")
        return redirect(url_for("books.view_wishlist"))

    book = Book.query.filter_by(google_id=book_id).first()
    if not book:
        flash("❌ El libro no existe.", "error")
        return redirect(url_for("books.view_wishlist"))

    wishlist = current_user.wishlist
    if not wishlist:
        flash("⚠️ No tienes una wishlist activa.", "warning")
        return redirect(url_for("books.view_wishlist"))

    wb = WishlistBook.query.filter_by(wishlist_id=wishlist.id, book_id=book.id).first()
    if not wb:
        flash("⚠️ Ese libro no está en tu wishlist.", "info")
        return redirect(url_for("books.view_wishlist"))

    db.session.delete(wb)
    db.session.commit()
    flash(f'"{book.title}" fue eliminado de tu wishlist.', "success")
    current_app.logger.info(
        f"[WISHLIST] Usuario {current_user.id} eliminó {book.title}"
    )
    return redirect(url_for("books.view_wishlist"))


@books_bp.route("/wishlist")
@login_required
def view_wishlist():
    page = request.args.get("page", 1, type=int)
    sort = request.args.get("sort", "recent")
    search = request.args.get("search", "", type=str).strip().lower()
    per_page = 12

    wishlist = current_user.wishlist
    if not wishlist or not wishlist.wishlist_books:
        return render_template(
            "books/wishlist.html",
            books=[],
            page=1,
            total=0,
            per_page=per_page,
            search=search,
            sort=sort,
            is_empty=True,
        )

    query = wishlist.wishlist_books

    if search:
        query = [
            wb for wb in query
            if search in (wb.book.title or "").lower()
            or search in (wb.book.authors or "").lower()
        ]

    if sort == "title_asc":
        query = sorted(query, key=lambda wb: (wb.book.title or "").lower())
    elif sort == "title_desc":
        query = sorted(query, key=lambda wb: (wb.book.title or "").lower(), reverse=True)
    elif sort == "oldest":
        query = sorted(query, key=lambda wb: wb.added_at)
    else:
        query = sorted(query, key=lambda wb: wb.added_at, reverse=True)

    total = len(query)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_books = [wb.book for wb in query[start:end]]

    return render_template(
        "books/wishlist.html",
        books=paginated_books,
        page=page,
        total=total,
        per_page=per_page,
        search=search,
        sort=sort,
        is_empty=(total == 0),
    )



@books_bp.route("/wishlist/search")
@login_required
def search_wishlist():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "", type=str).strip().lower()
    sort = request.args.get("sort", "recent")
    per_page = 12

    wishlist = current_user.wishlist
    if not wishlist:
        return "", 204

    query = wishlist.wishlist_books

    if search:
        query = [
            wb for wb in query
            if search in (wb.book.title or "").lower()
            or search in (wb.book.authors or "").lower()
        ]

    if sort == "title_asc":
        query = sorted(query, key=lambda wb: (wb.book.title or "").lower())
    elif sort == "title_desc":
        query = sorted(query, key=lambda wb: (wb.book.title or "").lower(), reverse=True)
    elif sort == "oldest":
        query = sorted(query, key=lambda wb: wb.added_at)
    else:
        query = sorted(query, key=lambda wb: wb.added_at, reverse=True)

    total = len(query)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_books = [wb.book for wb in query[start:end]]

    wishlist_ids = [b.google_id for b in getattr(current_user.wishlist, "books", [])]
    library_ids = [b.google_id for b in getattr(current_user.library, "books", [])]

    return render_template(
        "books/_books_ajax.html",
        books=paginated_books,
        page=page,
        total=total,
        per_page=per_page,
        base_url=url_for("books.view_wishlist"),
        card_template="books/_wishlist_card.html",
        wishlist_ids=wishlist_ids,
        library_ids=library_ids,
    )



@books_bp.route("/library")
@login_required
def view_library():
    page = request.args.get("page", 1, type=int)
    sort = request.args.get("sort", "title_asc")
    search = request.args.get("search", "", type=str).strip().lower()
    per_page = 12

    library = current_user.library
    if not library or not library.library_books:
        return render_template(
            "books/library.html",
            books=[],
            page=1,
            total=0,
            per_page=per_page,
            wishlist_ids=[],
            library_ids=[],
            search=search,
            sort=sort,
            is_empty=True,
        )

    query = library.library_books

    if search:
        query = [
            lb for lb in query
            if search in (lb.book.title or "").lower()
            or search in (lb.book.authors or "").lower()
        ]

    if sort == "title_asc":
        query = sorted(query, key=lambda lb: (lb.book.title or "").lower())
    elif sort == "title_desc":
        query = sorted(query, key=lambda lb: (lb.book.title or "").lower(), reverse=True)
    elif sort == "oldest":
        query = sorted(query, key=lambda lb: lb.added_at)
    elif sort == "recent":
        query = sorted(query, key=lambda lb: lb.added_at, reverse=True)

    total = len(query)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_books = [lb.book for lb in query[start:end]]

    wishlist_ids = [b.google_id for b in getattr(current_user.wishlist, "books", [])]
    library_ids = [lb.book.google_id for lb in library.library_books]

    current_app.logger.info(
        f"[LIBRARY] Usuario {current_user.id} accedió a biblioteca con {total} libros."
    )

    return render_template(
        "books/library.html",
        books=paginated_books,
        page=page,
        total=total,
        per_page=per_page,
        wishlist_ids=wishlist_ids,
        library_ids=library_ids,
        search=search,
        sort=sort,
        is_empty=(total == 0),
    )


@books_bp.route("/library/search")
@login_required
def search_library():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "", type=str).strip().lower()
    sort = request.args.get("sort", "title_asc")
    per_page = 12

    library = current_user.library
    if not library or not library.library_books:
        return "", 204

    query = library.library_books

    if search:
        query = [
            lb for lb in query
            if search in (lb.book.title or "").lower()
            or search in (lb.book.authors or "").lower()
        ]

    if sort == "title_asc":
        query = sorted(query, key=lambda lb: (lb.book.title or "").lower())
    elif sort == "title_desc":
        query = sorted(query, key=lambda lb: (lb.book.title or "").lower(), reverse=True)
    elif sort == "oldest":
        query = sorted(query, key=lambda lb: lb.added_at)
    elif sort == "recent":
        query = sorted(query, key=lambda lb: lb.added_at, reverse=True)

    total = len(query)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_books = [lb.book for lb in query[start:end]]

    wishlist_ids = [b.google_id for b in getattr(current_user.wishlist, "books", [])]
    library_ids = [lb.book.google_id for lb in library.library_books]

    return render_template(
        "books/_books_ajax.html",
        books=paginated_books,
        page=page,
        total=total,
        per_page=per_page,
        base_url=url_for("books.view_library"),
        card_template="books/_library_card.html",
        wishlist_ids=wishlist_ids,
        library_ids=library_ids,
    )


@books_bp.route("/book/<google_id>")
@login_required
def book_detail(google_id):
    def is_cache_incomplete(data):
        return (
            not data.get("publisher")
            or not data.get("authors")
            or not data.get("thumbnail")
            or not data.get("description")
        )

    def flatten_categories(cats):
        return [part.strip() for cat in cats for part in cat.split("/") if part.strip()]

    book = Book.query.filter_by(google_id=google_id).first()

    cached_data = session.get("search_cache", {}).get(google_id) or next(
        (b for b in session.get("recommendation_cache", []) if b["id"] == google_id),
        None,
    )

    if book:
        source = "db"
        info = {
            "title": book.title,
            "authors": book.authors.split(",") if book.authors else [],
            "language": book.language,
            "imageLinks": (
                {"thumbnail": book.small_thumbnail} if book.small_thumbnail else {}
            ),
            "description": (
                clean_description(book.description)
                if book.description
                else "Descripción no disponible"
            ),
            "publisher": book.publisher or "Editorial no disponible",
            "publishedDate": book.published_date or "Fecha no disponible",
            "categories": book.categories.split(",") if book.categories else [],
            "categories_flat": book.categories_flat,
            "isbn": book.isbn,
            "source": source,
        }

    elif cached_data:
        source = "cache"
        if is_cache_incomplete(cached_data):
            current_app.logger.info(
                f"[DEBUG] Caché incompleto para {google_id}, se mostrará vista parcial."
            )
        raw_categories = cached_data.get("categories", [])
        info = {
            "title": cached_data.get("title", "Título no disponible"),
            "authors": cached_data.get("authors", []),
            "language": cached_data.get("language", "Idioma no disponible"),
            "imageLinks": (
                {"thumbnail": cached_data.get("thumbnail")}
                if cached_data.get("thumbnail")
                else {}
            ),
            "description": clean_description(cached_data.get("description", ""))
            or "Descripción no disponible",
            "publisher": cached_data.get("publisher", "Editorial no disponible"),
            "publishedDate": cached_data.get("publishedDate", "Fecha no disponible"),
            "categories": raw_categories,
            "categories_flat": flatten_categories(raw_categories),
            "isbn": cached_data.get("isbn"),
            "source": source,
        }
        book = None

    else:
        try:
            api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
            url = f"https://www.googleapis.com/books/v1/volumes/{google_id}"
            response = requests.get(url, params={"key": api_key}, timeout=5)
            volume = (
                response.json().get("volumeInfo", {})
                if response.status_code == 200
                else {}
            )
        except requests.RequestException:
            flash("No se pudo obtener los detalles del libro.", "error")
            return redirect(url_for("books.recommendations"))

        source = "api"
        raw_categories = volume.get("categories", [])
        info = {
            "title": volume.get("title", "Título no disponible"),
            "authors": volume.get("authors", []),
            "language": volume.get("language", "Idioma no disponible"),
            "imageLinks": (
                {"thumbnail": volume.get("imageLinks", {}).get("thumbnail")}
                if volume.get("imageLinks", {}).get("thumbnail")
                else {}
            ),
            "description": clean_description(volume.get("description", ""))
            or "Descripción no disponible",
            "publisher": volume.get("publisher", "Editorial no disponible").strip(),
            "publishedDate": volume.get("publishedDate", "Fecha no disponible"),
            "categories": raw_categories,
            "categories_flat": flatten_categories(raw_categories),
            "isbn": next(
                (
                    i["identifier"].replace("-", "").strip()
                    for i in volume.get("industryIdentifiers", [])
                    if i["type"] in ("ISBN_13", "ISBN_10")
                ),
                None,
            ),
            "source": source,
        }
        book = None

    wishlist_ids = [b.google_id for b in getattr(current_user.wishlist, "books", [])]
    library_ids = [b.google_id for b in getattr(current_user.library, "books", [])]

    isbn = info.get("isbn")

    amazon_link = f"https://www.amazon.com.mx/s?k={isbn}" if isbn else None
    gandhi_link = f"https://www.gandhi.com.mx/search?query={isbn}" if isbn else None
    porrua_link = f"https://porrua.mx/catalogsearch/result/?q={isbn}" if isbn else None
    gonvill_link = (
        f"https://www.gonvill.com.mx/busqueda/listaLibros.php?tipoBus=full&palabrasBusqueda={isbn}"
        if isbn
        else None
    )
    buscalibre_link = (
        f"https://www.buscalibre.com.mx/libros/search?q={isbn}" if isbn else None
    )

    return render_template(
        "books/book_detail.html",
        book=book,
        info=info,
        wishlist_ids=wishlist_ids,
        library_ids=library_ids,
        amazon_link=amazon_link,
        gandhi_link=gandhi_link,
        porrua_link=porrua_link,
        gonvill_link=gonvill_link,
        buscalibre_link=buscalibre_link,
    )



@books_bp.route("/recommendations")
@login_required
def recommendations():
    user_books = (
        Book.query
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .join(UserLibrary, UserLibrary.id == LibraryBook.library_id)
        .filter(UserLibrary.user_id == current_user.id)
        .all()
    )

    recommendation_cache = session.get("recommendation_cache", [])

    if len(user_books) < 3 and not recommendation_cache:
        flash("Agrega al menos 3 libros a tu biblioteca para recibir recomendaciones.", "warning")
        current_app.logger.info(f"[RECOMMEND] Usuario {current_user.id} sin perfil suficiente ni caché.")
        return redirect(url_for("books.view_library"))

    grouped = group_books_by_category(user_books)
    user_categories = sorted(grouped.keys())

    return render_template("books/recommendations.html", user_categories=user_categories)

@books_bp.route("/recommendations/fetch")
@login_required
def fetch_recommendations():
    user_books = (
        Book.query
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .join(UserLibrary, UserLibrary.id == LibraryBook.library_id)
        .filter(UserLibrary.user_id == current_user.id)
        .all()
    )
    if len(user_books) < 3:
        return {"error": "Perfil insuficiente"}

    selected_category = request.args.get("selected_category", "").strip()
    selected_categories = [selected_category] if selected_category and selected_category.lower() not in ("undefined", "null") else None

    profile_vector, vectorizer, profile_hash = build_user_profile(
        user_books, selected_categories=selected_categories
    )
    if profile_vector is None:
        current_app.logger.info(f"[RECOMMEND] Perfil vacío para usuario {current_user.id}.")
        return {"error": "No se pudo construir el perfil"}

    last_hash = session.get("last_profile_hash")
    last_fetched = session.get("last_fetched")
    cache = session.get("recommendation_cache", [])
    rotation_index = session.get("rotation_index", 0)

    try:
        age = datetime.utcnow() - datetime.fromisoformat(last_fetched)
    except (ValueError, TypeError):
        age = timedelta(hours=999)

    if last_hash == profile_hash and cache and age < timedelta(hours=48):
        if rotation_index >= len(cache):
            current_app.logger.info(f"[RECOMMEND] Caché agotada para perfil {profile_hash}. Regenerando.")
            last_hash = None
        else:
            chunk = cache[rotation_index : rotation_index + 3]
            session["rotation_index"] = (rotation_index + 3) % len(cache)
            current_app.logger.info(f"[RECOMMEND] Usuario {current_user.id} recibió lote {rotation_index} desde caché.")
            return {"books": chunk}

    shown_ids = set(session.get("shown_recommendations", []))
    if last_hash != profile_hash:
        shown_ids = set()
        rotation_index = 0
        session["shown_recommendations"] = []

    api_key = current_app.config.get("GOOGLE_BOOKS_API_KEY")
    recommendations = fetch_google_books(
        profile_vector,
        vectorizer,
        api_key,
        user_books,
        shown_ids,
        selected_categories=selected_categories,
        min_similarity=0.2,
    )

    if recommendations:
        valid_scores = [r["similarity"] for r in recommendations if "similarity" in r]
        avg_score = np.mean(valid_scores) if valid_scores else 0
        current_app.logger.info(f"[RECOMMEND] {len(recommendations)} libros generados para perfil {profile_hash}. Similitud promedio: {avg_score:.3f}")

        session["recommendation_cache"] = recommendations
        session["shown_recommendations"] = list(shown_ids)
        session["last_profile_hash"] = profile_hash
        session["last_fetched"] = datetime.utcnow().isoformat()
        session["rotation_index"] = 3

        return {"books": recommendations[0:3]}

    current_app.logger.info(f"[RECOMMEND] Sin resultados útiles para perfil {profile_hash}.")
    return {
        "books": [],
        "message": "No se encontraron recomendaciones relevantes en este momento. Intenta más tarde o agrega más libros a tu biblioteca."
    }


@books_bp.route("/search/isbn-scan")
@login_required
def isbn_scan():
    return render_template("books/isbn_scan.html")


@books_bp.route("/isbn/<isbn>")
@login_required
def resolve_isbn(isbn):
    api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
    params = {"q": f"isbn:{isbn}", "maxResults": 1, "key": api_key}

    try:
        response = requests.get(
            "https://www.googleapis.com/books/v1/volumes", params=params, timeout=5
        )
        items = response.json().get("items", []) if response.status_code == 200 else []
    except requests.RequestException:
        flash("No se pudo buscar el ISBN.", "error")
        return redirect(url_for("books.search_books"))

    if not items:
        flash("No se encontró ningún libro con ese ISBN.", "warning")
        return redirect(url_for("books.search_books"))

    google_id = items[0]["id"]
    return redirect(url_for("books.book_detail", google_id=book_id))
