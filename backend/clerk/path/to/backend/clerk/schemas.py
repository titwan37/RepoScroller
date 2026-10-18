"""Pydantic models for Swiss administrative forms."""
from enum import Enum
from typing import Any, List, Optional
import re
from datetime import date

from pydantic import BaseModel, Field, field_validator


class FormRunStatus(str, Enum):
    """Enum for form processing status."""
    PENDING = "pending"
    ANALYZING = "analyzing"
    RETRIEVING = "retrieving"
    ANSWER_PROPOSED = "answer_proposed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    EXPORTED = "exported"


class FieldContract(BaseModel):
    """Base contract for form field definitions."""
    field_id: str
    label: str
    canonical_question: str
    expected_type: str
    jurisdiction: str
    required: bool = False
    freshness_policy: Optional[str] = None
    evidence_required: bool = False
    validation_rules: List[dict] = []

    @field_validator("expected_type")
    @classmethod
    def validate_expected_type(cls, v):
        if v not in ["string", "integer", "float", "date", "boolean"]:
            raise ValueError(f"Invalid expected_type: {v}")
        return v


class AHVNumberContract(BaseModel):
    """Swiss 13-digit AHV number contract with regex validation."""
    ahv_number: str = Field(..., description="Swiss 13-digit AHV number")

    @field_validator("ahv_number")
    @classmethod
    def validate_ahv_number(cls, v):
        pattern = r"^756\.\d{4}\.\d{4}\.\d{2}$"
        if not re.match(pattern, v):
            raise ValueError(f"Invalid AHV number format. Expected: {pattern}")
        return v


class CHFCurrencyContract(BaseModel):
    """CHF currency contract with non-negative amounts and 5-centime rounding."""
    amount: float = Field(..., ge=0, description="CHF amount")

    @field_validator("amount")
    @classmethod
    def validate_currency_rounding(cls, v):
        # Round to nearest 5 centimes (0.05 CHF)
        rounded = round(v / 0.05) * 0.05
        if rounded != v:
            raise ValueError(f"Amount must be a multiple of 0.05 CHF")
        return rounded


class DateFieldContract(BaseModel):
    """Swiss date format contract (DD.MM.YYYY)."""
    date_value: str = Field(..., description="Date in DD.MM.YYYY format")

    @field_validator("date_value")
    @classmethod
    def validate_date_format(cls, v):
        pattern = r"^\d{2}\.\d{2}\.\d{4}$"
        if not re.match(pattern, v):
            raise ValueError(f"Invalid date format. Expected: {pattern}")
        try:
            day, month, year = map(int, v.split("."))
            if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100):
                raise ValueError(f"Invalid date values")
        except ValueError:
            raise ValueError(f"Invalid date format. Expected: {pattern}")
        return v


class AnswerProposal(BaseModel):
    """Form answer proposal structure."""
    proposed_value: Any = None
    confidence_relevance: float = Field(..., ge=0, le=1)
    confidence_authority: float = Field(..., ge=0, le=1)
    confidence_freshness: float = Field(..., ge=0, le=1)
    evidence_list: List[str] = []
    requires_review: bool = False

    @field_validator("proposed_value")
    @classmethod
    def validate_proposed_value(cls, v):
        if v is not None and (not isinstance(v, (str, int, float, bool))):
            raise ValueError(f"Invalid proposed_value type. Must be str, int, float, or bool")
        return v


class FormRunStatus(BaseModel):
    """Form run status model."""
    status: FormRunStatus = Field(..., description="Current form processing status")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in FormRunStatus.__members__.values():
            raise ValueError(f"Invalid status. Must be one of: {list(FormRunStatus)}")
        return v
