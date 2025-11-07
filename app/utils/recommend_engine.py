import requests
import numpy as np
import hashlib
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from flask import current_app
from collections import defaultdict
from app.utils.books import clean_description

CATEGORY_GROUPS = {
    "Fiction": ["Fiction", "Literary Fiction", "Contemporary Fiction", "Short Stories"],
    "Romance": ["Romance", "Historical Romance", "Paranormal Romance", "Chick Lit"],
    "Mystery & Thriller": ["Mystery", "Thriller", "Crime", "Suspense", "Detective"],
    "Science Fiction": ["Science Fiction", "Dystopian", "Space Opera", "Cyberpunk"],
    "Fantasy": ["Fantasy", "Epic Fantasy", "Urban Fantasy", "Dark Fantasy"],
    "Horror": ["Horror", "Supernatural", "Gothic", "Occult"],
    "Biography & Memoir": ["Biography", "Memoir", "Autobiography", "Personal Memoirs"],
    "History": ["History", "Military History", "World History", "Ancient Civilizations"],
    "Self-Help & Wellness": ["Self-Help", "Motivation", "Mental Health", "Wellness", "Productivity"],
    "Business & Economics": ["Business", "Economics", "Finance", "Leadership", "Entrepreneurship"],
    "Science & Technology": ["Science", "Technology", "Physics", "Biology", "AI", "Engineering"],
    "Young Adult": ["Young Adult", "YA Romance", "YA Fantasy", "Coming of Age"],
    "Poetry": ["Poetry", "Verse", "Anthology", "Contemporary Poetry"],
    "Philosophy & Religion": ["Philosophy", "Religion", "Spirituality", "Theology", "Ethics"],
    "Education & Learning": ["Education", "Pedagogy", "Study Guides", "Teaching", "Academic Skills"],
    "Parenting & Relationships": ["Parenting", "Relationships", "Family", "Marriage", "Dating"],
    "Art & Design": ["Art", "Design", "Photography", "Architecture", "Graphic Design"],
    "Travel & Adventure": ["Travel", "Adventure", "Travel Guides", "Exploration", "Cultural Travel"],
    "Cooking & Food": ["Cooking", "Cookbooks", "Food", "Nutrition", "Culinary Arts"],
    "Politics & Society": ["Politics", "Sociology", "Current Affairs", "Social Issues", "Civic Engagement"],
    "Comics & Graphic Novels": ["Comics", "Graphic Novels", "Manga", "Webcomics"],
    "Children's Books": ["Children", "Picture Books", "Early Readers", "Middle Grade"]
}

def map_to_main_category(raw_category):
    if not raw_category:
        return "Other"
    raw = raw_category.lower()
    for main_cat, subcats in CATEGORY_GROUPS.items():
        if any(sub.lower() in raw for sub in subcats):
            return main_cat
    return "Other"

def group_books_by_category(user_books):
    grouped = defaultdict(list)
    for b in user_books:
        if b.categories:
            for raw_cat in b.categories.split(","):
                main_cat = map_to_main_category(raw_cat)
                grouped[main_cat].append(b)
    return grouped

def clean_text(text):
    return re.sub(r"[^\w\s]", "", text.strip().lower()) if text else ""

def build_user_profile(user_books, selected_categories=None):
    corpus = []
    for b in user_books:
        if not (b.author and b.categories and b.language):
            continue
        normalized = b.categories.split(",")
        if selected_categories:
            if not any(map_to_main_category(cat) in selected_categories for cat in normalized):
                continue
        enriched = " ".join([
            clean_text(b.title),
            clean_text(b.author),
            clean_text(",".join(normalized)),
            clean_text(b.language),
            clean_text(b.publisher),
            clean_text(clean_description(b.description))
        ])
        corpus.append(enriched)

    if not corpus:
        return None, None, None

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(corpus)
    profile_vector = np.asarray(tfidf_matrix.mean(axis=0)).flatten()

    hash_input = "".join(corpus) + "|".join(selected_categories or [])
    profile_hash = hashlib.md5(hash_input.encode("utf-8")).hexdigest()

    return profile_vector, vectorizer, profile_hash

def normalize_author(name):
    return re.sub(r"[^\w\s]", "", name.strip().lower())

def fetch_google_books(
    profile_vector,
    vectorizer,
    api_key,
    user_books,
    shown_ids=None,
    selected_categories=None,
    max_results=40,
    min_similarity=0.25
):
    if profile_vector is None:
        return []

    shown_ids = shown_ids or set()

    user_ids = {b.google_id.strip() for b in user_books if b.google_id}
    shown_ids.update(user_ids)

    seen_titles, seen_authors, seen_isbns = set(), set(), set()
    results = []

    categories_to_use = []
    for cat in selected_categories or ["Fiction"]:
        categories_to_use.extend(CATEGORY_GROUPS.get(cat, [cat]))

    def fetch_items(lang, query):
        params = {
            "q": f'subject:"{query}"',
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

    # Fetch Google Books
    items = []
    for query in categories_to_use:
        items += fetch_items("es", query)
        items += fetch_items("en", query)

    current_app.logger.info(f"[RECOMMEND] Libros recibidos antes de filtrar: {len(items)}")

    for item in items:
        volume = item.get("volumeInfo", {})
        gid = item.get("id", "").strip()

        # Exlude books that are already in the library or seen
        if gid in shown_ids:
            current_app.logger.debug(f"[RECOMMEND] Excluido por ID: {gid}")
            continue

        title = volume.get("title", "").strip().lower()
        authors = volume.get("authors", [])
        normalized_authors = [normalize_author(a) for a in authors]

        if title in seen_titles or any(a in seen_authors for a in normalized_authors):
            current_app.logger.debug(f"[RECOMMEND] Excluido por autor/título repetido: {title}")
            continue

        if not authors or not volume.get("description"):
            current_app.logger.debug(f"[RECOMMEND] Excluido por falta de autores o descripción: {gid}")
            continue

        raw_categories = volume.get("categories", [])
        mapped_categories = [map_to_main_category(cat) for cat in raw_categories]
        category = mapped_categories[0] if mapped_categories else ""

        language = volume.get("language", "")
        if language not in ("es", "en"):
            continue

        title_raw = volume.get("title", "")
        description = volume.get("description", "")
        publisher = volume.get("publisher", "")

        industry_ids = volume.get("industryIdentifiers", [])
        isbn = next((
            identifier.get("identifier").replace("-", "").strip()
            for identifier in industry_ids
            if identifier.get("type") in ("ISBN_13", "ISBN_10")
        ), None)
        if isbn and isbn in seen_isbns:
            continue

        enriched = " ".join([
            clean_text(title_raw),
            clean_text(" ".join(authors)),
            clean_text(category),
            clean_text(language),
            clean_text(publisher),
            clean_text(description)
        ])
        book_vector = vectorizer.transform([enriched])
        score = cosine_similarity([profile_vector], book_vector)[0][0]

        current_app.logger.debug(f"[RECOMMEND] Libro '{title_raw}' → similitud={score:.3f}")
        if score < min_similarity:
            continue

        result = {
            "google_id": gid,
            "id": gid,
            "title": title_raw,
            "author": ", ".join(authors),
            "authors": authors,
            "language": language,
            "thumbnail": volume.get("imageLinks", {}).get("thumbnail"),
            "categories": raw_categories,
            "description": description,
            "publisher": publisher,
            "publishedDate": volume.get("publishedDate", ""),
            "isbn": isbn,
            "similarity": round(score, 3)
        }

        results.append(result)
        shown_ids.add(gid)
        seen_titles.add(title)
        seen_authors.update(normalized_authors)
        if isbn:
            seen_isbns.add(isbn)

    results.sort(key=lambda x: x["similarity"], reverse=True)
    avg_score = np.mean([r["similarity"] for r in results]) if results else 0
    current_app.logger.info(f"[RECOMMEND] {len(results)} libros recomendados. Similitud promedio: {avg_score:.3f}")
    return results
