from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from app.models import User
from app.extensions import db

bp = Blueprint('main', __name__)


@bp.route('/')
@login_required
def dashboard():
    return render_template('user/dashboard.html')

@bp.route('/scan')
@login_required
def scan():
    return render_template('user/scan.html')


@bp.route('/recommendations')
@login_required
def recommendations():
    return render_template('user/recommendations.html')