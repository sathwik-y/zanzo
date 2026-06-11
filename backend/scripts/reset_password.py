"""Reset a user's password from the server (no email needed on self-hosted).

Usage:
    python -m scripts.reset_password you@example.com [new-password]

If no password is given, a random one is generated and printed once.
"""
import secrets
import sys

from sqlalchemy import select

from recall.auth import hash_password
from recall.db import get_session_factory
from recall.models import User


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    email = sys.argv[1].lower()
    password = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(12)
    if len(password) < 8:
        print("password must be at least 8 characters")
        return 2

    with get_session_factory()() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"no account with email {email}")
            return 1
        user.password_hash = hash_password(password)
        db.commit()
    print(f"password reset for {email}")
    if len(sys.argv) < 3:
        print(f"temporary password: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
