"""Interactive, server-only administrator creation; no default credentials."""
import getpass
from sqlalchemy import select
from .db import SessionLocal
from .models import User,Team
from .security import hasher

def main():
    email=input("Admin email: ").strip().lower()
    password=getpass.getpass("Password (minimum 12 characters): ")
    if len(password)<12: raise SystemExit("Password too short")
    if getpass.getpass("Confirm password: ")!=password: raise SystemExit("Passwords differ")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email==email)): raise SystemExit("Email already registered; use a new organizer email")
        team=Team(name="ADMIN organizers");db.add(team);db.flush()
        db.add(User(email=email,password_hash=hasher.hash(password),display_name="ADMIN",team_id=team.id,role="ADMIN"));db.commit()
    print("Administrator created")
if __name__=="__main__": main()
