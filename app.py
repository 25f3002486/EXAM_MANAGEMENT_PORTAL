import os

from flask import Flask, redirect, url_for
from flask_login import LoginManager, current_user

from models import db, User

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

ADMIN_EMAIL = "admin@emp.com"
ADMIN_PASSWORD = "admin123"


# Build and configure the Flask application
def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("EMP_SECRET_KEY", "emp-dev-secret-key-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "emp.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # Load a user by ID for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from routes.auth import bp as auth_bp
    from routes.admin import bp as admin_bp
    from routes.examiner import bp as examiner_bp
    from routes.student import bp as student_bp
    from routes.api import bp as api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(examiner_bp, url_prefix="/examiner")
    app.register_blueprint(student_bp, url_prefix="/student")
    app.register_blueprint(api_bp, url_prefix="/api")

    # Redirect to role dashboard or login page
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for(f"{current_user.role}.dashboard"))
        return redirect(url_for("auth.login"))

    # Map a status to a Bootstrap badge colour
    @app.template_filter("badge")
    def badge(status):
        return {
            "Active": "success", "Available": "success", "Booked": "primary",
            "Booking Open": "success", "Slot Creation": "info", "Draft": "secondary",
            "Closed": "dark", "Completed": "secondary", "Full": "warning",
            "Pending": "warning", "Inactive": "danger", "Cancelled": "danger",
        }.get(status, "secondary")

    with app.app_context():
        db.create_all()
        seed_admin()

    return app


# Create the default admin account if missing
def seed_admin():
    if not User.query.filter_by(role="admin").first():
        admin = User(role="admin", name="Administrator", email=ADMIN_EMAIL, status="Active")
        admin.set_password(ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
