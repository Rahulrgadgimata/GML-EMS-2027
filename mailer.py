"""SMTP email automation for the GM League Season 4 event management system.

Design goals
------------
* **Never break a registration.** Every send is dispatched to a background
  worker; if SMTP is down, misconfigured or slow, the student still gets their
  "registered successfully" page. Failures are logged, not raised.
* **Works before credentials exist.** With ``MAIL_SUPPRESS_SEND=true`` (or with
  no username/password in ``.env``) messages are written to ``outbox/`` as
  ``.eml`` files instead of being sent, so the whole flow can be tested offline.
* **Multipart + inline logo.** Every mail carries a plain-text alternative and
  embeds the league emblem via ``cid:`` so it renders in Gmail, Outlook and
  Apple Mail without hitting a remote image blocker.
"""

from __future__ import annotations

import mimetypes
import os
import smtplib
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from flask import render_template


class Mailer:
    """Thin, dependency-free SMTP sender wired into the Flask app."""

    def __init__(self, app=None):
        self.app = None
        self._pool = None
        if app is not None:
            self.init_app(app)

    # ------------------------------------------------------------------ setup
    def init_app(self, app):
        self.app = app
        app.extensions = getattr(app, "extensions", {})
        app.extensions["mailer"] = self
        # Serverless hosts freeze the instance as soon as the response is
        # returned, so a queued background send is simply never executed. There
        # the send has to happen inline, before the response goes out.
        self.deliver_inline = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
        if self.deliver_inline:
            # Inline sending happens on the request's clock. The default 2 tries
            # at a 20s timeout is ~42s of worst case, well past the function's
            # limit, which would turn a slow SMTP server into a 504 on a
            # registration that actually succeeded. One short attempt instead:
            # a dropped mail is logged, a lost registration is not recoverable.
            app.config["MAIL_TIMEOUT"] = min(int(app.config.get("MAIL_TIMEOUT", 20)), 8)
            app.config["MAIL_MAX_RETRIES"] = 1
        self._pool = ThreadPoolExecutor(
            max_workers=app.config.get("MAIL_WORKERS", 2),
            thread_name_prefix="mailer",
        )
        # On Vercel (and other serverless), the filesystem is read-only except /tmp
        _tmp = Path("/tmp/outbox")
        _local = Path(app.root_path) / "outbox"
        # Use /tmp if the local path is not writable
        try:
            _local.mkdir(exist_ok=True)
            self.outbox = _local
        except OSError:
            self.outbox = _tmp  # _write_to_outbox creates it on first use

    # ------------------------------------------------------------------ state
    @property
    def enabled(self) -> bool:
        return bool(self.app and self.app.config.get("MAIL_ENABLED", True))

    @property
    def suppressed(self) -> bool:
        """True when mail should be written to disk instead of sent."""
        cfg = self.app.config
        if cfg.get("MAIL_SUPPRESS_SEND"):
            return True
        # No credentials yet? Fall back to the outbox rather than erroring out.
        return not (cfg.get("MAIL_USERNAME") and cfg.get("MAIL_PASSWORD"))

    def status(self) -> dict:
        """Human-readable config summary for the admin panel."""
        cfg = self.app.config
        if not self.enabled:
            mode = "disabled"
        elif self.suppressed:
            mode = "outbox (no credentials / suppressed)"
        else:
            mode = "live SMTP"
        return {
            "mode": mode,
            "server": f"{cfg.get('MAIL_SERVER')}:{cfg.get('MAIL_PORT')}",
            "security": "SSL" if cfg.get("MAIL_USE_SSL") else ("STARTTLS" if cfg.get("MAIL_USE_TLS") else "none"),
            "username": cfg.get("MAIL_USERNAME") or "(not set)",
            "sender": self._sender_header(),
        }

    # ------------------------------------------------------------------ public
    def send_template(self, *, to, subject, template, context=None, reply_to=None, bcc=None):
        """Render ``emails/<template>.html`` + ``.txt`` and queue it for delivery.

        Returns True when the message was accepted for sending (queued), False
        when there is nothing to do (mail off, or no recipient).
        """
        to = [addr for addr in ([to] if isinstance(to, str) else list(to or [])) if addr]
        if not to:
            return False
        if not self.enabled:
            self.app.logger.info("Mail disabled - skipping '%s' to %s", subject, ", ".join(to))
            return False

        context = dict(context or {})
        context.setdefault("subject", subject)
        context.setdefault("year", datetime.now().year)

        # Render inside the caller's context (request context is alive here),
        # so the background worker only ever does network I/O.
        html_body = render_template(f"emails/{template}.html", **context)
        try:
            text_body = render_template(f"emails/{template}.txt", **context)
        except Exception:  # optional plain-text partner
            text_body = _html_to_text(html_body)

        message = self._build_message(
            to=to,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            reply_to=reply_to or self.app.config.get("MAIL_REPLY_TO"),
            bcc=bcc if bcc is not None else self.app.config.get("MAIL_ADMIN_BCC"),
        )
        if self.deliver_inline:
            # _deliver never raises, so a dead SMTP server still cannot break
            # the registration that triggered this mail.
            self._deliver(message, to, subject)
        else:
            self._pool.submit(self._deliver, message, to, subject)
        return True

    def send_now(self, *, to, subject, template, context=None):
        """Synchronous variant used by the admin "send test mail" button.

        Returns ``(ok, detail)`` so the admin sees the real SMTP error.
        """
        to = [to] if isinstance(to, str) else list(to)
        context = dict(context or {})
        context.setdefault("subject", subject)
        context.setdefault("year", datetime.now().year)
        html_body = render_template(f"emails/{template}.html", **context)
        try:
            text_body = render_template(f"emails/{template}.txt", **context)
        except Exception:
            text_body = _html_to_text(html_body)
        message = self._build_message(
            to=to,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            reply_to=self.app.config.get("MAIL_REPLY_TO"),
            bcc=None,
        )
        try:
            detail = self._transmit(message, to)
            return True, detail
        except Exception as exc:  # surfaced straight to the admin UI
            return False, f"{type(exc).__name__}: {exc}"

    # ----------------------------------------------------------------- message
    def _sender_header(self) -> str:
        cfg = self.app.config
        email = cfg.get("MAIL_SENDER_EMAIL") or cfg.get("MAIL_USERNAME") or "no-reply@localhost"
        name = cfg.get("MAIL_SENDER_NAME") or "GM League"
        return formataddr((name, email))

    def _build_message(self, *, to, subject, html_body, text_body, reply_to, bcc):
        cfg = self.app.config
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._sender_header()
        msg["To"] = ", ".join(to)
        msg["Message-ID"] = make_msgid(domain=(cfg.get("MAIL_SENDER_EMAIL") or "gmleague.local").split("@")[-1])
        msg["Date"] = _rfc2822_now()
        if reply_to:
            msg["Reply-To"] = reply_to
        if bcc:
            msg["Bcc"] = bcc
        # Helps Gmail/Outlook file these as transactional rather than promo.
        msg["Auto-Submitted"] = "auto-generated"
        msg["X-Entity-Ref-ID"] = msg["Message-ID"]

        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")

        logo_path = cfg.get("MAIL_LOGO_PATH")
        if logo_path and os.path.isfile(logo_path):
            html_part = msg.get_payload()[-1]
            ctype, _ = mimetypes.guess_type(logo_path)
            maintype, subtype = (ctype or "image/png").split("/", 1)
            with open(logo_path, "rb") as fh:
                html_part.add_related(
                    fh.read(),
                    maintype=maintype,
                    subtype=subtype,
                    cid="<brandlogo>",
                    filename=os.path.basename(logo_path),
                )
        return msg

    # ---------------------------------------------------------------- delivery
    def _deliver(self, message, to, subject):
        """Background worker entry point - must never raise."""
        try:
            detail = self._transmit(message, to)
            self.app.logger.info("Mail '%s' -> %s (%s)", subject, ", ".join(to), detail)
        except Exception as exc:
            self.app.logger.error(
                "Mail FAILED '%s' -> %s: %s: %s", subject, ", ".join(to), type(exc).__name__, exc
            )

    def _transmit(self, message, to) -> str:
        if self.suppressed:
            return self._write_to_outbox(message, to)

        cfg = self.app.config
        host = cfg["MAIL_SERVER"]
        port = int(cfg["MAIL_PORT"])
        timeout = int(cfg.get("MAIL_TIMEOUT", 20))
        attempts = int(cfg.get("MAIL_MAX_RETRIES", 2))
        last_error: Exception = RuntimeError("SMTP delivery did not run")

        for attempt in range(1, attempts + 1):
            try:
                if cfg.get("MAIL_USE_SSL"):
                    ctx = ssl.create_default_context()
                    server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx)
                else:
                    server = smtplib.SMTP(host, port, timeout=timeout)
                with server:
                    server.ehlo()
                    if cfg.get("MAIL_USE_TLS") and not cfg.get("MAIL_USE_SSL"):
                        server.starttls(context=ssl.create_default_context())
                        server.ehlo()
                    server.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
                    server.send_message(message)
                return f"sent via {host}:{port}"
            except smtplib.SMTPAuthenticationError:
                raise  # bad credentials will never fix themselves on a retry
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(1.5 * attempt)
        raise last_error

    def _write_to_outbox(self, message, to) -> str:
        self.outbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe = "".join(ch if ch.isalnum() else "_" for ch in to[0])[:40]
        path = self.outbox / f"{stamp}_{safe}.eml"
        path.write_bytes(bytes(message))
        return f"written to outbox/{path.name}"


def _rfc2822_now() -> str:
    from email.utils import format_datetime

    return format_datetime(datetime.now().astimezone())


def _html_to_text(html: str) -> str:
    """Very small HTML -> text fallback for the plain-text alternative."""
    import re

    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for i, ln in enumerate(lines) if ln or (i and lines[i - 1]))
