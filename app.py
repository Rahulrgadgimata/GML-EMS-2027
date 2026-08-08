"""GM League Season 4 — Event Management System.

Flask application powering player registration, franchise (team owner)
registration, the live auction, the admin console and the SMTP email
automation that confirms every one of those actions.

Configuration lives in ``.env`` (see ``.env.example``); nothing secret is
hardcoded here.
"""

from __future__ import annotations

import os
import re
import secrets
import uuid
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from urllib.parse import quote

# pandas is imported lazily inside excel_response() to keep cold-start fast on Vercel
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect as sa_inspect, text
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from mailer import Mailer

load_dotenv()


# --------------------------------------------------------------------------- #
# Small env helpers
# --------------------------------------------------------------------------- #
def env_str(key, default=""):
    value = os.getenv(key)
    return default if value is None else value.strip()


def env_bool(key, default=False):
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(key, default):
    try:
        return int(os.getenv(key, "").strip() or default)
    except ValueError:
        return default


# --------------------------------------------------------------------------- #
# App + configuration
# --------------------------------------------------------------------------- #
app = Flask(__name__)

app.config.update(
    SECRET_KEY=env_str("SECRET_KEY") or secrets.token_urlsafe(48),
    SQLALCHEMY_DATABASE_URI=env_str("DATABASE_URL", "sqlite:///league.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=os.path.join(app.root_path, "static", "player_photos"),
    TEAM_LOGO_FOLDER=os.path.join(app.root_path, "static", "team_logos"),
    OWNER_PHOTO_FOLDER=os.path.join(app.root_path, "static", "owner_photos"),
    MAX_CONTENT_LENGTH=env_int("MAX_UPLOAD_MB", 8) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE", False),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

# ---- Email automation -----------------------------------------------------
app.config.update(
    MAIL_ENABLED=env_bool("MAIL_ENABLED", True),
    MAIL_SUPPRESS_SEND=env_bool("MAIL_SUPPRESS_SEND", False),
    MAIL_SERVER=env_str("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT=env_int("MAIL_PORT", 587),
    MAIL_USE_TLS=env_bool("MAIL_USE_TLS", True),
    MAIL_USE_SSL=env_bool("MAIL_USE_SSL", False),
    MAIL_USERNAME=env_str("MAIL_USERNAME"),
    MAIL_PASSWORD=env_str("MAIL_PASSWORD"),
    MAIL_SENDER_NAME=env_str("MAIL_SENDER_NAME", "GM League Season 4"),
    MAIL_SENDER_EMAIL=env_str("MAIL_SENDER_EMAIL") or env_str("MAIL_USERNAME"),
    MAIL_REPLY_TO=env_str("MAIL_REPLY_TO"),
    MAIL_ADMIN_BCC=env_str("MAIL_ADMIN_BCC"),
    MAIL_TIMEOUT=env_int("MAIL_TIMEOUT", 20),
    MAIL_MAX_RETRIES=env_int("MAIL_MAX_RETRIES", 2),
    MAIL_WORKERS=env_int("MAIL_WORKERS", 2),
    MAIL_LOGO_PATH=os.path.join(app.root_path, "static", "logos", env_str("MAIL_LOGO_FILE", "gmulogo1.png")),
)

# ---- Branding (drives every page title, header and email) -----------------
BRAND = {
    "name": env_str("LEAGUE_NAME", "GM League Season 4"),
    "short": env_str("LEAGUE_SHORT", "GML S4"),
    "season": env_str("LEAGUE_SEASON", "Season 4"),
    "university": env_str("LEAGUE_UNIVERSITY", "GM University"),
    "tagline": env_str("LEAGUE_TAGLINE", "Season 4 — Where Legends Are Born"),
    "site_url": env_str("SITE_URL", "http://127.0.0.1:5000"),
    "support_phone": env_str("SUPPORT_PHONE", "6363962653"),
    "support_phone_alt": env_str("SUPPORT_PHONE_ALT", "7019670142"),
    "support_email": env_str("SUPPORT_EMAIL"),
    "whatsapp_number": env_str("WHATSAPP_NUMBER", "8618139789"),
    "whatsapp_country_code": env_str("WHATSAPP_COUNTRY_CODE", "91"),
    # Good-luck message signed off at the end of every automated email.
    "director_name": env_str("DIRECTOR_NAME", "Ajjaiah G B"),
    "director_title": env_str("DIRECTOR_TITLE", "Director — PE"),
    "director_message": env_str(
        "DIRECTOR_MESSAGE",
        "Play hard, play fair, and enjoy every minute of it. "
        "The whole Physical Education department is behind you this season — go make it count.",
    ),
}

# The header wordmark: the league name without the season suffix ("GM League"),
# so the season can sit beside it as its own badge.
BRAND["wordmark"] = env_str("LEAGUE_WORDMARK") or (
    BRAND["name"].replace(BRAND["season"], "").strip(" -—–·") or BRAND["name"]
)

# Both helpline numbers, in one list so no template has to know there are two.
BRAND["support_phones"] = [p for p in (BRAND["support_phone"], BRAND["support_phone_alt"]) if p]
BRAND["support_phones_text"] = " or ".join(BRAND["support_phones"])
# wa.me needs the full international number with no "+" or spaces.
BRAND["whatsapp_url"] = (
    f"https://wa.me/{BRAND['whatsapp_country_code']}{BRAND['whatsapp_number']}"
    f"?text={quote('Hi! I have a question about ' + BRAND['name'] + '.')}"
    if BRAND["whatsapp_number"]
    else ""
)

ADMIN_USERNAME = env_str("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = env_str("ADMIN_PASSWORD", "password")
ADMIN_PASSWORD_HASH = env_str("ADMIN_PASSWORD_HASH")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"RIFF")

SPORTS = ["Football", "Kabaddi", "Basketball", "Badminton"]
SPORT_CODES = {"Football": "FB", "Kabaddi": "KB", "Basketball": "BB", "Badminton": "BD"}
POSITIONS = {
    "Football": ["Goalkeeper", "Defender", "Midfielder", "Forward"],
    "Kabaddi": ["Raider", "Defender", "All-Rounder"],
    "Basketball": ["Point Guard", "Shooting Guard", "Small Forward", "Power Forward", "Center"],
    "Badminton": ["Singles", "Doubles"],
}
# Football is a men's event this season; everything else runs both categories.
MENS_ONLY_SPORTS = {"Football"}
OWNER_SPORT_OPTIONS = [
    "Football(Men)",
    "Basketball(Men)",
    "Basketball(Women)",
    "Kabaddi(Men)",
    "Kabaddi(Women)",
    "Badminton(Men)",
    "Badminton(Women)",
]
DEFAULT_BUDGET = env_int("DEFAULT_TEAM_BUDGET", 1000000)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
mailer = Mailer(app)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sport = db.Column(db.String(50), nullable=False)
    branch = db.Column(db.String(50))
    usn = db.Column(db.String(20))
    email = db.Column(db.String(120))
    college_name = db.Column(db.String(100))
    position = db.Column(db.String(50))
    contact = db.Column(db.String(20))
    photo = db.Column(db.String(200))
    achievements = db.Column(db.Text)
    experience = db.Column(db.String(50))
    gender = db.Column(db.String(10))
    sold = db.Column(db.Boolean, default=False)
    bid_amount = db.Column(db.Integer)
    sold_to = db.Column(db.String(100))
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def reg_code(self):
        return f"{BRAND['short'].replace(' ', '')}-{SPORT_CODES.get(self.sport, 'GM')}-{self.id:04d}"


class TeamOwner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    team_name = db.Column(db.String(100), nullable=False, unique=True)
    sports = db.Column(db.String(200), nullable=False)
    budget = db.Column(db.Integer, default=DEFAULT_BUDGET)
    contact = db.Column(db.String(20))
    team_logo = db.Column(db.String(200))
    designation = db.Column(db.String(100))
    email = db.Column(db.String(120))
    usn = db.Column(db.String(20))
    manager_name = db.Column(db.String(100))
    manager_contact_number = db.Column(db.String(20))
    team_owner_photo = db.Column(db.String(200))
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def reg_code(self):
        return f"{BRAND['short'].replace(' ', '')}-TM-{self.id:04d}"


def ensure_schema():
    """Add any model column that is missing from an existing SQLite file.

    The project ships with a populated ``league.db``; this keeps that data
    intact when new fields (email, usn, registered_at) are introduced, without
    forcing anyone to run ``flask db upgrade`` by hand.
    """
    inspector = sa_inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    for model in (Player, TeamOwner):
        table = model.__table__
        if table.name not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            ddl = column.type.compile(dialect=db.engine.dialect)
            app.logger.info("Schema upgrade: adding %s.%s", table.name, column.name)
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'))


with app.app_context():
    for folder in ("UPLOAD_FOLDER", "TEAM_LOGO_FOLDER", "OWNER_PHOTO_FOLDER"):
        os.makedirs(app.config[folder], exist_ok=True)
    db.create_all()
    ensure_schema()


# --------------------------------------------------------------------------- #
# CSRF protection (session token, no extra dependency)
# --------------------------------------------------------------------------- #
def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.before_request
def protect_against_csrf():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    sent = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("_csrf_token", "")
    if not expected or not secrets.compare_digest(str(sent), str(expected)):
        if request.is_json or request.headers.get("X-CSRF-Token") is not None:
            return jsonify({"error": "Session expired. Reload the page and try again."}), 400
        flash("Your session expired. Please fill the form again.", "error")
        return redirect(request.referrer or url_for("index"))
    return None


@app.context_processor
def inject_globals():
    return {
        "csrf_token": csrf_token,
        "brand": BRAND,
        "sports": SPORTS,
        "now_year": datetime.now().year,
    }


# --------------------------------------------------------------------------- #
# Validation + upload helpers
# --------------------------------------------------------------------------- #
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")


def clean(value, limit=200):
    return (value or "").strip()[:limit]


def normalise_phone(value):
    """Strip +91 / spaces / dashes so 10-digit validation is fair to users."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def looks_like_image(storage):
    """Cheap magic-byte sniff so a renamed .exe cannot land in static/."""
    head = storage.stream.read(12)
    storage.stream.seek(0)
    return head.startswith(IMAGE_MAGIC)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(storage, folder_key, subdir, label):
    """Validate and store an uploaded image.

    Returns ``(relative_path, error)``. ``relative_path`` is what goes in the
    database (e.g. ``player_photos/abc.jpg``); it is ``None`` when no file was
    supplied, which is not an error.
    """
    if not storage or not storage.filename:
        return None, None
    if not allowed_file(storage.filename):
        return None, f"{label} must be a PNG, JPG, GIF or WEBP image."
    if not looks_like_image(storage):
        return None, f"{label} does not look like a real image file."

    extension = storage.filename.rsplit(".", 1)[1].lower()
    stem = secure_filename(label.replace(" ", "_")) or "upload"
    filename = f"{stem}_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}.{extension}"
    destination = os.path.join(app.config[folder_key], filename)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    storage.save(destination)
    return f"{subdir}/{filename}", None


def delete_upload(relative_path, folder_key):
    if not relative_path:
        return
    path = os.path.join(app.config[folder_key], os.path.basename(relative_path))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as exc:  # a stale file must never block a delete
        app.logger.warning("Could not remove %s: %s", path, exc)


def rupees(amount):
    return f"₹ {int(amount or 0):,}"


def category_of(player):
    """The league talks in Men/Women, not the raw Male/Female stored value."""
    return "Women" if player.gender == "Female" else "Men"


# --------------------------------------------------------------------------- #
# Email dispatch
# --------------------------------------------------------------------------- #
def has_logo():
    return os.path.isfile(app.config["MAIL_LOGO_PATH"])


def email_player_registered(player):
    return mailer.send_template(
        to=player.email,
        subject=f"You're registered — {player.sport} · {BRAND['name']}",
        template="player_registered",
        context={
            "player": player,
            "sport": player.sport,
            "reg_code": player.reg_code,
            "category": category_of(player),
            "brand": BRAND,
            "logo_cid": has_logo(),
        },
    )


def email_owner_registered(owner):
    return mailer.send_template(
        to=owner.email,
        subject=f"{owner.team_name} is registered — {BRAND['name']}",
        template="owner_registered",
        context={"owner": owner, "reg_code": owner.reg_code, "brand": BRAND, "logo_cid": has_logo()},
    )


def email_player_sold(player, owner, amount):
    mailer.send_template(
        to=player.email,
        subject=f"SOLD! {owner.team_name} signed you for {rupees(amount)}",
        template="player_sold",
        context={
            "player": player,
            "sport": player.sport,
            "team_name": owner.team_name,
            "owner_name": owner.name,
            "category": category_of(player),
            "amount_display": rupees(amount),
            "brand": BRAND,
            "logo_cid": has_logo(),
        },
    )
    mailer.send_template(
        to=owner.email,
        subject=f"Signed: {player.name} for {rupees(amount)} — {owner.team_name}",
        template="owner_signing",
        context={
            "player": player,
            "owner": owner,
            "sport": player.sport,
            "team_name": owner.team_name,
            "category": category_of(player),
            "amount_display": rupees(amount),
            "budget_display": rupees(owner.budget),
            "brand": BRAND,
            "logo_cid": has_logo(),
        },
    )


# --------------------------------------------------------------------------- #
# Public routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    stats = {
        "players": Player.query.count(),
        "teams": TeamOwner.query.count(),
        "sports": len(SPORTS),
        "sold": Player.query.filter_by(sold=True).count(),
    }
    return render_template("index.html", stats=stats)


@app.route("/register_player/<sport>", methods=["GET", "POST"])
def register_player(sport):
    sport = sport.capitalize()
    if sport not in SPORTS:
        flash("That sport is not part of this season.", "error")
        return redirect(url_for("index"))

    positions = POSITIONS[sport]
    form = {}

    if request.method == "POST":
        form = {
            "name": clean(request.form.get("name"), 100),
            "branch": clean(request.form.get("branch"), 50),
            "usn": clean(request.form.get("usn"), 20).upper(),
            "email": clean(request.form.get("email"), 120).lower(),
            "college_name": clean(request.form.get("college_name"), 100),
            "position": clean(request.form.get("position"), 50),
            "contact": normalise_phone(request.form.get("contact")),
            "achievements": clean(request.form.get("achievements"), 2000),
            "experience": clean(request.form.get("experience"), 50),
            "gender": clean(request.form.get("gender"), 10),
        }

        errors = []
        if len(form["name"]) < 3:
            errors.append("Please enter your full name.")
        if not form["usn"]:
            errors.append("USN is required.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Please enter a valid email address — your confirmation is sent there.")
        if not PHONE_RE.match(form["contact"]):
            errors.append("Contact must be a valid 10-digit mobile number.")
        if form["position"] not in positions:
            errors.append(f"Please choose a valid {sport} position.")
        if form["gender"] not in {"Male", "Female"}:
            errors.append("Please select a category.")
        if form["experience"] not in {"Beginner", "Intermediate", "Pro"}:
            errors.append("Please select your experience level.")
        if sport in MENS_ONLY_SPORTS and form["gender"] == "Female":
            errors.append(f"{sport} runs as a men's event this season. Please pick another sport.")
        if not form["branch"]:
            errors.append("Branch is required.")
        if not form["college_name"]:
            errors.append("College name is required.")

        duplicate = Player.query.filter(
            db.func.upper(Player.usn) == form["usn"], Player.sport == sport
        ).first()
        if form["usn"] and duplicate:
            errors.append(f"USN {form['usn']} is already registered for {sport}.")

        photo_path, photo_error = save_upload(
            request.files.get("photo"), "UPLOAD_FOLDER", "player_photos", form["name"] or "player"
        )
        if photo_error:
            errors.append(photo_error)

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "register_player.html", sport=sport, positions=positions, form=form
            )

        player = Player(sport=sport, photo=photo_path, **form)
        try:
            db.session.add(player)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Player registration failed")
            flash(f"We could not save your registration: {exc}", "error")
            return render_template(
                "register_player.html", sport=sport, positions=positions, form=form
            )

        queued = email_player_registered(player)
        flash(
            f"You're registered for {sport}! Entry ID {player.reg_code}."
            + (f" A confirmation is on its way to {player.email}." if queued else ""),
            "success",
        )
        return redirect(url_for("registration_success", kind="player", code=player.reg_code))

    return render_template("register_player.html", sport=sport, positions=positions, form=form)


@app.route("/team_owner_registration", methods=["GET", "POST"])
def team_owner_registration():
    form = {}
    selected_sports = []

    if request.method == "POST":
        form = {
            "name": clean(request.form.get("name"), 100),
            "team_name": clean(request.form.get("team_name"), 100),
            "usn": clean(request.form.get("usn"), 20).upper(),
            "email": clean(request.form.get("email"), 120).lower(),
            "designation": clean(request.form.get("designation"), 100),
            "contact": normalise_phone(request.form.get("contact")),
            "manager_name": clean(request.form.get("manager_name"), 100),
            "manager_contact_number": normalise_phone(request.form.get("manager_contact_number")),
        }
        selected_sports = [s for s in request.form.getlist("sports") if s in OWNER_SPORT_OPTIONS]

        errors = []
        if len(form["name"]) < 3:
            errors.append("Please enter the owner's full name.")
        if not form["team_name"]:
            errors.append("Team name is required.")
        if not form["usn"]:
            errors.append("USN is required.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Please enter a valid email address — your confirmation is sent there.")
        if not PHONE_RE.match(form["contact"]):
            errors.append("Contact must be a valid 10-digit mobile number.")
        if form["manager_contact_number"] and not PHONE_RE.match(form["manager_contact_number"]):
            errors.append("Manager contact must be a valid 10-digit mobile number.")
        if not selected_sports:
            errors.append("Select at least one sport your team will compete in.")
        if TeamOwner.query.filter(db.func.lower(TeamOwner.team_name) == form["team_name"].lower()).first():
            errors.append(f"The team name “{form['team_name']}” is already taken.")

        logo_path, logo_error = save_upload(
            request.files.get("team_logo"), "TEAM_LOGO_FOLDER", "team_logos", form["team_name"] or "team"
        )
        photo_path, photo_error = save_upload(
            request.files.get("team_owner_photo"), "OWNER_PHOTO_FOLDER", "owner_photos", form["name"] or "owner"
        )
        errors.extend(e for e in (logo_error, photo_error) if e)

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "team_owner_registration.html",
                sport_options=OWNER_SPORT_OPTIONS,
                form=form,
                selected_sports=selected_sports,
            )

        owner = TeamOwner(
            sports=",".join(s.split("(")[0].strip() for s in selected_sports),
            budget=DEFAULT_BUDGET,
            team_logo=logo_path,
            team_owner_photo=photo_path,
            **form,
        )
        try:
            db.session.add(owner)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Team owner registration failed")
            flash(f"We could not save your registration: {exc}", "error")
            return render_template(
                "team_owner_registration.html",
                sport_options=OWNER_SPORT_OPTIONS,
                form=form,
                selected_sports=selected_sports,
            )

        queued = email_owner_registered(owner)
        flash(
            f"{owner.team_name} is registered! Franchise ID {owner.reg_code}."
            + (f" A confirmation is on its way to {owner.email}." if queued else ""),
            "success",
        )
        return redirect(url_for("registration_success", kind="owner", code=owner.reg_code))

    return render_template(
        "team_owner_registration.html",
        sport_options=OWNER_SPORT_OPTIONS,
        form=form,
        selected_sports=selected_sports,
    )


@app.route("/registered/<kind>/<code>")
def registration_success(kind, code):
    if kind not in {"player", "owner"}:
        abort(404)
    return render_template("registration_success.html", kind=kind, code=code)


@app.route("/bidding/<sport>/<gender>", methods=["GET", "POST"])
def bidding(sport, gender):
    sport = sport.capitalize()
    gender = gender.capitalize()
    if sport not in SPORTS:
        flash("That sport is not part of this season.", "error")
        return redirect(url_for("index"))
    if gender not in {"Male", "Female"} or (sport in MENS_ONLY_SPORTS and gender == "Female"):
        flash("That sport and category combination does not exist.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        player = db.session.get(Player, request.form.get("player_id", type=int))
        owner = db.session.get(TeamOwner, request.form.get("owner_id", type=int))
        bid_amount = request.form.get("bid_amount", type=int)

        if not player or not owner:
            flash("Invalid player or team owner selected.", "error")
        elif player.sold:
            flash(f"{player.name} has already been sold to {player.sold_to}.", "error")
        elif bid_amount is None or bid_amount <= 0:
            flash("Enter a bid amount greater than zero.", "error")
        elif bid_amount > owner.budget:
            flash(
                f"{owner.team_name} only has {rupees(owner.budget)} left — that bid is too high.",
                "error",
            )
        elif player.sport.lower() not in (owner.sports or "").lower():
            flash(f"{owner.team_name} is not registered for {player.sport}.", "error")
        else:
            player.sold = True
            player.bid_amount = bid_amount
            player.sold_to = owner.team_name
            owner.budget -= bid_amount
            try:
                db.session.commit()
                email_player_sold(player, owner, bid_amount)
                flash(
                    f"SOLD! {player.name} goes to {owner.team_name} for {rupees(bid_amount)}. "
                    f"Remaining purse: {rupees(owner.budget)}.",
                    "success",
                )
            except Exception as exc:
                db.session.rollback()
                app.logger.exception("Bid failed")
                flash(f"Could not record that bid: {exc}", "error")
        return redirect(url_for("bidding", sport=sport.lower(), gender=gender.lower()))

    effective_gender = "Male" if sport in MENS_ONLY_SPORTS else gender
    players = (
        Player.query.filter_by(sport=sport, gender=effective_gender, sold=False)
        .order_by(Player.name)
        .all()
    )
    owners = (
        TeamOwner.query.filter(TeamOwner.sports.ilike(f"%{sport}%")).order_by(TeamOwner.team_name).all()
    )
    sold_here = (
        Player.query.filter_by(sport=sport, gender=effective_gender, sold=True)
        .order_by(Player.bid_amount.desc())
        .all()
    )
    return render_template(
        "bidding.html",
        sport=sport,
        gender=gender,
        players=players,
        owners=owners,
        sold_players=sold_here,
        mens_only=sport in MENS_ONLY_SPORTS,
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            if request.is_json:
                return jsonify({"error": "Admin login required."}), 401
            flash("Admin login required.", "error")
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_password_ok(candidate):
    if ADMIN_PASSWORD_HASH:
        return check_password_hash(ADMIN_PASSWORD_HASH, candidate)
    return secrets.compare_digest(candidate, ADMIN_PASSWORD)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        attempts = session.get("_login_attempts", 0)
        if attempts >= 8:
            flash("Too many failed attempts. Close the browser tab and try again.", "error")
            return render_template("admin_login.html")

        username = clean(request.form.get("username"), 60)
        password = request.form.get("password") or ""
        if secrets.compare_digest(username, ADMIN_USERNAME) and admin_password_ok(password):
            session.clear()
            session.permanent = True
            session["admin_logged_in"] = True
            flash("Welcome back. You're logged in.", "success")
            target = request.args.get("next") or request.form.get("next") or ""
            return redirect(target if target.startswith("/admin") else url_for("admin_dashboard"))

        session["_login_attempts"] = attempts + 1
        flash("Invalid username or password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    players_by_sport = {s: Player.query.filter_by(sport=s).order_by(Player.name).all() for s in SPORTS}
    owners = TeamOwner.query.order_by(TeamOwner.team_name).all()
    sold_players = Player.query.filter_by(sold=True).order_by(Player.bid_amount.desc()).all()
    all_players = [p for group in players_by_sport.values() for p in group]
    return render_template(
        "admin_dashboard.html",
        players_by_sport=players_by_sport,
        owners=owners,
        sold_players=sold_players,
        total_players=len(all_players),
        missing_email=sum(1 for p in all_players if not p.email),
        spent=sum(p.bid_amount or 0 for p in sold_players),
        remaining=sum(o.budget or 0 for o in owners),
        mail_status=mailer.status(),
    )


@app.route("/admin/mail_test", methods=["POST"])
@admin_required
def admin_mail_test():
    recipient = clean(request.form.get("recipient"), 120).lower()
    if not EMAIL_RE.match(recipient):
        flash("Enter a valid email address to send the test to.", "error")
        return redirect(url_for("admin_dashboard"))

    status = mailer.status()
    ok, detail = mailer.send_now(
        to=recipient,
        subject=f"SMTP test — {BRAND['name']} event management system",
        template="test_mail",
        context={
            "brand": BRAND,
            "logo_cid": has_logo(),
            "sent_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "smtp_server": status["server"],
            "smtp_security": status["security"],
            "smtp_username": status["username"],
            "smtp_sender": status["sender"],
        },
    )
    flash(
        f"Test mail to {recipient}: {detail}" if ok else f"Test mail failed — {detail}",
        "success" if ok else "error",
    )
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/resend/<kind>/<int:record_id>", methods=["POST"])
@admin_required
def admin_resend_confirmation(kind, record_id):
    if kind == "player":
        player = db.session.get(Player, record_id) or abort(404)
        if not player.email:
            flash(f"{player.name} has no email address on record.", "error")
        elif email_player_registered(player):
            flash(f"Confirmation re-sent to {player.email}.", "success")
        else:
            flash("Email automation is switched off.", "error")
    elif kind == "owner":
        owner = db.session.get(TeamOwner, record_id) or abort(404)
        if not owner.email:
            flash(f"{owner.team_name} has no email address on record.", "error")
        elif email_owner_registered(owner):
            flash(f"Confirmation re-sent to {owner.email}.", "success")
        else:
            flash("Email automation is switched off.", "error")
    else:
        abort(404)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reset_bid/<int:player_id>", methods=["POST"])
@admin_required
def admin_reset_bid(player_id):
    player = db.session.get(Player, player_id) or abort(404)
    owner = TeamOwner.query.filter_by(team_name=player.sold_to).first()
    if owner and player.bid_amount:
        owner.budget += player.bid_amount
    player.sold = False
    player.bid_amount = None
    player.sold_to = None
    try:
        db.session.commit()
        flash(f"Bid reset for {player.name}. The purse has been refunded.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Error resetting bid: {exc}", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete_player/<int:id>", methods=["POST"])
@admin_required
def admin_delete_player(id):
    player = db.session.get(Player, id) or abort(404)
    name = player.name
    try:
        delete_upload(player.photo, "UPLOAD_FOLDER")
        db.session.delete(player)
        db.session.commit()
        flash(f"Player {name} deleted.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Error deleting player: {exc}", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete_owner/<int:id>", methods=["POST"])
@admin_required
def admin_delete_owner(id):
    owner = db.session.get(TeamOwner, id) or abort(404)
    team = owner.team_name
    try:
        delete_upload(owner.team_logo, "TEAM_LOGO_FOLDER")
        delete_upload(owner.team_owner_photo, "OWNER_PHOTO_FOLDER")
        db.session.delete(owner)
        db.session.commit()
        flash(f"Team owner {team} deleted.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Error deleting team owner: {exc}", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete_players", methods=["POST"])
@admin_required
def admin_delete_players():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "No players selected"}), 400
    try:
        for player in Player.query.filter(Player.id.in_(ids)).all():
            delete_upload(player.photo, "UPLOAD_FOLDER")
            db.session.delete(player)
        db.session.commit()
        return jsonify({"message": f"{len(ids)} player(s) deleted"}), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Error deleting players: {exc}"}), 500


@app.route("/admin/delete_owners", methods=["POST"])
@admin_required
def admin_delete_owners():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "No owners selected"}), 400
    try:
        for owner in TeamOwner.query.filter(TeamOwner.id.in_(ids)).all():
            delete_upload(owner.team_logo, "TEAM_LOGO_FOLDER")
            delete_upload(owner.team_owner_photo, "OWNER_PHOTO_FOLDER")
            db.session.delete(owner)
        db.session.commit()
        return jsonify({"message": f"{len(ids)} owner(s) deleted"}), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Error deleting owners: {exc}"}), 500


@app.route("/admin/edit_player/<int:id>", methods=["GET", "POST"])
@admin_required
def admin_edit_player(id):
    player = db.session.get(Player, id) or abort(404)
    if request.method == "POST":
        sport = clean(request.form.get("sport"), 50)
        if sport not in SPORTS:
            flash("Invalid sport.", "error")
            return redirect(url_for("admin_edit_player", id=id))

        position = clean(request.form.get("position"), 50)
        try:
            player.name = clean(request.form.get("name"), 100) or player.name
            player.sport = sport
            player.position = position if position in POSITIONS[sport] else None
            player.branch = clean(request.form.get("branch"), 50) or None
            player.usn = clean(request.form.get("usn"), 20).upper() or None
            player.email = clean(request.form.get("email"), 120).lower() or None
            player.college_name = clean(request.form.get("college_name"), 100) or None
            player.contact = normalise_phone(request.form.get("contact")) or None
            player.achievements = clean(request.form.get("achievements"), 2000) or None
            player.experience = clean(request.form.get("experience"), 50) or player.experience
            player.gender = clean(request.form.get("gender"), 10) or player.gender

            new_photo, photo_error = save_upload(
                request.files.get("photo"), "UPLOAD_FOLDER", "player_photos", player.name
            )
            if photo_error:
                flash(photo_error, "error")
                return redirect(url_for("admin_edit_player", id=id))
            if new_photo:
                delete_upload(player.photo, "UPLOAD_FOLDER")
                player.photo = new_photo

            db.session.commit()
            flash(f"Player {player.name} updated.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error updating player: {exc}", "error")
        return redirect(url_for("admin_dashboard"))

    return render_template(
        "edit_player.html", player=player, positions=POSITIONS.get(player.sport, []), all_positions=POSITIONS
    )


@app.route("/admin/edit_team_owner/<int:id>", methods=["GET", "POST"])
@admin_required
def admin_edit_team_owner(id):
    owner = db.session.get(TeamOwner, id) or abort(404)
    if request.method == "POST":
        selected = [s for s in request.form.getlist("sports") if s in OWNER_SPORT_OPTIONS]
        if not selected:
            flash("Select at least one sport.", "error")
            return redirect(url_for("admin_edit_team_owner", id=id))
        try:
            owner.name = clean(request.form.get("name"), 100) or owner.name
            owner.team_name = clean(request.form.get("team_name"), 100) or owner.team_name
            owner.sports = ",".join(s.split("(")[0].strip() for s in selected)
            owner.budget = request.form.get("budget", type=int) or 0
            owner.contact = normalise_phone(request.form.get("contact")) or None
            owner.usn = clean(request.form.get("usn"), 20).upper() or None
            owner.designation = clean(request.form.get("designation"), 100) or None
            owner.email = clean(request.form.get("email"), 120).lower() or None
            owner.manager_name = clean(request.form.get("manager_name"), 100) or None
            owner.manager_contact_number = normalise_phone(request.form.get("manager_contact_number")) or None

            new_logo, logo_error = save_upload(
                request.files.get("team_logo"), "TEAM_LOGO_FOLDER", "team_logos", owner.team_name
            )
            new_photo, photo_error = save_upload(
                request.files.get("team_owner_photo"), "OWNER_PHOTO_FOLDER", "owner_photos", owner.name
            )
            for message in (logo_error, photo_error):
                if message:
                    flash(message, "error")
                    return redirect(url_for("admin_edit_team_owner", id=id))
            if new_logo:
                delete_upload(owner.team_logo, "TEAM_LOGO_FOLDER")
                owner.team_logo = new_logo
            if new_photo:
                delete_upload(owner.team_owner_photo, "OWNER_PHOTO_FOLDER")
                owner.team_owner_photo = new_photo

            db.session.commit()
            flash(f"Team owner {owner.team_name} updated.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error updating team owner: {exc}", "error")
        return redirect(url_for("admin_dashboard"))

    owned = {s.strip().lower() for s in (owner.sports or "").split(",") if s.strip()}
    return render_template(
        "edit_team_owner.html", owner=owner, sport_options=OWNER_SPORT_OPTIONS, owned=owned
    )


# --------------------------------------------------------------------------- #
# Excel exports
# --------------------------------------------------------------------------- #
def player_rows(players):
    return [
        {
            "Entry ID": p.reg_code,
            "Name": p.name,
            "USN": p.usn or "N/A",
            "Email": p.email or "N/A",
            "Contact": p.contact or "N/A",
            "Branch": p.branch or "N/A",
            "College": p.college_name or "N/A",
            "Sport": p.sport,
            "Position": p.position or "N/A",
            "Category": p.gender or "N/A",
            "Experience": p.experience or "N/A",
            "Achievements": p.achievements or "None",
            "Sold To": p.sold_to or "Not Sold",
            "Bid Amount": p.bid_amount or 0,
            "Registered On": p.registered_at.strftime("%Y-%m-%d %H:%M") if p.registered_at else "N/A",
            "Photo": p.photo or "N/A",
        }
        for p in players
    ]


def owner_rows(owners):
    return [
        {
            "Franchise ID": o.reg_code,
            "Team Name": o.team_name,
            "Owner": o.name,
            "USN": o.usn or "N/A",
            "Email": o.email or "N/A",
            "Contact": o.contact or "N/A",
            "Designation": o.designation or "N/A",
            "Sports": o.sports,
            "Remaining Budget": o.budget,
            "Manager Name": o.manager_name or "N/A",
            "Manager Contact": o.manager_contact_number or "N/A",
            "Registered On": o.registered_at.strftime("%Y-%m-%d %H:%M") if o.registered_at else "N/A",
        }
        for o in owners
    ]


def excel_response(sheets, filename):
    """``sheets`` is a list of ``(sheet_name, list-of-dict-rows)``."""
    import pandas as pd  # lazy import — keeps Vercel cold-start fast
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for sheet_name, rows in sheets:
            frame = pd.DataFrame(rows if rows else [{"Info": "No records"}])
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            worksheet = writer.sheets[sheet_name[:31]]
            for column_index, column in enumerate(frame.columns):
                width = max(len(str(column)), *(len(str(v)) for v in frame[column])) if len(frame) else len(str(column))
                worksheet.set_column(column_index, column_index, min(max(width + 2, 10), 42))
    output.seek(0)
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/export_summary/<sport>")
@admin_required
def export_summary(sport):
    sport = sport.capitalize()
    if sport not in SPORTS:
        flash("Invalid sport.", "error")
        return redirect(url_for("admin_dashboard"))
    players = Player.query.filter_by(sport=sport).order_by(Player.name).all()
    return excel_response([(sport, player_rows(players))], f"{BRAND['short']}_{sport}_Players.xlsx")


@app.route("/export_all_summaries")
@admin_required
def export_all_summaries():
    sheets = [(s, player_rows(Player.query.filter_by(sport=s).order_by(Player.name).all())) for s in SPORTS]
    sheets.append(("Team Owners", owner_rows(TeamOwner.query.order_by(TeamOwner.team_name).all())))
    return excel_response(sheets, f"{BRAND['short']}_All_Summaries.xlsx")


@app.route("/export_owners")
@admin_required
def export_owners():
    owners = TeamOwner.query.order_by(TeamOwner.team_name).all()
    return excel_response([("Team Owners", owner_rows(owners))], f"{BRAND['short']}_Team_Owners.xlsx")


# --------------------------------------------------------------------------- #
# Error handlers
# --------------------------------------------------------------------------- #
@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, title="Page not found",
                           message="That page isn't part of the league."), 404


@app.errorhandler(413)
def too_large(_error):
    limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return render_template("error.html", code=413, title="File too large",
                           message=f"Photos and logos must be under {limit} MB. Please compress and try again."), 413


@app.errorhandler(500)
def server_error(error):
    app.logger.exception("Unhandled error: %s", error)
    db.session.rollback()
    return render_template("error.html", code=500, title="Something broke",
                           message="Our fault, not yours. Please try again in a moment."), 500


if __name__ == "__main__":
    app.run(debug=env_bool("FLASK_DEBUG", True), host=env_str("HOST", "127.0.0.1"), port=env_int("PORT", 5000))
