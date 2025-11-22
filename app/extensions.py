from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_caching import Cache
mail = Mail()

db = SQLAlchemy()
login_manager = LoginManager()
cache = Cache()