import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from werkzeug.security import generate_password_hash

from .models import db, Employee, Track, User


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

    def normalize_database_url(raw_url):
        if not raw_url:
            return raw_url
        cleaned = (
            raw_url.replace("—", "-")
            .replace("–", "-")
            .replace("−", "-")
            .replace("\u2011", "-")
        )
        parts = urlsplit(cleaned)
        if not parts.hostname:
            return cleaned
        host = parts.hostname
        userinfo = ""
        if parts.username:
            userinfo = parts.username
            if parts.password:
                userinfo = f"{userinfo}:{parts.password}"
            userinfo = f"{userinfo}@"
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{userinfo}{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_url(
        os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:CarDatabase123!%40%23@srv-captain--carbookdb-db:3306/carbook",
    )
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

    def ensure_database_exists():
        db_url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        db_name = db_url.database
        if not db_name:
            raise RuntimeError("DATABASE_URL must include a database name")

        server_url = db_url.set(database=None)
        bootstrap_engine = create_engine(server_url)
        try:
            with bootstrap_engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE DATABASE IF NOT EXISTS `"
                        + db_name
                        + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
            app.logger.info("Ensured database '%s' exists on host '%s'.", db_name, db_url.host)
        finally:
            bootstrap_engine.dispose()

        db.engine.dispose()

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

    def ensure_schema_with_models():
        db.create_all()

        demo_track = Track.query.filter_by(name="Demo Speedway").first()
        if not demo_track:
            demo_track = Track(name="Demo Speedway", city="Austin", state="TX")
            db.session.add(demo_track)
            db.session.flush()

        demo_employee = Employee.query.filter_by(email="employee@track.local").first()
        if not demo_employee:
            demo_employee = Employee(
                track_id=demo_track.id,
                full_name="Demo Employee",
                email="employee@track.local",
                password_hash=generate_password_hash("ChangeMe123!"),
            )
            db.session.add(demo_employee)

        db.session.commit()

    with app.app_context():
        try:
            ensure_database_exists()
            try:
                run_init_sql_if_needed()
            except Exception:
                app.logger.exception("init.sql execution failed; falling back to ORM schema creation.")
            ensure_schema_with_models()
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
            try:
                ensure_database_exists()
                try:
                    run_init_sql_if_needed()
                except Exception:
                    current_app.logger.exception("init.sql recovery failed; using ORM fallback.")
                ensure_schema_with_models()
                inspector = inspect(db.engine)
                existing = set(inspector.get_table_names())
                g.schema_ready = required_tables.issubset(existing)
            except Exception as exc:
                current_app.logger.exception("Automatic DB recovery attempt failed: %s", exc)
            current_app.logger.warning(
                "Database schema missing. Automatic init is enabled; if it still fails, run your DB client with sql/init.sql manually."
            )

    return app
