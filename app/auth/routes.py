from datetime import date
import re
from secrets import token_hex
from urllib.parse import urlsplit

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from app.auth import bp
from app.extensions import db
from app.models import Patient, User

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.active and user.check_password(password):
            login_user(user, remember=request.form.get("remember") == "on")
            next_url = request.args.get("next", "")
            parsed_next = urlsplit(next_url)
            if (
                next_url.startswith("/")
                and not next_url.startswith("//")
                and "\\" not in next_url
                and not parsed_next.scheme
                and not parsed_next.netloc
            ):
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))
        flash("Email or password is incorrect.", "danger")
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        gender = request.form.get("gender") or None
        address = request.form.get("address", "").strip()
        dob_value = request.form.get("date_of_birth", "")
        if (
            not name or len(name) > 120 or len(email) > 190
            or not EMAIL_PATTERN.fullmatch(email)
        ):
            flash("Enter a name and a valid email address.", "danger")
            return render_template("auth/register.html", today=date.today().isoformat())
        if len(password) < 12:
            flash("Use a password with at least 12 characters.", "danger")
            return render_template("auth/register.html")
        if len(phone) > 30 or len(address) > 255:
            flash("Phone or address is too long.", "danger")
            return render_template("auth/register.html")
        if gender and gender not in {"Female", "Male", "Non-binary", "Other"}:
            flash("Select a valid gender option.", "danger")
            return render_template("auth/register.html")
        dob = None
        if dob_value:
            try:
                dob = date.fromisoformat(dob_value)
                if dob > date.today():
                    raise ValueError
            except ValueError:
                flash("Enter a valid date of birth.", "danger")
                return render_template("auth/register.html")
        try:
            user = User(name=name, email=email, role="patient")
            user.set_password(password)
            patient = Patient(
                user=user,
                mrn=f"PT-{token_hex(6).upper()}",
                phone=phone or None,
                date_of_birth=dob,
                gender=gender,
                address=address or None,
            )
            db.session.add_all([user, patient])
            db.session.commit()
            login_user(user)
            flash("Your patient account is ready.", "success")
            return redirect(url_for("main.dashboard"))
        except IntegrityError:
            db.session.rollback()
            flash("That email address is already registered.", "danger")
    return render_template("auth/register.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
