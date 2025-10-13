import requests
import numpy as np
import hashlib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from flask import current_app

def build_user_profile(user_books):
    corpus = []
    for b in user_books:
        if b.author and b.categories and b.language:
            corpus.append(f"{b.author} {b.categories} {b.language}")
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(corpus)
    profile_vector = np.asarray(tfidf_matrix.mean(axis=0)).flatten()
    profile_hash = hashlib.md5(profile_vector.tobytes()).hexdigest()
    return profile_vector, vectorizer, profile_hash

def fetch_google_books(profile_vector, vectorizer, api_key, user_books, shown_ids=set(), max_results=40, min_similarity=0.25):
    user_ids = {b.google_id.strip().lower() for b in user_books if b.google_id}
    seen_titles, seen_authors, seen_isbns = set(), set(), set()
    results = []

    all_categories = [c for b in user_books if b.categories for c in b.categories.split("/") if c]
    dominant_category = all_categories[0] if all_categories else "fiction"
    query = f'subject:"{dominant_category}"'

    def fetch_items(lang):
        params = {
            "q": query,
            "langRestrict": lang,
            "maxResults": max_results,
            "printType": "books",
            "orderBy": "relevance",
            "key": api_key
        }
        try:
            response = requests.get("https://www.googleapis.com/books/v1/volumes", params=params, timeout=6)
            if response.status_code != 200:
                return []
            return response.json().get("items", [])
        except requests.RequestException:
            return []

    items = fetch_items("es") + fetch_items("en")

    for item in items:
        volume = item.get("volumeInfo", {})
        gid = item.get("id", "").strip().lower()
        if gid in user_ids or gid in shown_ids:
            continue

        title = volume.get("title", "").strip().lower()
        authors = volume.get("authors", [])
        author = authors[0].strip().lower() if authors else ""
        if title in seen_titles or author in seen_authors:
            continue
        if not volume.get("imageLinks", {}).get("thumbnail") or not authors or not volume.get("description"):
            continue

        categories = volume.get("categories", [])
        category = categories[0] if categories else ""
        language = volume.get("language", "")
        if language not in ("es", "en"):
            continue

        title_raw = volume.get("title", "")
        description = volume.get("description", "")

        industry_ids = volume.get("industryIdentifiers", [])
        isbn = next((
            identifier.get("identifier").replace("-", "").strip()
            for identifier in industry_ids
            if identifier.get("type") in ("ISBN_13", "ISBN_10")
        ), None)
        if isbn and isbn in seen_isbns:
            continue

        book_corpus = [f"{author} {category} {language} {title_raw} {description}"]
        book_vector = vectorizer.transform(book_corpus)
        score = cosine_similarity([profile_vector], book_vector)[0][0]

        current_app.logger.debug(f"[RECOMMEND] Libro '{title_raw}' → similitud={score:.3f}")

        if score < min_similarity:
            continue

        result = {
            "id": gid,
            "title": title_raw,
            "author": ", ".join(authors),
            "authors": authors,
            "language": language,
            "thumbnail": volume.get("imageLinks", {}).get("thumbnail"),
            "categories": categories,
            "description": description,
            "publisher": volume.get("publisher", ""),
            "publishedDate": volume.get("publishedDate", ""),
            "isbn": isbn,
            "similarity": round(score, 3)
        }

        results.append(result)
        shown_ids.add(gid)
        seen_titles.add(title)
        seen_authors.add(author)
        if isbn:
            seen_isbns.add(isbn)

    if results:
        results.sort(key=lambda x: x["similarity"], reverse=True)
        current_app.logger.info(f"[RECOMMEND] {len(results)} libros recomendados en español e inglés.")
        return results[:12]

    current_app.logger.info("[RECOMMEND] Sin recomendaciones útiles tras consulta.")
    return []