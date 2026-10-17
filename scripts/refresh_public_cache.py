# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.
"""Retire only anonymous, unfiltered public responses after a fork deployment."""

PUBLIC_PATHS = ("/", "/home", "/course/explore", "/program/explore")


def refresh_public_cache(app):
    """Use the live key builder, including its generation, without broad eviction."""
    from flask_login import current_user

    from now_lms.cache import cache, cache_key_with_auth_state

    for path in PUBLIC_PATHS:
        # A fresh cookie-free context is anonymous. Refuse any unexpected loader
        # behavior instead of evicting a member's response or changing sessions.
        with app.app_context(), app.test_request_context(path):
            if current_user.is_authenticated:
                raise RuntimeError("Public cache refresh requires an anonymous context")
            key = cache_key_with_auth_state()
            cache.delete(key)
            print(f"PUBLIC CACHE OK: {path}")


if __name__ == "__main__":
    from now_lms import lms_app

    refresh_public_cache(lms_app)
