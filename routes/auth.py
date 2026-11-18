from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import db, User

bp = Blueprint("auth", __name__)


# Authenticate a user and start their session
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
        elif user.status == "Inactive":
            flash("Your account has been deactivated. Contact the administrator.", "danger")
        else:
            login_user(user)
            flash(f"Welcome, {user.name}!", "success")
            if user.status == "Pending":
                return redirect(url_for("auth.pending"))
            return redirect(url_for("index"))
    return render_template("auth/login.html")


# Register a new student or examiner account
@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    role = request.args.get("role", request.form.get("role", "student"))
    if role not in ("student", "examiner"):
        role = "student"
    if request.method == "POST":
        f = request.form
        name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
        password, confirm = f.get("password", ""), f.get("confirm", "")
        errors = []
        if not name or not email:
            errors.append("Name and email are required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")
        roll_no = f.get("roll_no", "").strip() or None
        if role == "student":
            if not roll_no:
                errors.append("Roll number is required.")
            elif User.query.filter_by(roll_no=roll_no).first():
                errors.append("This roll number is already registered.")
        if role == "examiner" and not f.get("department", "").strip():
            errors.append("Department is required.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("auth/register.html", role=role, form=f)

        user = User(role=role, name=name, email=email, phone=f.get("phone", "").strip(),
                    status="Pending" if role == "examiner" else "Active")
        if role == "examiner":
            user.department = f.get("department", "").strip()
            user.designation = f.get("designation", "").strip()
        else:
            user.roll_no = roll_no
            user.program = f.get("program", "").strip()
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        if role == "examiner":
            flash("Registration submitted. You can access the dashboard once the admin approves your account.", "info")
        else:
            flash("Registration successful. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", role=role, form={})


# Show the awaiting-approval page to pending examiners
@bp.route("/pending")
@login_required
def pending():
    if current_user.status != "Pending":
        return redirect(url_for("index"))
    return render_template("auth/pending.html")


# Log out the current user
@bp.route("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# View and update the current user's profile
@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        f = request.form
        current_user.name = f.get("name", current_user.name).strip() or current_user.name
        current_user.phone = f.get("phone", "").strip()
        if current_user.role == "examiner":
            current_user.department = f.get("department", "").strip()
            current_user.designation = f.get("designation", "").strip()
        elif current_user.role == "student":
            current_user.program = f.get("program", "").strip()
        new_pw = f.get("new_password", "")
        if new_pw:
            if not current_user.check_password(f.get("current_password", "")):
                flash("Current password is incorrect; password not changed.", "danger")
                return redirect(url_for("auth.profile"))
            if len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "danger")
                return redirect(url_for("auth.profile"))
            current_user.set_password(new_pw)
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html")
