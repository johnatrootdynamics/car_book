import os
from flask import Flask, redirect, url_for, request
from db.migrate import run_migrations_once, is_database_initialized
from db.connection import get_connection

def create_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {"ok": True, "initialized": is_database_initialized()}

    @app.route("/", methods=["GET"])
    def index():
        initialized = is_database_initialized()
        if not initialized:
            # First-time experience: show a button to build the DB
            return (
                "<html><head><title>Car History Setup</title></head><body>"
                "<h1>Welcome to Car History</h1>"
                "<p>It looks like this is your first time running the app.</p>"
                "<form method='post' action='/init'>"
                "<button type='submit'>Build DB</button>"
                "</form>"
                "</body></html>"
            )

        # DB initialized: show sample data
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT * FROM users LIMIT 5")
        users = cur.fetchall()

        cur.execute("SELECT * FROM vehicles LIMIT 5")
        vehicles = cur.fetchall()

        cur.execute("SELECT * FROM service_events ORDER BY created_at DESC LIMIT 5")
        service_events = cur.fetchall()

        cur.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 5")
        incidents = cur.fetchall()

        cur.execute("SELECT * FROM vehicle_scores LIMIT 5")
        scores = cur.fetchall()

        cur.close()
        conn.close()

        html_parts = []
        html_parts.append("<html><head><title>Car History Sample Data</title></head><body>")
        html_parts.append("<h1>Car History Sample Data</h1>")

        def section(title, rows):
            html_parts.append(f"<h2>{title}</h2>")
            if not rows:
                html_parts.append("<p><em>No data found.</em></p>")
                return
            html_parts.append("<pre>")
            for row in rows:
                html_parts.append(str(row))
                html_parts.append("\n")
            html_parts.append("</pre>")

        section("Users", users)
        section("Vehicles", vehicles)
        section("Service Events", service_events)
        section("Incidents", incidents)
        section("Vehicle Scores", scores)

        html_parts.append("</body></html>")
        return "".join(html_parts)

    @app.route("/init", methods=["POST"])
    def init_db():
        # Run migrations and seed data, then redirect back to index
        run_migrations_once()
        return redirect(url_for("index"))

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 80)))
