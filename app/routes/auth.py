from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, UserLibrary, Wishlist
from app.extensions import db, mail
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
import re
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter(
            (User.email == identifier) | (User.username == identifier)
        ).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash("Tu cuenta aún no está activada. Revisa tu correo.", "error")
                return redirect(url_for("auth.login"))

            login_user(user)
            return redirect(url_for('auth.dashboard'))
        else:
            flash("Usuario o contraseña incorrectos.", "error")
            return redirect(url_for("auth.login"))

    return render_template("auth/login.html")


@auth.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth.route("/")
@login_required
def dashboard():
    return render_template("user/dashboard.html", user=current_user)


@auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password_raw = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        # Basic validation
        if not username or not email or not password_raw or not confirm_password:
            flash("Todos los campos son obligatorios.", "error")
            return redirect(url_for("auth.register"))

        if password_raw != confirm_password:
            flash("Las contraseñas no coinciden.", "error")
            return redirect(url_for("auth.register"))

        if (
            len(password_raw) < 8
            or not re.search(r"[A-Z]", password_raw)
            or not re.search(r"[a-z]", password_raw)
            or not re.search(r"\d", password_raw)
        ):
            flash(
                "La contraseña debe tener al menos 8 caracteres, una mayúscula, una minúscula y un número.",
                "error",
            )
            return redirect(url_for("auth.register"))

        if User.query.filter_by(username=username).first():
            flash("Ese nombre de usuario ya está en uso.", "error")
            return redirect(url_for("auth.register"))

        if User.query.filter_by(email=email).first():
            flash("Ese correo ya está registrado.", "error")
            return redirect(url_for("auth.register"))

        # Create active user (activation disabled)
        password_hash = generate_password_hash(password_raw)
        user = User(
            username=username, email=email, password_hash=password_hash, is_active=True
        )
        db.session.add(user)
        db.session.commit()

        # Create user's wishlist & library automatically
        library = UserLibrary(user=user)
        wishlist = Wishlist(user=user)
        db.session.add_all([library, wishlist])
        db.session.commit()

        # Send welcome email instead of activation
        msg = Message(
            subject="Bienvenido a Smart Stack",
            recipients=[email],
            html=f"""
    <div style="font-family: Arial; padding: 20px;">
      <h2 style="color: #2b6cb0;">Hola {username},</h2>
      <p>Tu cuenta ha sido creada exitosamente en <strong>Smart Stack</strong>.</p>
      <p>Ya puedes iniciar sesión y comenzar a explorar recomendaciones personalizadas.</p>
      <a href="{url_for('auth.login', _external=True)}" style="display:inline-block; margin-top:20px; padding:10px 20px; background:#2b6cb0; color:white; text-decoration:none; border-radius:5px;">Ir a Smart Stack</a>
    </div>
    """,
        )

        mail.send(msg)

        # Optional: account activation logic (currently disabled)
        """
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = s.dumps(email, salt='email-confirm')
        activation_link = url_for('auth.activate_account', token=token, _external=True)

        msg = Message(
            subject="Activa tu cuenta en Smart Stack",
            recipients=[email],
            html=f'''
            <div style="font-family: Arial; padding: 20px;">
              <h2 style="color: #2b6cb0;">Hola {username},</h2>
              <p>Gracias por registrarte en <strong>Smart Stack</strong>.</p>
              <p>Para activar tu cuenta, haz clic en el siguiente botón:</p>
              <a href="{activation_link}" style="display:inline-block; margin-top:10px; padding:10px 20px; background:#2b6cb0; color:white; text-decoration:none; border-radius:5px;">Activar cuenta</a>
              <p style="margin-top:20px; font-size:0.9em;">Este enlace expirará en 24 horas.</p>
            </div>
            '''
        )
        mail.send(msg)
        """

        flash("Registro exitoso. Te enviamos un correo de bienvenida.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


# Optional: account activation route (currently unused)
@auth.route("/activate/<token>")
def activate_account(token):
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = s.loads(token, salt="email-confirm", max_age=86400)  # 24h
    except:
        flash("El enlace de activación es inválido o ha expirado.", "error")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(email=email).first()
    if user:
        user.is_active = True
        db.session.commit()
        flash("Cuenta activada correctamente. ¡Ya puedes iniciar sesión!", "success")
    else:
        flash("Usuario no encontrado.", "error")

    return redirect(url_for("auth.login"))


@auth.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email").strip()
        user = User.query.filter_by(email=email).first()

        if user:
            s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
            token = s.dumps(email, salt="password-reset")
            reset_link = url_for("auth.reset_password", token=token, _external=True)

            msg = Message(
                subject="Recupera tu contraseña - Smart Stack",
                recipients=[email],
                html=f"""
                <div style="font-family: Arial; padding: 20px;">
                  <h2 style="color: #2b6cb0;">Hola {user.username},</h2>
                  <p>Recibimos una solicitud para restablecer tu contraseña.</p>
                  <p>Haz clic en el siguiente botón para continuar:</p>
                  <a href="{reset_link}" style="display:inline-block; margin-top:10px; padding:10px 20px; background:#2b6cb0; color:white; text-decoration:none; border-radius:5px;">Restablecer contraseña</a>
                  <p style="margin-top:20px; font-size:0.9em;">Si no solicitaste esto, puedes ignorar este mensaje.</p>
                </div>
                """,
            )
            mail.send(msg)
            flash(
                "Te enviamos un correo con instrucciones para recuperar tu contraseña.",
                "success",
            )
        else:
            flash("No encontramos una cuenta con ese correo.", "error")

        return redirect(url_for("auth.forgot_password"))

    return render_template("auth/forgot_password.html")


@auth.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])

    try:
        email = s.loads(
            token, salt="password-reset", max_age=3600
        )  # Token valid for 1 hour
    except:
        flash("El enlace ha expirado o es inválido.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        # Validation: passwords match
        if new_password != confirm_password:
            flash("Las contraseñas no coinciden.", "error")
            return redirect(url_for("auth.reset_password", token=token))

        # Validation: password meets minimum requirements
        if (
            len(new_password) < 8
            or not re.search(r"[A-Z]", new_password)
            or not re.search(r"[a-z]", new_password)
            or not re.search(r"\d", new_password)
        ):
            flash(
                "La contraseña debe tener al menos 8 caracteres, una mayúscula, una minúscula y un número.",
                "error",
            )
            return redirect(url_for("auth.reset_password", token=token))

            # Do not repeat the current password
        if check_password_hash(user.password_hash, new_password):
            flash("La nueva contraseña no puede ser igual a la actual.", "error")
            return redirect(url_for("auth.reset_password", token=token))

        # Update password
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()

        flash("Tu contraseña ha sido actualizada. Ya puedes iniciar sesión.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
