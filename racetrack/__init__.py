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

from .models import db, Employee, EnterpriseAdmin, Track, User
from .services.storage_service import build_presigned_read_url


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
    if user_type == "admin":
        return EnterpriseAdmin.query.get(object_id)
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
    app.config["APP_BASE_URL"] = os.getenv("APP_BASE_URL", "")
    app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_url(
        os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:CarDatabase123!%40%23@srv-captain--carbookdb-db:3306/carbook",
    )
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["S3_ENDPOINT_URL"] = os.getenv("S3_ENDPOINT_URL", "https://s3.root-dynamics.com")
    app.config["S3_API_ENDPOINT_URL"] = os.getenv(
        "S3_API_ENDPOINT_URL", "https://s3-api.root-dynamics.com"
    )
    app.config["S3_BUCKET"] = os.getenv("S3_BUCKET", "trackops")
    app.config["S3_ACCESS_KEY"] = (
        os.getenv("S3_ACCESS_KEY")
        or os.getenv("S3_USERNAME")
        or os.getenv("MINIO_ACCESS_KEY")
        or os.getenv("MINIO_ROOT_USER")
        or ""
    )
    app.config["S3_SECRET_KEY"] = (
        os.getenv("S3_SECRET_KEY")
        or os.getenv("S3_PASSWORD")
        or os.getenv("MINIO_SECRET_KEY")
        or os.getenv("MINIO_ROOT_PASSWORD")
        or ""
    )
    app.config["S3_READ_ACCESS_KEY"] = (
        os.getenv("S3_READ_ACCESS_KEY")
        or os.getenv("S3_READ_USERNAME")
        or os.getenv("MINIO_READ_ACCESS_KEY")
        or ""
    )
    app.config["S3_READ_SECRET_KEY"] = (
        os.getenv("S3_READ_SECRET_KEY")
        or os.getenv("S3_READ_PASSWORD")
        or os.getenv("MINIO_READ_SECRET_KEY")
        or ""
    )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .admin_routes import admin_bp
    from .auth import auth_bp
    from .employee_routes import employee_bp
    from .user_routes import user_bp
    from .waiver_routes import waiver_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(waiver_bp)
    csrf.exempt(app.view_functions["waiver.boldsign_webhook"])

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
            "inspection_rules",
            "inspections",
            "inspection_items",
            "enterprise_admins",
            "social_posts",
            "social_comments",
            "community_groups",
            "community_group_members",
            "track_subscriptions",
            "track_driver_classes",
            "run_groups",
            "run_group_assignments",
            "event_class_slots",
            "spectator_ticket_orders",
            "spectator_ticket_types",
            "spectator_carts",
            "spectator_cart_items",
            "spectator_orders",
            "spectator_order_items",
            "track_layouts",
            "track_waiver_templates",
            "driver_waivers",
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

        with db.engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE event_registrations ADD COLUMN IF NOT EXISTS checkin_code VARCHAR(64) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS static_qr_code VARCHAR(64) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE cars ADD COLUMN IF NOT EXISTS static_qr_code VARCHAR(64) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE cars ADD COLUMN IF NOT EXISTS image_url VARCHAR(500) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS thumbnail_image_path VARCHAR(255) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_start_time TIME NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_end_time TIME NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS driver_price_cents INT NOT NULL DEFAULT 0"
            )
            conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS spectator_price_cents INT NOT NULL DEFAULT 2500"
            )
            conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS track_layout_id INT NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS spectator_payment_provider VARCHAR(50) NOT NULL DEFAULT 'stripe'"
            )
            conn.exec_driver_sql(
                "ALTER TABLE spectator_order_items ADD COLUMN IF NOT EXISTS checked_in_at DATETIME NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE spectator_order_items ADD COLUMN IF NOT EXISTS checked_in_by_employee_id INT NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE spectator_orders ADD COLUMN IF NOT EXISTS guest_phone VARCHAR(30) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE spectator_ticket_orders ADD COLUMN IF NOT EXISTS guest_phone VARCHAR(30) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(50) NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS driver_class CHAR(1) NOT NULL DEFAULT 'C'"
            )
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_image_url VARCHAR(500) NULL"
            )

        with db.engine.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE users SET username = LOWER(SUBSTRING_INDEX(email, '@', 1)) WHERE username IS NULL OR username = ''"
            )
            conn.exec_driver_sql(
                "UPDATE users SET driver_class = 'C' WHERE driver_class IS NULL OR driver_class NOT IN ('A','B','C')"
            )
            conn.exec_driver_sql(
                "UPDATE track_driver_classes SET driver_class = 'C' WHERE driver_class IS NULL OR driver_class NOT IN ('A','B','C')"
            )
            conn.exec_driver_sql(
                "INSERT IGNORE INTO track_driver_classes (track_id, user_id, driver_class, created_at, updated_at) SELECT DISTINCT e.track_id, er.user_id, CASE WHEN u.driver_class IN ('A','B','C') THEN u.driver_class ELSE 'C' END, NOW(), NOW() FROM event_registrations er JOIN events e ON e.id = er.event_id JOIN users u ON u.id = er.user_id"
            )
            conn.exec_driver_sql(
                "INSERT IGNORE INTO track_driver_classes (track_id, user_id, driver_class, created_at, updated_at) SELECT ts.track_id, ts.user_id, CASE WHEN u.driver_class IN ('A','B','C') THEN u.driver_class ELSE 'C' END, NOW(), NOW() FROM track_subscriptions ts JOIN users u ON u.id = ts.user_id"
            )
            conn.exec_driver_sql(
                "UPDATE users u JOIN (SELECT id, CONCAT(LOWER(SUBSTRING_INDEX(email, '@', 1)), '-', id) AS fallback_username FROM users) x ON x.id = u.id SET u.username = x.fallback_username WHERE u.username IN (SELECT t.username FROM (SELECT username FROM users GROUP BY username HAVING COUNT(*) > 1) t)"
            )
            conn.exec_driver_sql(
                "UPDATE users SET static_qr_code = CONCAT('DRV-', UPPER(SUBSTRING(MD5(CONCAT(id, email)), 1, 8))) WHERE static_qr_code IS NULL OR static_qr_code = ''"
            )
            conn.exec_driver_sql(
                "UPDATE cars SET static_qr_code = CONCAT('CAR-', UPPER(SUBSTRING(MD5(CONCAT(id, user_id, make, model, car_year)), 1, 8))) WHERE static_qr_code IS NULL OR static_qr_code = ''"
            )
            conn.exec_driver_sql(
                "UPDATE event_registrations er JOIN cars c ON c.id = er.car_id SET er.checkin_code = c.static_qr_code WHERE er.checkin_code IS NULL OR er.checkin_code = ''"
            )

        with db.engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE event_registrations MODIFY COLUMN checkin_code VARCHAR(64) NOT NULL"
            )
            try:
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX idx_users_static_qr_code ON users (static_qr_code)"
                )
            except Exception:
                pass
            try:
                conn.exec_driver_sql("CREATE UNIQUE INDEX idx_users_username ON users (username)")
            except Exception:
                pass
            try:
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX idx_cars_static_qr_code ON cars (static_qr_code)"
                )
            except Exception:
                pass
            try:
                conn.exec_driver_sql("DROP INDEX idx_event_registrations_checkin_code ON event_registrations")
            except Exception:
                pass
            try:
                conn.exec_driver_sql(
                    "CREATE INDEX idx_event_registrations_checkin_code ON event_registrations (checkin_code)"
                )
            except Exception:
                pass

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

        demo_admin = EnterpriseAdmin.query.filter_by(email="admin@enterprise.local").first()
        if not demo_admin:
            demo_admin = EnterpriseAdmin(
                full_name="Enterprise Admin",
                email="admin@enterprise.local",
                password_hash=generate_password_hash("ChangeMe123!"),
            )
            db.session.add(demo_admin)

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
        from flask import url_for

        def asset_url(stored_value):
            if not stored_value:
                return None
            if stored_value.startswith("uploads/"):
                return url_for("static", filename=stored_value)
            read_key = app.config.get("S3_READ_ACCESS_KEY")
            read_secret = app.config.get("S3_READ_SECRET_KEY")
            if read_key and read_secret:
                return build_presigned_read_url(
                    stored_value,
                    bucket=app.config["S3_BUCKET"],
                    endpoint_url=app.config["S3_API_ENDPOINT_URL"],
                    access_key=read_key,
                    secret_key=read_secret,
                )
            return None

        return {
            "is_user": getattr(current_user, "account_type", None) == "user",
            "is_employee": getattr(current_user, "account_type", None) == "employee",
            "is_admin": getattr(current_user, "account_type", None) == "admin",
            "asset_url": asset_url,
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
            "inspection_rules",
            "inspections",
            "inspection_items",
            "enterprise_admins",
            "social_posts",
            "social_comments",
            "community_groups",
            "community_group_members",
            "track_subscriptions",
            "track_driver_classes",
            "run_groups",
            "run_group_assignments",
            "event_class_slots",
            "spectator_ticket_orders",
            "spectator_ticket_types",
            "spectator_carts",
            "spectator_cart_items",
            "spectator_orders",
            "spectator_order_items",
            "track_layouts",
            "track_waiver_templates",
            "driver_waivers",
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
