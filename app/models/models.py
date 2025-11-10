from flask_login import UserMixin
from app.extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Wishlist association model
class WishlistBook(db.Model):
    __tablename__ = 'wishlist_books'
    wishlist_id = db.Column(db.Integer, db.ForeignKey('wishlists.id'), primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), primary_key=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    wishlist = db.relationship('Wishlist', back_populates='wishlist_books')
    book = db.relationship('Book')


# Library association model with timestamp
class LibraryBook(db.Model):
    __tablename__ = 'library_books'
    library_id = db.Column(db.Integer, db.ForeignKey('user_libraries.id'), primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), primary_key=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    library = db.relationship('UserLibrary', back_populates='library_books')
    book = db.relationship('Book')


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # is_active = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)


    wishlist = db.relationship('Wishlist', back_populates='user', uselist=False)
    library = db.relationship('UserLibrary', back_populates='user', uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


class Book(db.Model):
    __tablename__ = 'books'

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(50), unique=True, nullable=False)

    title = db.Column(db.String(255), nullable=False)
    authors = db.Column(db.String(255))
    categories = db.Column(db.Text)
    language = db.Column(db.String(50))
    isbn = db.Column(db.String(20), nullable=True)
    thumbnail = db.Column(db.String(512))
    small_thumbnail = db.Column(db.String(512))
    description = db.Column(db.Text)
    publisher = db.Column(db.String(255))
    published_date = db.Column(db.String(20))

    wishlists = db.relationship('WishlistBook', back_populates='book', cascade="all, delete-orphan")
    library_books = db.relationship('LibraryBook', back_populates='book', cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Book {self.title}>"

    @property
    def authors_list(self):
        if not self.authors:
            return []
        return [a.strip() for a in self.authors.split(",")]

    @property
    def categories_list(self):
        if not self.categories:
            return []
        return [c.strip() for c in self.categories.split(",")]

    @property
    def categories_flat(self):
        if not self.categories:
            return []
        raw = self.categories.split(",") if isinstance(self.categories, str) else self.categories
        return [part.strip() for cat in raw for part in cat.split("/") if part.strip()]


class Wishlist(db.Model):
    __tablename__ = 'wishlists'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', back_populates='wishlist')

    wishlist_books = db.relationship('WishlistBook', back_populates='wishlist', cascade="all, delete-orphan")

    @property
    def books(self):
        return [wb.book for wb in sorted(self.wishlist_books, key=lambda wb: wb.added_at)]


class UserLibrary(db.Model):
    __tablename__ = 'user_libraries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', back_populates='library')

    library_books = db.relationship('LibraryBook', back_populates='library', cascade="all, delete-orphan")

    @property
    def books(self):
        return [lb.book for lb in sorted(self.library_books, key=lambda lb: lb.added_at)]
