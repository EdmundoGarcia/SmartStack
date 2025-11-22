import os
from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
from redis import Redis

from app.extensions import db, mail, cache
from app.models import User
from app.routes import main_bp, auth, books_bp
from config import Config

login_manager = LoginManager()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    csrf.init_app(app)

    app.config["SESSION_TYPE"] = "redis"
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_KEY_PREFIX"] = "smartstack:"
    app.config["SESSION_REDIS"] = Redis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        password=Config.REDIS_PASSWORD if Config.REDIS_PASSWORD else None
    )
    Session(app)

    app.config["CACHE_TYPE"] = Config.CACHE_TYPE
    app.config["CACHE_REDIS_HOST"] = Config.REDIS_HOST
    app.config["CACHE_REDIS_PORT"] = Config.REDIS_PORT
    if Config.REDIS_PASSWORD:
        app.config["CACHE_REDIS_PASSWORD"] = Config.REDIS_PASSWORD
    app.config["CACHE_DEFAULT_TIMEOUT"] = Config.CACHE_DEFAULT_TIMEOUT
    cache.init_app(app)

    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "error"
    login_manager.login_message = "Debes iniciar sesión para acceder."

    @login_manager.unauthorized_handler
    def handle_unauthorized():
        return redirect(url_for("auth.login"))

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(main_bp)
    app.register_blueprint(auth)
    app.register_blueprint(books_bp)

    app.logger.setLevel("INFO")

    return app
