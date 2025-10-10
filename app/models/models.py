from flask_login import UserMixin
from app.extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Association tables
wishlist_books = db.Table(
    'wishlist_books',
    db.Column('wishlist_id', db.Integer, db.ForeignKey('wishlists.id'), primary_key=True),
    db.Column('book_id', db.Integer, db.ForeignKey('books.id'), primary_key=True)
)

library_books = db.Table(
    'library_books',
    db.Column('library_id', db.Integer, db.ForeignKey('user_libraries.id'), primary_key=True),
    db.Column('book_id', db.Integer, db.ForeignKey('books.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=False)

    # Relaciones uno a uno
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
    author = db.Column(db.String(255))
    categories = db.Column(db.String(255)) 
    language = db.Column(db.String(50))
    isbn = db.Column(db.String(20), unique=True)
    thumbnail = db.Column(db.String(512))
    small_thumbnail = db.Column(db.String(512))
    description = db.Column(db.Text)
    publisher = db.Column(db.String(255))           
    published_date = db.Column(db.String(20))       
             

    wishlists = db.relationship('Wishlist', secondary=wishlist_books, back_populates='books')
    libraries = db.relationship('UserLibrary', secondary=library_books, back_populates='books')

    def __repr__(self):
        return f"<Book {self.title}>"

class Wishlist(db.Model):
    __tablename__ = 'wishlists'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', back_populates='wishlist')

    books = db.relationship('Book', secondary=wishlist_books, back_populates='wishlists')

    def __repr__(self):
        return f"<Wishlist User {self.user_id}>"

class UserLibrary(db.Model):
    __tablename__ = 'user_libraries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', back_populates='library')

    books = db.relationship('Book', secondary=library_books, back_populates='libraries')

    def __repr__(self):
        return f"<Library User {self.user_id}>"