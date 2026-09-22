"""
Cognito PreSignUp trigger: restrict the pool to one email domain.

A user pool cannot express "only @company.com" on its own -- there is no
attribute constraint for it -- so the check runs here, before the account
is created. Raising rejects the sign-up.

This is a second line, not the first. The pool is configured for
ADMIN-INVITE ONLY, so self sign-up is closed and this trigger exists to
catch a future change that opens it. Both are needed: the invite setting
is a console toggle somebody can flip.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Comma-separated, lowercase, no leading @. Set from CDK.
ALLOWED = {
    d.strip().lower().lstrip("@")
    for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",")
    if d.strip()
}


def handler(event, _context):
    email = (event.get("request", {}).get("userAttributes", {}).get("email") or "").lower()
    domain = email.rpartition("@")[2]

    if not ALLOWED:
        # Fail CLOSED. An empty allow-list means the deployment is
        # misconfigured, and the safe reading of "no domains are
        # permitted" is none -- not all.
        logger.error("ALLOWED_EMAIL_DOMAINS is empty; refusing sign-up")
        raise Exception("Sign-up is not available.")

    if domain not in ALLOWED:
        # The address is not logged. It is the identifier of a person who
        # tried to sign up and failed, and it has no operational use.
        logger.info("rejected sign-up for domain %r", domain)
        raise Exception("Sign-up is restricted to company email addresses.")

    return event
