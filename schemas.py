"""
Database Schemas for Ethics & Compliance Training Platform

Each Pydantic model maps to a MongoDB collection with the lowercase name of the class.
Examples:
- Learner -> "learner"
- Course -> "course"
- Statement -> "statement"
- Progress -> "progress"
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr

# Learner accounts (corporate users)
class Learner(BaseModel):
    external_id: str = Field(..., description="External account ID (e.g., SSO subject or HRIS key)")
    name: str = Field(..., description="Full name")
    email: Optional[EmailStr] = Field(None, description="Work email")
    department: Optional[str] = Field(None, description="Department or business unit")
    role: Optional[str] = Field(None, description="Job role or title")
    is_active: bool = Field(default=True)

# Course catalog entries
class Course(BaseModel):
    course_id: str = Field(..., description="Stable course identifier")
    title: str = Field(..., description="Course title")
    description: Optional[str] = Field(None, description="Short description")
    duration_minutes: Optional[int] = Field(None, ge=0)
    level: Optional[str] = Field(None, description="Beginner / Intermediate / Advanced / All Levels")
    tags: list[str] = Field(default_factory=list)
    published: bool = Field(default=True)

# Minimal xAPI statement storage model
class Statement(BaseModel):
    actor: Dict[str, Any] = Field(..., description="xAPI actor object")
    verb: Dict[str, Any] = Field(..., description="xAPI verb object")
    object: Dict[str, Any] = Field(..., description="xAPI object (activity)")
    result: Optional[Dict[str, Any]] = Field(None, description="xAPI result (score, success, completion)")
    context: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp from client")
    stored_by: str = Field("api", description="Who stored this statement")

# Denormalized learner progress per course
class Progress(BaseModel):
    learner_external_id: str = Field(..., description="Learner external ID")
    course_id: str = Field(..., description="Course identifier")
    status: str = Field("in_progress", description="in_progress | completed")
    score: Optional[int] = Field(None, ge=0, le=100)
    success: Optional[bool] = None
    last_statement_timestamp: Optional[str] = None
