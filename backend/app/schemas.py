"""Pydantic request/response models = the API contract documented in docs/LLD.md."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CategoryKey = Literal["credit_reporting", "debt_collection", "mortgage", "credit_card", "bank_account",
                      "student_loan", "vehicle_consumer_loan", "payday_personal_loan", "money_transfer"]


class PredictRequest(BaseModel):
    text: str = Field(..., description="Complaint narrative written by the customer", examples=[
        "Someone opened a credit card in my name and the bank keeps charging me for purchases I never made."])
    top_k_similar: int = Field(3, ge=0, le=10, description="How many similar past complaints to return")

    @field_validator("text")
    @classmethod
    def text_must_have_words(cls, v: str) -> str:
        v = v.strip()
        if sum(ch.isalpha() for ch in v) < 10:
            raise ValueError("Complaint text must contain at least a few words")
        return v


class BatchPredictRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, description="Up to 50 complaint narratives")


class Alternative(BaseModel):
    category: str
    category_label: str
    probability: float


class TermWeight(BaseModel):
    term: str
    weight: float


class SimilarComplaint(BaseModel):
    complaint_id: str
    similarity: float
    category: str | None = None
    category_label: str | None = None
    priority: str
    issue: str | None = ""
    date_received: str | None = ""
    company_response: str | None = ""
    snippet: str


class TextStats(BaseModel):
    n_chars: int
    n_tokens: int
    oov_rate: float


class PredictResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    prediction_id: str
    category: str
    category_label: str
    team: str
    confidence: float = Field(..., ge=0, le=1)
    low_confidence: bool
    alternatives: list[Alternative]
    priority: Literal["high", "normal"]
    priority_score: float
    priority_threshold: float
    priority_reasons: list[str]
    explanation: list[TermWeight]
    similar_complaints: list[SimilarComplaint]
    text_stats: TextStats
    model_version: str | None
    latency_ms: float


class BatchPredictResponse(BaseModel):
    results: list[PredictResponse]


class FeedbackRequest(BaseModel):
    prediction_id: str
    complaint_text: str = Field(..., min_length=20, max_length=10000)
    predicted_category: CategoryKey
    correct_category: CategoryKey
    predicted_priority: Literal["high", "normal"] | None = None
    correct_priority: Literal["high", "normal"] | None = None


class FeedbackResponse(BaseModel):
    stored: bool
    message: str


class CategoryInfo(BaseModel):
    key: str
    label: str
    team: str
    description: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: Literal["ok", "degraded"]
    model_server: Literal["up", "down"]
    model_version: str | None
    mlflow: Literal["up", "down", "unknown"]
    uptime_seconds: float


class RetrainRequest(BaseModel):
    reason: str = Field("manual retrain from pipeline console", max_length=200)


class ErrorResponse(BaseModel):
    detail: str
