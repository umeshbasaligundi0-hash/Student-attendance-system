import base64
import csv
import io
import os
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import qrcode
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

csrf = CSRFProtect()


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def timestamp(value):
    return value.isoformat(timespec="seconds")


def make_code(length=6):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-this-key"),
        DATABASE=os.path.join(app.instance_path, "attendance.sqlite3"),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    csrf.init_app(app)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        get_db().executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('teacher', 'student')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subject TEXT NOT NULL,
                join_code TEXT NOT NULL UNIQUE,
                teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS enrollments (
                course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                enrolled_at TEXT NOT NULL,
                PRIMARY KEY (course_id, student_id)
            );
            CREATE TABLE IF NOT EXISTS attendance_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                token TEXT NOT NULL UNIQUE,
                attendance_code TEXT NOT NULL UNIQUE,
                starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                marked_at TEXT NOT NULL,
                UNIQUE (session_id, student_id)
            );
            """
        )
        get_db().commit()

    with app.app_context():
        init_db()

    def current_user():
        user_id = session.get("user_id")
        if user_id is None:
            return None
        return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def login_required(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if current_user() is None:
                flash("Please sign in to continue.", "error")
                return redirect(url_for("login"))
            return view(**kwargs)

        return wrapped_view

    def role_required(role):
        def decorate(view):
            @wraps(view)
            def wrapped_view(**kwargs):
                user = current_user()
                if user is None:
                    flash("Please sign in to continue.", "error")
                    return redirect(url_for("login"))
                if user["role"] != role:
                    abort(403)
                return view(**kwargs)

            return wrapped_view

        return decorate

    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    @app.route("/")
    def index():
        if current_user():
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            role = request.form.get("role", "student")
            if not name or len(name) > 100 or "@" not in email:
                flash("Enter your name and a valid email address.", "error")
            elif len(password) < 8:
                flash("Use a password with at least 8 characters.", "error")
            elif role not in ("student", "teacher"):
                flash("Choose a valid account type.", "error")
            else:
                try:
                    cursor = get_db().execute(
                        "INSERT INTO users (name, email, password_hash, role, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (name, email, generate_password_hash(password), role, timestamp(now_utc())),
                    )
                    get_db().commit()
                except sqlite3.IntegrityError:
                    flash("An account with that email already exists.", "error")
                else:
                    session.clear()
                    session["user_id"] = cursor.lastrowid
                    flash("Your account is ready.", "success")
                    return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("Email or password is incorrect.", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        user = current_user()
        db = get_db()
        if user["role"] == "teacher":
            courses = db.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.id) "
                "AS student_count FROM courses c WHERE c.teacher_id = ? ORDER BY c.created_at DESC",
                (user["id"],),
            ).fetchall()
        else:
            courses = db.execute(
                "SELECT c.*, u.name AS teacher_name FROM courses c "
                "JOIN enrollments e ON e.course_id = c.id "
                "JOIN users u ON u.id = c.teacher_id WHERE e.student_id = ? ORDER BY c.title",
                (user["id"],),
            ).fetchall()
        return render_template("dashboard.html", courses=courses)

    @app.route("/courses/create", methods=["POST"])
    @role_required("teacher")
    def create_course():
        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        if not title or not subject:
            flash("Course title and subject are required.", "error")
            return redirect(url_for("dashboard"))
        join_code = make_code(8)
        cursor = get_db().execute(
            "INSERT INTO courses (title, subject, join_code, teacher_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (title[:100], subject[:100], join_code, current_user()["id"], timestamp(now_utc())),
        )
        get_db().commit()
        flash(f"Course created. Share join code {join_code} with your students.", "success")
        return redirect(url_for("course_detail", course_id=cursor.lastrowid))

    @app.route("/courses/join", methods=["POST"])
    @role_required("student")
    def join_course():
        join_code = request.form.get("join_code", "").strip().upper()
        course = get_db().execute("SELECT id FROM courses WHERE join_code = ?", (join_code,)).fetchone()
        if course is None:
            flash("That course join code was not found.", "error")
        else:
            try:
                get_db().execute(
                    "INSERT INTO enrollments (course_id, student_id, enrolled_at) VALUES (?, ?, ?)",
                    (course["id"], current_user()["id"], timestamp(now_utc())),
                )
                get_db().commit()
                flash("You joined the course.", "success")
            except sqlite3.IntegrityError:
                flash("You are already enrolled in that course.", "error")
            return redirect(url_for("course_detail", course_id=course["id"]))
        return redirect(url_for("dashboard"))

    def course_for_user(course_id):
        user = current_user()
        db = get_db()
        course = db.execute(
            "SELECT c.*, u.name AS teacher_name FROM courses c "
            "JOIN users u ON u.id = c.teacher_id WHERE c.id = ?",
            (course_id,),
        ).fetchone()
        if course is None:
            abort(404)
        if user["role"] == "teacher" and course["teacher_id"] != user["id"]:
            abort(403)
        if user["role"] == "student":
            enrolled = db.execute(
                "SELECT 1 FROM enrollments WHERE course_id = ? AND student_id = ?",
                (course_id, user["id"]),
            ).fetchone()
            if enrolled is None:
                abort(403)
        return course

    @app.route("/courses/<int:course_id>")
    @login_required
    def course_detail(course_id):
        course = course_for_user(course_id)
        user = current_user()
        db = get_db()
        if user["role"] == "teacher":
            sessions = db.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM attendance a WHERE a.session_id = s.id) "
                "AS attendance_count FROM attendance_sessions s WHERE s.course_id = ? "
                "ORDER BY s.starts_at DESC",
                (course_id,),
            ).fetchall()
        else:
            sessions = db.execute(
                "SELECT s.*, a.marked_at FROM attendance_sessions s "
                "LEFT JOIN attendance a ON a.session_id = s.id AND a.student_id = ? "
                "WHERE s.course_id = ? ORDER BY s.starts_at DESC",
                (user["id"], course_id),
            ).fetchall()
        return render_template("course.html", course=course, sessions=sessions)

    @app.route("/courses/<int:course_id>/sessions", methods=["POST"])
    @role_required("teacher")
    def create_session(course_id):
        course = course_for_user(course_id)
        try:
            duration = int(request.form.get("duration", "60"))
        except ValueError:
            duration = 0
        if not 1 <= duration <= 180:
            flash("Choose a session duration from 1 to 180 minutes.", "error")
            return redirect(url_for("course_detail", course_id=course_id))
        start = now_utc()
        cursor = get_db().execute(
            "INSERT INTO attendance_sessions "
            "(course_id, token, attendance_code, starts_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                course["id"],
                secrets.token_urlsafe(24),
                make_code(),
                timestamp(start),
                timestamp(start + timedelta(minutes=duration)),
            ),
        )
        get_db().commit()
        flash("Attendance session opened.", "success")
        return redirect(url_for("session_detail", session_id=cursor.lastrowid))

    @app.route("/sessions/<int:session_id>")
    @login_required
    def session_detail(session_id):
        user = current_user()
        record = get_db().execute(
            "SELECT s.*, c.title AS course_title, c.teacher_id FROM attendance_sessions s "
            "JOIN courses c ON c.id = s.course_id WHERE s.id = ?",
            (session_id,),
        ).fetchone()
        if record is None:
            abort(404)
        if user["role"] != "teacher" or record["teacher_id"] != user["id"]:
            abort(403)
        attendance_url = url_for("mark_attendance", token=record["token"], _external=True)
        qr = qrcode.make(attendance_url)
        image_buffer = io.BytesIO()
        qr.save(image_buffer, format="PNG")
        qr_data = base64.b64encode(image_buffer.getvalue()).decode("ascii")
        return render_template("session.html", attendance_session=record, qr_data=qr_data)

    @app.route("/attendance/code", methods=["POST"])
    @role_required("student")
    def use_attendance_code():
        code = request.form.get("attendance_code", "").strip().upper()
        record = get_db().execute(
            "SELECT token FROM attendance_sessions WHERE attendance_code = ?", (code,)
        ).fetchone()
        if record is None:
            flash("That attendance code was not found.", "error")
            return redirect(url_for("dashboard"))
        return redirect(url_for("mark_attendance", token=record["token"]))

    @app.route("/attend/<token>", methods=["GET", "POST"])
    @role_required("student")
    def mark_attendance(token):
        user = current_user()
        record = get_db().execute(
            "SELECT s.*, c.title AS course_title, c.id AS course_id FROM attendance_sessions s "
            "JOIN courses c ON c.id = s.course_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        if record is None:
            abort(404)
        enrolled = get_db().execute(
            "SELECT 1 FROM enrollments WHERE course_id = ? AND student_id = ?",
            (record["course_id"], user["id"]),
        ).fetchone()
        if enrolled is None:
            abort(403)
        already_marked = get_db().execute(
            "SELECT 1 FROM attendance WHERE session_id = ? AND student_id = ?",
            (record["id"], user["id"]),
        ).fetchone() is not None
        expired = now_utc() > datetime.fromisoformat(record["expires_at"])
        if request.method == "POST":
            if expired:
                flash("This attendance session has expired.", "error")
            elif already_marked:
                flash("Your attendance was already recorded.", "success")
            else:
                get_db().execute(
                    "INSERT INTO attendance (session_id, student_id, marked_at) VALUES (?, ?, ?)",
                    (record["id"], user["id"], timestamp(now_utc())),
                )
                get_db().commit()
                flash("Attendance recorded.", "success")
                already_marked = True
        return render_template(
            "attend.html",
            attendance_session=record,
            already_marked=already_marked,
            expired=expired,
        )

    @app.route("/courses/<int:course_id>/report.csv")
    @role_required("teacher")
    def download_report(course_id):
        course = course_for_user(course_id)
        rows = get_db().execute(
            "SELECT u.name, u.email, s.starts_at, s.expires_at, a.marked_at "
            "FROM attendance_sessions s JOIN enrollments e ON e.course_id = s.course_id "
            "JOIN users u ON u.id = e.student_id "
            "LEFT JOIN attendance a ON a.session_id = s.id AND a.student_id = u.id "
            "WHERE s.course_id = ? ORDER BY s.starts_at, u.name",
            (course_id,),
        ).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Student", "Email", "Session started (UTC)", "Session expires (UTC)", "Marked at (UTC)", "Status"])
        for row in rows:
            writer.writerow(
                [row["name"], row["email"], row["starts_at"], row["expires_at"], row["marked_at"] or "", "Present" if row["marked_at"] else "Absent"]
            )
        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"{course['title'].replace(' ', '_')}_attendance.csv",
        )

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", title="Access denied", message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", title="Not found", message="That page or attendance link does not exist."), 404

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")