import requests
import numpy as np
import hashlib
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from flask import current_app
from collections import defaultdict
from app.utils.books import clean_description, normalize_categories

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
            for raw_cat in normalize_categories(b.categories.split(",")):
                main_cat = map_to_main_category(raw_cat)
                grouped[main_cat].append(b)
    return grouped

def clean_text(text):
    return re.sub(r"[^\w\s]", "", text.strip().lower()) if text else ""

def build_user_profile(user_books, selected_categories=None):
    corpus = []
    for b in user_books:
        if not (b.authors and b.categories and b.language):
            continue
        normalized = normalize_categories(b.categories.split(","))
        if selected_categories:
            if not any(map_to_main_category(cat) in selected_categories for cat in normalized):
                continue
        enriched = " ".join([
            clean_text(b.title),
            clean_text(b.authors),
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
    if profile_vector is None or not selected_categories:
        return []

    shown_ids = shown_ids or set()
    user_ids = {b.google_id.strip() for b in user_books if b.google_id}
    shown_ids.update(user_ids)

    seen_keys, seen_isbns = set(), set()
    results = []

    categories_to_use = []
    for cat in selected_categories:
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

    items = []
    for query in categories_to_use:
        items += fetch_items("es", query)
        items += fetch_items("en", query)

    current_app.logger.info(f"[RECOMMEND] Libros recibidos antes de filtrar: {len(items)}")

    for item in items:
        volume = item.get("volumeInfo", {})
        gid = item.get("id", "").strip()

        if gid in shown_ids:
            continue

        title_raw = volume.get("title", "").strip()
        title = title_raw.lower()
        authors = volume.get("authors", [])
        normalized_authors = [normalize_author(a) for a in authors]
        title_author_key = f"{title}|{'|'.join(normalized_authors)}"

        if title_author_key in seen_keys:
            continue

        description = volume.get("description", "")
        if not authors or not description:
            continue

        raw_categories = volume.get("categories", [])
        normalized_categories = normalize_categories(raw_categories)
        mapped_categories = [map_to_main_category(cat) for cat in normalized_categories]

        if not any(cat in selected_categories for cat in mapped_categories):
            continue

        language = volume.get("language", "")
        if language not in ("es", "en"):
            continue

        publisher_raw = volume.get("publisher")
        publisher = publisher_raw.strip() if isinstance(publisher_raw, str) and publisher_raw.strip() else "No disponible"
        if publisher == "No disponible":
            current_app.logger.warning(f"[RECOMMEND] Libro sin editorial: {title_raw} ({gid})")

        description_raw = volume.get("description")
        description = description_raw.strip() if isinstance(description_raw, str) and description_raw.strip() else ""
        if not description:
            current_app.logger.warning(f"[RECOMMEND] Libro sin descripción: {title_raw} ({gid})")


        industry_ids = volume.get("industryIdentifiers", [])
        isbn = next((
            identifier.get("identifier", "").replace("-", "").strip()
            for identifier in industry_ids
            if identifier.get("type") in ("ISBN_13", "ISBN_10")
        ), None)
        if isbn and isbn in seen_isbns:
            continue

        enriched = " ".join([
            clean_text(title_raw),
            clean_text(" ".join(authors)),
            clean_text(",".join(mapped_categories)),
            clean_text(language),
            clean_text(publisher),
            clean_text(description)
        ])
        book_vector = vectorizer.transform([enriched])
        score = cosine_similarity([profile_vector], book_vector)[0][0]

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
            "similarity": round(score, 3),
            "matched_category": mapped_categories[0] if mapped_categories else "",
            "matched_terms": [cat for cat in mapped_categories if cat in selected_categories]
        }

        results.append(result)
        shown_ids.add(gid)
        seen_keys.add(title_author_key)
        if isbn:
            seen_isbns.add(isbn)

    results.sort(key=lambda x: x["similarity"], reverse=True)
    avg_score = np.mean([r["similarity"] for r in results]) if results else 0
    current_app.logger.info(f"[RECOMMEND] {len(results)} libros recomendados. Similitud promedio: {avg_score:.3f}")
    return results
