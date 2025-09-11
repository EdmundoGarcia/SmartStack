from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from .models import User
from app.extensions import db

bp = Blueprint('main', __name__)


@bp.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')

@bp.route('/scan')
@login_required
def scan():
    return render_template('scan.html')

@bp.route('/library')
@login_required
def library():
    return render_template('library.html')

@bp.route('/recommendations')
@login_required
def recommendations():
    return render_template('recommendations.html')