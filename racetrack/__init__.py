import os

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from sqlalchemy import inspect

from .models import db, Employee, User


login_manager = LoginManager()
login_manager.login_view = "auth.user_login"
csrf = CSRFProtect()


@login_manager.user_loader
def load_user(user_id):
    if not user_id or ":" not in user_id:
        return None
    user_type, raw_id = user_id.split(":", 1)
    if not raw_id.isdigit():
        return None
    object_id = int(raw_id)
    if user_type == "user":
        return User.query.get(object_id)
    if user_type == "employee":
        return Employee.query.get(object_id)
    return None


def create_app():
    load_dotenv()
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://racetrack:racetrack@127.0.0.1:3306/racetrack",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads", "tracks")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth import auth_bp
    from .employee_routes import employee_bp
    from .user_routes import user_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(employee_bp)

    @app.context_processor
    def inject_roles():
        from flask_login import current_user

        return {
            "is_user": getattr(current_user, "account_type", None) == "user",
            "is_employee": getattr(current_user, "account_type", None) == "employee",
        }

    @app.before_request
    def schema_health_check():
        from flask import current_app, g

        if getattr(g, "_schema_checked", False):
            return
        g._schema_checked = True
        required_tables = {
            "users",
            "cars",
            "tracks",
            "employees",
            "events",
            "event_registrations",
        }
        try:
            inspector = inspect(db.engine)
            existing = set(inspector.get_table_names())
            g.schema_ready = required_tables.issubset(existing)
        except Exception:
            g.schema_ready = False
        if not g.schema_ready:
            current_app.logger.warning(
                "Database schema missing. Run: mysql -u <user> -p racetrack < sql/init.sql"
            )

    return app
