# 🏆 GM League Season 4 — Event Management System

The event management platform for **GML S4**, the inter-collegiate sports league of
**GM University**. Players register, team owners register their franchise, the
organising desk runs a live auction, and everyone involved gets a branded
confirmation email automatically.

---

## ✨ What it does

| Area | Detail |
|---|---|
| **Player registration** | Name, **USN**, **email**, mobile, branch, college, position, category, experience, achievements and photo. One entry per USN per sport. |
| **Team owner registration** | Team name, owner name, **USN**, **email**, designation, contact, manager details, team logo, owner photo and the sports the franchise competes in. |
| **Live auction** | Card-per-player bidding room with a live purse cap, a sold-players ledger and keyboard navigation. |
| **Email automation** | Branded HTML + plain-text mail on registration and on every signing. See below. |
| **Admin console** | Live stats, per-sport tables with search and bulk delete, edit forms, bid reset, resend-confirmation, Excel exports and an SMTP test panel. |
| **Excel exports** | Per-sport, all-sports and team-owner workbooks with auto-sized columns, including USN and email. |

Sports live this season: **Football (Men), Kabaddi, Basketball, Badminton**.
Cricket, Volleyball, Throwball and Kho-Kho show as *Coming soon*.

---

## 🚀 Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure — a ready-to-edit .env already exists in the project root.
#    Open it and fill in MAIL_USERNAME / MAIL_PASSWORD (see next section).

# 4. Run
python app.py
```

Open <http://127.0.0.1:5000>. The admin console is at `/admin/login`.

The database schema upgrades itself on start-up — new columns are added to the
existing `instance/league.db` without touching the rows already in it.

---

## 📧 Email automation (SMTP)

**All you need to do is paste two values into `.env`:**

```ini
MAIL_USERNAME=your.address@gmail.com
MAIL_PASSWORD=your-app-password
```

> **Gmail:** use a 16-character **App Password**, not your normal login password.
> Google Account → Security → 2-Step Verification → App passwords.
> Your everyday password will be rejected with `SMTPAuthenticationError`.

Other providers — swap the server block in `.env`:

| Provider | `MAIL_SERVER` | `MAIL_PORT` | TLS / SSL |
|---|---|---|---|
| Gmail | `smtp.gmail.com` | 587 | `MAIL_USE_TLS=true` |
| Outlook / Office 365 | `smtp.office365.com` | 587 | `MAIL_USE_TLS=true` |
| Zoho | `smtp.zoho.in` | 465 | `MAIL_USE_SSL=true`, `MAIL_USE_TLS=false` |
| Brevo | `smtp-relay.brevo.com` | 587 | `MAIL_USE_TLS=true` |

### What goes out, and when

| Trigger | Recipient | Email |
|---|---|---|
| Player registers | The player | **Entry pass** — entry ID, full profile, what happens next |
| Team owner registers | The owner | **Franchise card** — squad details, auction purse, pre-auction checklist |
| Bid won at auction | The player | **SOLD** — team, owner, winning bid |
| Bid won at auction | The owner | **Signing sheet** — player contact details and remaining purse |
| Admin clicks *Email* | Player or owner | Re-sends the original confirmation |

Every message is table-based, fully inline-styled HTML with a plain-text
alternative and the university crest embedded as an inline `cid:` image, so it
renders correctly in Gmail, Outlook and Apple Mail even with images blocked.

### Testing it

The admin dashboard has an **Email automation** panel showing the live SMTP
config and a **Send test email** button that reports the exact SMTP response.

**Before you have credentials**, the system runs in dry-run mode automatically:
every message is written to `outbox/` as a `.eml` file (openable in any mail
client) instead of being sent. Force this on at any time with
`MAIL_SUPPRESS_SEND=true`, or turn email off entirely with `MAIL_ENABLED=false`.

Sending never blocks a registration — mail is dispatched on a background worker
and a failure is logged, not shown to the student.

---

## 🔐 Security

Change these in `.env` before the event:

```ini
SECRET_KEY=            # python -c "import secrets; print(secrets.token_urlsafe(48))"
ADMIN_USERNAME=admin
ADMIN_PASSWORD=        # or, better, ADMIN_PASSWORD_HASH
```

For a hashed admin password:

```bash
python -c "from werkzeug.security import generate_password_hash as g; print(g('your-password'))"
```

Put the result in `ADMIN_PASSWORD_HASH` and `ADMIN_PASSWORD` is ignored.

Also in place: CSRF tokens on every state-changing request, an `@admin_required`
guard on every admin route and export, login attempt throttling, HttpOnly
`SameSite=Lax` session cookies, an 8 MB upload cap, and uploads validated by
extension *and* magic bytes before they touch `static/`.

`.env` and `outbox/` are git-ignored — never commit them.

---

## 📂 Project structure

```
GML-EMS/
├── app.py                     # Routes, models, validation, auto-migration
├── mailer.py                  # SMTP engine (threaded, retrying, dry-run capable)
├── .env                       # Your live config — paste SMTP credentials here
├── .env.example               # Documented template
├── requirements.txt
├── instance/league.db         # SQLite database (auto-created / auto-upgraded)
├── outbox/                    # Dry-run .eml dumps (git-ignored)
├── static/
│   ├── css/league.css         # Public design system
│   ├── css/admin.css          # Admin console (no CDN — works offline)
│   ├── logos/ photos/ player_photos/ team_logos/ owner_photos/
└── templates/
    ├── base.html              # Public shell
    ├── admin_base.html        # Admin shell
    ├── index.html  register_player.html  team_owner_registration.html
    ├── registration_success.html  terms.html  error.html
    ├── admin_login.html  admin_dashboard.html
    ├── edit_player.html  edit_team_owner.html  bidding.html
    └── emails/
        ├── _layout.html  _macros.html
        ├── player_registered.html/.txt   owner_registered.html/.txt
        ├── player_sold.html/.txt         owner_signing.html/.txt
        └── test_mail.html
```

---

## 🛠️ Tech stack

Python · Flask · SQLAlchemy · Jinja2 · SQLite · pandas + XlsxWriter · smtplib.
No frontend framework and no CDN — the admin console and auction room work with
no internet connection, which matters at a venue.

---

## 🎛️ Configuration reference

Everything is driven by `.env`. Highlights beyond the SMTP block:

| Key | Purpose |
|---|---|
| `LEAGUE_NAME`, `LEAGUE_SHORT`, `LEAGUE_SEASON` | Branding across every page and email. Rename the season here — nothing is hardcoded. |
| `LEAGUE_TAGLINE`, `LEAGUE_UNIVERSITY` | Footer and email sign-off |
| `SUPPORT_PHONE`, `SUPPORT_EMAIL` | Contact details shown to students |
| `SITE_URL` | Link target in email CTA buttons |
| `DEFAULT_TEAM_BUDGET` | Auction purse each new franchise starts with |
| `MAX_UPLOAD_MB` | Photo / logo size cap |

---

## 📊 Possible next steps

* Live auction updates over WebSockets, so owners follow bidding on their phones
* Fixtures and results tracking after the auction
* Multiple admin accounts with roles
* Postgres + cloud deployment for multi-device use on match day
