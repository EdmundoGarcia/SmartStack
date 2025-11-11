from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.extensions import db

bp = Blueprint("main", __name__)

@bp.route("/")
def landing():
    if current_user.is_authenticated:
        return render_template("user/dashboard.html")
    return render_template("main/landing.html")
