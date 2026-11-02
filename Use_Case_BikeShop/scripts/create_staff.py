"""
Create a staff user, or promote an existing user to staff (SPEC §3).
There is deliberately no API endpoint for this.

    python -m scripts.create_staff --username anna --email anna@bikeshop.test

The password comes from the STAFF_PASSWORD environment variable, or is asked
for. It is only needed when the user doesn't exist yet.
"""
import argparse
import getpass
import os

from sqlmodel import Session, select

from api.database import engine, init_database
from api.models.models import Role, User
from api.services.auth_service import AuthService


def create_or_promote(db: Session, username: str, email: str, password: str | None) -> User:
    user = db.exec(select(User).where(User.username == username)).first()
    if user:
        user.role = Role.staff
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    if not password or len(password) < 10:
        raise SystemExit("A new user needs a password of at least 10 characters.")
    user = AuthService().register_user(username, email, password, db, role=Role.staff)
    if not user:
        raise SystemExit(f"The email {email} is already used by another account.")
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    init_database()
    with Session(engine) as db:
        exists = db.exec(select(User).where(User.username == args.username)).first()
        password = None if exists else (os.getenv("STAFF_PASSWORD") or getpass.getpass("Password: "))
        user = create_or_promote(db, args.username, args.email, password)
    print(f"{user.username} is staff.")


if __name__ == "__main__":
    main()
