"""
Sync resume_data.json -> MongoDB `user_resume`.

Whenever you edit resume_data.json (add a skill, change a value, add a
search_role, etc.), run this to push the changes into the DB so both stay
consistent:

    python sync_resume.py

It upserts the whole profile (creating user_resume if it doesn't exist) and
prints what changed.
"""

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from database import _get_db_objects

RESUME_JSON = Path(__file__).with_name("resume_data.json")


def main():
    data = json.loads(RESUME_JSON.read_text(encoding="utf-8"))
    _, _, resume = _get_db_objects()

    before = resume.find_one({}, {"_id": 0}) or {}
    resume.update_one({}, {"$set": data}, upsert=True)
    after = resume.find_one({}, {"_id": 0}) or {}

    before_skills = set(map(str.lower, before.get("skills") or []))
    added = [s for s in (data.get("skills") or []) if s.lower() not in before_skills]

    print(f"✅ Synced resume_data.json -> user_resume ({len(after)} fields).")
    print(f"   Skills now: {after.get('skills')}")
    if added:
        print(f"   ➕ New skills added: {added}")
    print(f"   search_roles: {after.get('search_roles')}")


if __name__ == "__main__":
    main()
