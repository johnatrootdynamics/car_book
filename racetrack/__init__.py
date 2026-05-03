import os
from pathlib import Path

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
        "mysql+pymysql://racetrack:CarDatabase123!%40%23@srv-captain—carbpokdb-db:3306/srv-captain--carbookdb-db",
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

    def run_init_sql_if_needed():
        required_tables = {
            "users",
            "cars",
            "tracks",
            "employees",
            "events",
            "event_registrations",
        }
        inspector = inspect(db.engine)
        existing = set(inspector.get_table_names())
        if required_tables.issubset(existing):
            app.logger.info("Database schema already present.")
            return

        init_sql_path = (Path(app.root_path).parent / "sql" / "init.sql").resolve()
        if not init_sql_path.exists():
            app.logger.error("Schema missing and init.sql not found at %s", init_sql_path)
            return

        app.logger.warning("Schema missing; attempting automatic initialization from %s", init_sql_path)

        raw_sql = init_sql_path.read_text(encoding="utf-8")
        lines = []
        for line in raw_sql.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            lines.append(line)
        statements = [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]

        with db.engine.begin() as conn:
            for statement in statements:
                conn.exec_driver_sql(statement)

        inspector = inspect(db.engine)
        existing = set(inspector.get_table_names())
        if required_tables.issubset(existing):
            app.logger.info("Schema initialized successfully from init.sql.")
        else:
            app.logger.error("Schema initialization ran but required tables are still missing.")

    with app.app_context():
        try:
            run_init_sql_if_needed()
        except Exception as exc:
            app.logger.exception("Automatic schema initialization failed: %s", exc)

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
                "Database schema missing. Automatic init is enabled; if it still fails, run your DB client with sql/init.sql manually."
            )

    return app
