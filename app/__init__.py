from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
from app.extensions import db, mail
from app.models import User
from app.routes import main_bp, auth, books_bp
from config import Config

login_manager = LoginManager()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # CSRF protection
    csrf.init_app(app)

    # Session configuration
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = "flask_session_cache"
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_USE_SIGNER"] = True
    Session(app)

    # Extensions
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

    # Login configuration
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'error'
    login_manager.login_message = 'Debes iniciar sesión para acceder.'

    @login_manager.unauthorized_handler
    def handle_unauthorized():
        return redirect(url_for('auth.login'))

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth)
    app.register_blueprint(books_bp)

    # Logging
    app.logger.setLevel("INFO")

    return app
