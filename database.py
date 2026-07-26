import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

load_dotenv()

# Fields that identify a job regardless of its link. Two postings with the
# same title/company/location/salary/rating are treated as the SAME job even
# if their link differs (Naukri links often carry changing tracking params).
FINGERPRINT_FIELDS = ("title", "company", "location", "salary", "rating")


def job_fingerprint(doc):
    """Builds a normalized content fingerprint from a job dict (link-independent)."""
    def norm(value):
        return re.sub(r"\s+", " ", str(value if value is not None else "")).strip().lower()
    return "|".join(norm(doc.get(field)) for field in FINGERPRINT_FIELDS)

MONGO_URI = os.getenv("MONGO_URI")
# `or` guards against empty-string env vars injected by CI for unset secrets.
DB_NAME = os.getenv("MONGO_DB_NAME") or "JobPortalBot"
RESUME_COLLECTION_NAME = os.getenv("MONGO_RESUME_COLLECTION") or "user_resume"
LOCAL_STORAGE_PATH = Path(__file__).with_name("resume_data.json")

client = None
db = None
resume_collection = None

def _get_db_objects():
    global client, db, resume_collection
    if client is None:
        if not MONGO_URI:
            raise RuntimeError("MONGO_URI is not set.")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        resume_collection = db[RESUME_COLLECTION_NAME]
    return client, db, resume_collection


def _merge_data(old_data, new_data):
    """
    Merges new_data into old_data.
    - If a field is a list (like skills), it appends and removes duplicates.
    - If a field is a single value, it overwrites/adds.
    """
    merged = old_data.copy() if old_data else {}

    for key, value in new_data.items():
        # CASE 1: Both are lists (e.g., Skills) -> Append and remove duplicates
        if key in merged and isinstance(merged[key], list) and isinstance(value, list):
            merged[key] = list(set(merged[key] + value))
        # CASE 2: Key is new OR it's a single value -> Add/Overwrite
        else:
            merged[key] = value
            
    return merged


def get_resume_data(storage_path=None):
    """Loads and combines existing data from BOTH MongoDB and Local File so nothing is lost."""
    path = Path(storage_path or LOCAL_STORAGE_PATH)
    
    local_data = {}
    db_data = {}

    # 1. Load from Local File first
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            try:
                local_data = json.load(handle)
            except json.JSONDecodeError:
                local_data = {}

    # 2. Load from MongoDB
    try:
        _get_db_objects()
        data = resume_collection.find_one({}, {"_id": 0})
        if data:
            db_data = data
    except Exception:
        pass # If DB fails, we still have local_data

    # 3. MERGE BOTH: Taaki local aur DB ka data mix ho jaye aur koi key delete na ho
    combined_existing_data = _merge_data(local_data, db_data)
    return combined_existing_data


def save_resume_data(new_data, storage_path=None):
    """Merges new data into the single dictionary and saves it."""
    path = Path(storage_path or LOCAL_STORAGE_PATH)
    
    # 1. Get combined existing data (Local + MongoDB)
    existing_data = get_resume_data(storage_path)
    
    # 2. Merge the incoming new_data into it
    updated_data = _merge_data(existing_data, new_data)
    
    # 3. Save to MongoDB
    try:
        _get_db_objects()
        # Single document ko update/upsert karega
        resume_collection.update_one(
            {}, 
            {"$set": updated_data}, 
            upsert=True
        )
        print("✅ Resume data merged and saved to MongoDB!")
        
        # Also update local backup file
        with path.open("w", encoding="utf-8") as f:
            json.dump(updated_data, f, indent=2)
        return True

    except (OperationFailure, PyMongoError, RuntimeError, ConnectionError) as exc:
        # If DB fails, local JSON file update is guaranteed
        with path.open("w", encoding="utf-8") as f:
            json.dump(updated_data, f, indent=2)
        print(f"⚠️ MongoDB save failed: {exc}. Data safely saved locally at {path}")
        return False