from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_session import Session
from app.extensions import db
from app.models import User, Book, Wishlist, UserLibrary
from config import Config 
from .extensions import mail

from app.routes import main_bp, auth, books_bp

login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')


    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = "flask_session_cache"
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_USE_SIGNER"] = True

    Session(app) 

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    mail.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(main_bp)
    app.register_blueprint(auth)
    app.register_blueprint(books_bp)

    
    app.logger.setLevel("INFO")
    return app