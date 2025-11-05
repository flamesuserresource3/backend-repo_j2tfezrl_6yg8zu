import os
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone

from database import db, create_document, get_documents
from schemas import Course as CourseSchema, Statement as StatementSchema, Progress as ProgressSchema

app = FastAPI(title="Ethics & Compliance Training API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Health & Diagnostics
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "Ethics & Compliance Training API"}

@app.get("/test")
def test_database():
    """Verify database connectivity and list collections"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = getattr(db, 'name', None) or os.getenv("DATABASE_NAME") or "❌ Not Set"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:20]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response

# -----------------------------
# Course Catalog
# -----------------------------
class CourseCreate(BaseModel):
    course_id: str
    title: str
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    level: Optional[str] = None
    tags: List[str] = []
    published: bool = True

@app.get("/courses")
def list_courses() -> List[Dict[str, Any]]:
    items = get_documents("course", {})
    if not items:
        # Provide a default seed catalog for first run visibility
        seed = [
            {
                "course_id": "c-ethics-101",
                "title": "Ethics Fundamentals",
                "description": "Core principles of ethical decision-making in the workplace.",
                "duration_minutes": 45,
                "level": "Beginner",
                "tags": ["ethics", "culture"],
                "published": True,
            },
            {
                "course_id": "c-privacy-gdpr",
                "title": "Data Privacy & GDPR",
                "description": "Understand data protection, privacy by design, and GDPR basics.",
                "duration_minutes": 60,
                "level": "Intermediate",
                "tags": ["privacy", "gdpr"],
                "published": True,
            },
            {
                "course_id": "c-anti-bribery",
                "title": "Anti-Bribery & Corruption",
                "description": "Recognize risk, report concerns, and comply with ABAC policies.",
                "duration_minutes": 40,
                "level": "Intermediate",
                "tags": ["abac", "risk"],
                "published": True,
            },
            {
                "course_id": "c-code-of-conduct",
                "title": "Code of Conduct",
                "description": "Company standards for professional behavior and integrity.",
                "duration_minutes": 35,
                "level": "All Levels",
                "tags": ["conduct"],
                "published": True,
            },
        ]
        for c in seed:
            try:
                create_document("course", CourseSchema(**c))
            except Exception:
                pass
        items = get_documents("course", {})
    # Normalize ObjectId to string
    for it in items:
        it["_id"] = str(it.get("_id"))
    return items

@app.post("/courses")
def create_course(payload: CourseCreate):
    course_id = create_document("course", CourseSchema(**payload.model_dump()))
    return {"id": course_id}

# -----------------------------
# xAPI Statements (Tin Can API)
# -----------------------------
@app.post("/xapi/statements")
def record_statement(statement: StatementSchema):
    """Store an xAPI statement as-is while adding server timestamp."""
    data = statement.model_dump()
    data["received_at"] = datetime.now(timezone.utc)

    # Basic derivation for convenience fields
    actor_account = (
        data.get("actor", {}).get("account", {}).get("name")
        or data.get("actor", {}).get("mbox")
        or data.get("actor", {}).get("openid")
    )
    activity_id = data.get("object", {}).get("id")
    data["_learner_external_id"] = actor_account
    data["_course_id"] = activity_id.split("/")[-1] if isinstance(activity_id, str) else None

    inserted_id = create_document("statement", data)

    # Maintain a denormalized progress record for quick dashboards
    try:
        update_progress_from_statement(data)
    except Exception:
        # Non-critical: progress denormalization failure should not break ingestion
        pass

    return {"id": inserted_id}

@app.get("/xapi/statements")
def get_statements(user_id: Optional[str] = Query(default=None), limit: int = Query(default=50, ge=1, le=500)):
    filt: Dict[str, Any] = {}
    if user_id:
        # Filter on convenience field set during ingestion
        filt["_learner_external_id"] = user_id
    items = get_documents("statement", filt, limit=limit)
    for it in items:
        it["_id"] = str(it.get("_id"))
    return items

# -----------------------------
# Progress & Reporting
# -----------------------------
@app.get("/progress/{learner_external_id}")
def get_progress(learner_external_id: str):
    # Prefer denormalized collection, but compute from statements if needed
    progress_items = get_documents("progress", {"learner_external_id": learner_external_id})
    if progress_items:
        for p in progress_items:
            p["_id"] = str(p.get("_id"))
        return {"learner_external_id": learner_external_id, "items": progress_items}

    # Fallback: compute from statements
    statements = get_documents("statement", {"_learner_external_id": learner_external_id})
    computed: Dict[str, Dict[str, Any]] = {}
    for st in statements:
        course_id = st.get("_course_id") or st.get("object", {}).get("id")
        if isinstance(course_id, str) and "/" in course_id:
            course_id = course_id.split("/")[-1]
        verb = st.get("verb", {}).get("display", {}).get("en-US") or st.get("verb", {}).get("id")
        result = st.get("result") or {}
        score = None
        if isinstance(result, dict):
            sc = result.get("score")
            if isinstance(sc, dict):
                scaled = sc.get("scaled")
                if isinstance(scaled, (int, float)):
                    score = int(round(scaled * 100))
        rec = computed.setdefault(course_id, {"course_id": course_id, "status": "in_progress", "score": None, "success": None, "last_statement_timestamp": st.get("timestamp")})
        # Update with the latest timestamp if present
        rec["last_statement_timestamp"] = st.get("timestamp") or rec.get("last_statement_timestamp")
        if score is not None:
            rec["score"] = score
        if isinstance(result, dict):
            if "success" in result:
                rec["success"] = bool(result.get("success"))
            if result.get("completion") or (verb and "completed" in str(verb)):
                rec["status"] = "completed"
    items = list(computed.values())
    return {"learner_external_id": learner_external_id, "items": items}

# Helper: update denormalized progress

def update_progress_from_statement(st: Dict[str, Any]):
    learner_id = st.get("_learner_external_id")
    course_id = st.get("_course_id")
    if not learner_id or not course_id:
        return

    result = st.get("result") or {}
    score = None
    if isinstance(result, dict):
        sc = result.get("score")
        if isinstance(sc, dict) and isinstance(sc.get("scaled"), (int, float)):
            score = int(round(sc["scaled"] * 100))
    success = bool(result.get("success")) if isinstance(result, dict) and "success" in result else None
    status = "completed" if (isinstance(result, dict) and result.get("completion")) else "in_progress"
    last_ts = st.get("timestamp")

    # Upsert progress document
    app_logger = getattr(app, "logger", None)
    from pymongo import ReturnDocument
    db.progress.find_one_and_update(
        {"learner_external_id": learner_id, "course_id": course_id},
        {
            "$set": {
                "learner_external_id": learner_id,
                "course_id": course_id,
                "status": status,
                "score": score,
                "success": success,
                "last_statement_timestamp": last_ts,
                "updated_at": datetime.now(timezone.utc),
            },
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
