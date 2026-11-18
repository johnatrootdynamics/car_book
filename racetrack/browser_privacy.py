"""Essential-only browser storage and public-page privacy defaults."""

from flask import request
from flask_login import current_user


PUBLIC_INFORMATION_ENDPOINTS = {
    "auth.home", "auth.features", "auth.cookies", "auth.privacy",
    "auth.terms", "auth.community_guidelines", "auth.support",
}


def configure_browser_privacy(app, *, secure_cookies=True):
    # Session cookies are created by requested account/cart/form actions, not by
    # the cookie notice. Do not turn sessions permanent to remember the notice.
    app.config.update(
        SESSION_COOKIE_SECURE=secure_cookies,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_REFRESH_EACH_REQUEST=False,
        REMEMBER_COOKIE_SECURE=secure_cookies,
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
    )

    @app.after_request
    def browser_privacy_headers(response):
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.endpoint in {
            "auth.forgot_password", "auth.password_reset_sent", "auth.reset_password",
        }:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if request.endpoint in PUBLIC_INFORMATION_ENDPOINTS and (
            request.endpoint in {"auth.home", "auth.features"}
            or not current_user.is_authenticated
        ):
            # Public information pages have no third-party embeds or trackers.
            # Keep that boundary enforced if a remote resource is added later.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; font-src 'self'; media-src 'self'; "
                "connect-src 'self'; frame-src 'none'; object-src 'none'; "
                "base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
            )
        return response
