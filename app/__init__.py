from flask import Flask, redirect, url_for
from flask_login import LoginManager
from app.extensions import db
from app.models import User
from app.auth import auth  # Import your auth blueprint
from .routes import bp as main_bp
from config import Config  # Ensure you have a config.py with your configuration
from .extensions import mail

login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')  # Make sure you have a config.py file

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)



    # Configure login behavior
    login_manager.login_view = 'auth.login'

    mail.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth)
    


    return app