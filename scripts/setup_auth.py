"""
Interactive script to set up auth credentials for Y7 Dispatch.

Generates bcrypt password hash and JWT secret, then outputs env vars
to paste into .env file.

Usage:
    python scripts/setup_auth.py
"""

import secrets
import sys

def main():
    try:
        import bcrypt
    except ImportError:
        print("Error: bcrypt not installed. Run: pip install bcrypt")
        sys.exit(1)

    print("=" * 50)
    print("  Y7 Dispatch — Auth Setup")
    print("=" * 50)
    print()

    # Username
    username = input("Username [sergii]: ").strip() or "sergii"

    # Password
    password = input("Password: ").strip()
    if not password:
        print("Error: Password cannot be empty")
        sys.exit(1)

    confirm = input("Confirm password: ").strip()
    if password != confirm:
        print("Error: Passwords don't match")
        sys.exit(1)

    # Generate hash and secret
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    jwt_secret = secrets.token_hex(32)

    print()
    print("-" * 50)
    print("Add these to your .env file:")
    print("-" * 50)
    print()
    print(f"AUTH_USERNAME={username}")
    print(f"AUTH_PASSWORD_HASH={password_hash}")
    print(f"JWT_SECRET={jwt_secret}")
    print("JWT_EXPIRE_HOURS=24")
    print("COOKIE_SECURE=true")
    print()
    print("-" * 50)
    print("For production, also set:")
    print(f"CORS_ORIGINS=https://yourdomain.com")
    print("-" * 50)


if __name__ == "__main__":
    main()
