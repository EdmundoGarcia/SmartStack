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
import hashlib
from datetime import datetime, timedelta

import re
from sqlalchemy.orm import joinedload

from app.utils.recommend_engine import build_user_profile, fetch_google_books

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
    def is_incomplete(volume):
        return not volume.get("title") or not volume.get("authors")

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

    if len(session.get("search_cache", {})) > 200:
        session["search_cache"].clear()

    if not query:
        flash("Ingresa una palabra clave para buscar libros.", "warning")
        return render_template("books/search.html", results=[], page=page, total_pages=0)

    q = query
    if author:
        q += f"+inauthor:{author}"
    if publisher:
        q += f"+inpublisher:{publisher}"

    api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
    params = {
        "q": q,
        "startIndex": 0,
        "maxResults": 40,
        "orderBy": order_by,
        "key": api_key,
        "langRestrict": ",".join(lang_filters)
    }

    try:
        response = requests.get("https://www.googleapis.com/books/v1/volumes", params=params, timeout=5)
        raw_results = response.json().get("items", []) if response.status_code == 200 else []
    except requests.RequestException:
        flash("Error de conexión con Google Books API.", "error")
        return render_template("books/search.html", results=[], page=page, total_pages=0)

    filtered = []
    for item in raw_results:
        volume = item.get("volumeInfo", {})
        if is_incomplete(volume):
            continue
        lang = volume.get("language", "")
        if lang not in lang_filters:
            continue
        session.setdefault("search_cache", {})[item["id"]] = {
            "title": volume.get("title"),
            "authors": volume.get("authors", []),
            "language": lang,
            "thumbnail": volume.get("imageLinks", {}).get("thumbnail"),
            "description": volume.get("description"),
            "publisher": volume.get("publisher", "").strip(),
            "publishedDate": volume.get("publishedDate"),
            "categories": volume.get("categories", []),
            "isbn": next((i["identifier"].replace("-", "").strip()
                          for i in volume.get("industryIdentifiers", [])
                          if i["type"] in ("ISBN_13", "ISBN_10")), None)
        }
        filtered.append(item)

    total_items = len(filtered)
    total_pages = max(1, math.ceil(total_items / RESULTS_PER_PAGE))
    results = filtered[(page - 1) * RESULTS_PER_PAGE : page * RESULTS_PER_PAGE]

    wishlist_ids = [book.google_id for book in getattr(current_user.wishlist, "books", [])]
    library_ids = [book.google_id for book in getattr(current_user.library, "books", [])]

    return render_template(
    "books/search.html",
    results=results,
    page=page,
    total_pages=total_pages,
    query=query,
    lang_filters=lang_filters,
    author=author,
    publisher=publisher,
    order_by=order_by,
    wishlist_ids=wishlist_ids,
    library_ids=library_ids,
    total_items=total_items
)


@books_bp.route("/add_to_library", methods=["POST"])
@login_required
def add_to_library():
    google_id = request.form.get("book_id", "").strip()
    title = request.form.get("title", "").strip()
    authors = request.form.get("authors", "").strip()
    thumbnail = request.form.get("thumbnail", "").strip()
    language = request.form.get("language", "").strip().lower()
    isbn = request.form.get("isbn", "").strip()

    if not google_id or not title or not authors or not isbn:
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

    was_in_library = any(b.id == book.id for b in current_user.library.books)
    was_in_wishlist = current_user.wishlist and any(b.id == book.id for b in current_user.wishlist.books)

    if not was_in_library:
        current_user.library.books.append(book)
        flash(f'📚 "{title}" fue añadido a tu biblioteca.', "success")
    else:
        flash(f'⚠️ "{title}" ya está en tu biblioteca.', "info")

    if was_in_wishlist:
        current_user.wishlist.books.remove(book)
        flash(f'📚 "{title}" fue movido de tu wishlist a la biblioteca.', "success")

    db.session.commit()
    current_app.logger.info(f"[LIBRARY] Usuario {current_user.id} agregó {title}")
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

    if current_user.library and book in current_user.library.books:
        current_user.library.books.remove(book)
        db.session.commit()
        flash(f'🗑️ "{book.title}" fue eliminado de tu biblioteca.', "success")
        current_app.logger.info(f"[LIBRARY] Usuario {current_user.id} eliminó {book.title}")
    else:
        flash("⚠️ Ese libro no está en tu biblioteca.", "warning")

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

    if not google_id or not title or not authors or not isbn:
        flash("❌ Faltan datos esenciales para agregar el libro.", "error")
        return redirect(request.referrer or url_for("books.search_books"))

    if request.form.get("submitted") == session.get("last_submission"):
        flash("⚠️ Ya procesamos esta acción. Evita enviar el formulario dos veces.", "warning")
        return redirect(request.referrer or url_for("books.search_books"))
    session["last_submission"] = request.form.get("submitted")

    book = get_or_create_book(google_id, title, authors, thumbnail, language, isbn)
    if not book:
        flash("❌ No se pudo agregar el libro a la wishlist.", "error")
        current_app.logger.warning(f"[WISHLIST] Falló get_or_create_book para {google_id}")
        return redirect(request.referrer or url_for("books.search_books"))

    if current_user.library and any(b.id == book.id for b in current_user.library.books):
        flash(f'📚 "{title}" ya está en tu biblioteca. No se puede agregar a la wishlist.', "info")
        return redirect(request.referrer or url_for("books.search_books"))

    if not current_user.wishlist:
        db.session.add(Wishlist(user=current_user))
        db.session.commit()

    already_in_wishlist = any(b.id == book.id for b in current_user.wishlist.books)

    if not already_in_wishlist:
        current_user.wishlist.books.append(book)
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

    if current_user.wishlist and book in current_user.wishlist.books:
        current_user.wishlist.books.remove(book)
        db.session.commit()
        flash(f'🗑️ "{book.title}" fue eliminado de tu wishlist.', "success")
        current_app.logger.info(f"[WISHLIST] Usuario {current_user.id} eliminó {book.title}")
    else:
        flash("⚠️ Ese libro no está en tu wishlist.", "warning")

    return redirect(url_for("books.view_wishlist"))


@books_bp.route("/wishlist")
@login_required
def view_wishlist():
    books = current_user.wishlist.books if current_user.wishlist else []
    current_app.logger.info(f"[WISHLIST] Usuario {current_user.id} accedió a wishlist con {len(books)} libros.")
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
    current_app.logger.info(f"[LIBRARY] Usuario {current_user.id} accedió a biblioteca con {len(books)} libros.")
    return render_template("books/library.html", books=books)

@books_bp.route("/book/<id>")
@login_required
def book_detail(id):
    def is_cache_incomplete(data):
        return (
            not data.get("publisher") or
            not data.get("authors") or
            not data.get("thumbnail") or
            not data.get("description")
        )

    book = Book.query.filter_by(google_id=id).first()
    cached_data = (
        session.get("search_cache", {}).get(id)
        or next((b for b in session.get("recommendation_cache", []) if b["id"] == id), None)
    )

    if book:
        source = "db"
        info = {
            "title": book.title,
            "authors": [book.author],
            "language": book.language,
            "imageLinks": {"thumbnail": book.small_thumbnail} if book.small_thumbnail else {},
            "description": book.description or "Descripción no disponible",
            "publisher": book.publisher or "Editorial no disponible",
            "publishedDate": book.published_date or "Fecha no disponible",
            "categories": book.categories.split(",") if book.categories else [],
            "isbn": book.isbn,
            "source": source
        }

    elif cached_data:
        source = "cache"
        if is_cache_incomplete(cached_data):
            current_app.logger.info(f"[DEBUG] Caché incompleto para {id}, se mostrará vista parcial.")
        info = {
            "title": cached_data.get("title", "Título no disponible"),
            "authors": cached_data.get("authors", []),
            "language": cached_data.get("language", "Idioma no disponible"),
            "imageLinks": {"thumbnail": cached_data.get("thumbnail")} if cached_data.get("thumbnail") else {},
            "description": cached_data.get("description", "Descripción no disponible"),
            "publisher": cached_data.get("publisher", "Editorial no disponible"),
            "publishedDate": cached_data.get("publishedDate", "Fecha no disponible"),
            "categories": cached_data.get("categories", []),
            "isbn": cached_data.get("isbn"),
            "source": source
        }
        book = None

    else:
        try:
            api_key = current_app.config["GOOGLE_BOOKS_API_KEY"]
            url = f"https://www.googleapis.com/books/v1/volumes/{id}"
            response = requests.get(url, params={"key": api_key}, timeout=5)
            volume = response.json().get("volumeInfo", {}) if response.status_code == 200 else {}
        except requests.RequestException:
            flash("No se pudo obtener los detalles del libro.", "error")
            return redirect(url_for("books.recommendations"))

        source = "api"
        info = {
            "title": volume.get("title", "Título no disponible"),
            "authors": volume.get("authors", []),
            "language": volume.get("language", "Idioma no disponible"),
            "imageLinks": {"thumbnail": volume.get("imageLinks", {}).get("thumbnail")} if volume.get("imageLinks", {}).get("thumbnail") else {},
            "description": volume.get("description", "Descripción no disponible"),
            "publisher": volume.get("publisher", "Editorial no disponible").strip(),
            "publishedDate": volume.get("publishedDate", "Fecha no disponible"),
            "categories": volume.get("categories", []),
            "isbn": next((i["identifier"].replace("-", "").strip()
                          for i in volume.get("industryIdentifiers", [])
                          if i["type"] in ("ISBN_13", "ISBN_10")), None),
            "source": source
        }
        book = None

    wishlist_ids = [b.google_id for b in getattr(current_user.wishlist, "books", [])]
    library_ids = [b.google_id for b in getattr(current_user.library, "books", [])]

    isbn = info.get("isbn")

    amazon_link = f"https://www.amazon.com.mx/s?k={isbn}" if isbn else None
    gandhi_link = f"https://www.gandhi.com.mx/search?query={isbn}" if isbn else None
    porrua_link = f"https://porrua.mx/catalogsearch/result/?q={isbn}" if isbn else None
    gonvill_link = f"https://www.gonvill.com.mx/busqueda/listaLibros.php?tipoBus=full&palabrasBusqueda={isbn}" if isbn else None
    buscalibre_link = f"https://www.buscalibre.com.mx/libros/search?q={isbn}" if isbn else None
    
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
        buscalibre_link=buscalibre_link
    )


@books_bp.route("/recommendations")
@login_required
def recommendations():
    user_books = Book.query.join(UserLibrary.books).filter(UserLibrary.user_id == current_user.id).all()
    recommendation_cache = session.get("recommendation_cache", [])

    if len(user_books) < 3 and not recommendation_cache:
        flash("Agrega al menos 3 libros a tu biblioteca para recibir recomendaciones.", "warning")
        current_app.logger.info(f"[RECOMMEND] Usuario {current_user.id} sin perfil suficiente ni caché.")

    return render_template("books/recommendations.html")


@books_bp.route("/recommendations/fetch")
@login_required
def fetch_recommendations():
    user_books = Book.query.join(UserLibrary.books).filter(UserLibrary.user_id == current_user.id).all()
    if len(user_books) < 3:
        return {"error": "Perfil insuficiente"}

    current_ids = {b.google_id for b in user_books}
    profile_vector, vectorizer, profile_hash = build_user_profile(user_books)

    last_hash = session.get("last_profile_hash")
    last_fetched = session.get("last_fetched")
    cache = session.get("recommendation_cache", [])
    rotation_index = session.get("rotation_index", 0)

    # Detectar caché agotada
    if last_hash == profile_hash and cache and last_fetched:
        age = datetime.utcnow() - datetime.fromisoformat(last_fetched)
        if age < timedelta(hours=48):
            if rotation_index >= len(cache):
                current_app.logger.info(f"[RECOMMEND] Caché agotada para perfil {profile_hash}. Regenerando.")
                last_hash = None  # Forzar regeneración
            else:
                chunk = cache[rotation_index:rotation_index + 3]
                session["rotation_index"] = (rotation_index + 3) % len(cache)
                current_app.logger.info(f"[RECOMMEND] Usuario {current_user.id} recibió lote {rotation_index} desde caché.")
                return {"books": chunk}

    # Regenerar si el perfil cambió o no hay caché útil
    shown_ids = session.get("shown_recommendations", set())
    if last_hash != profile_hash:
        shown_ids = set()  # Reiniciar si el perfil cambió

    api_key = current_app.config.get("GOOGLE_BOOKS_API_KEY")
    recommendations = fetch_google_books(
        profile_vector,
        vectorizer,
        api_key,
        user_books,
        shown_ids,
        min_similarity=0.2
    )

    if recommendations:
        session["recommendation_cache"] = recommendations
        session["shown_recommendations"] = shown_ids
        session["last_profile_hash"] = profile_hash
        session["last_fetched"] = datetime.utcnow().isoformat()
        session["rotation_index"] = 3
        current_app.logger.info(f"[RECOMMEND] {len(recommendations)} libros generados para perfil {profile_hash}.")
        return {"books": recommendations[:3]}

    current_app.logger.info(f"[RECOMMEND] Sin resultados útiles para perfil {profile_hash}.")
    return {"books": []}