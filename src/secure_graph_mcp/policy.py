"""Privacy and permission policy for graph properties."""

import re
from typing import Optional, Tuple


PUBLIC_PERMISSION = None

SENSITIVE_KEY_PERMISSIONS = {
    "ssn": ("restricted", "pii.ssn.read"),
    "social_security_number": ("restricted", "pii.ssn.read"),
    "passport_number": ("restricted", "pii.passport.read"),
    "dob": ("confidential", "pii.dob.read"),
    "date_of_birth": ("confidential", "pii.dob.read"),
    "diagnosis": ("restricted", "medical.diagnosis.read"),
    "medical_record": ("restricted", "medical.record.read"),
    "bank_account": ("secret", "finance.bank_account.read"),
    "account_number": ("secret", "finance.account_number.read"),
    "routing_number": ("secret", "finance.routing_number.read"),
}

EDGE_TYPE_SENSITIVITY = {
    # Relationship types that imply sensitive linkage even without properties.
    "treated_by": ("restricted", "medical.treated_by.read"),
    "married_to": ("confidential", "relationship.married_to.read"),
    "owns_account": ("secret", "finance.account_ownership.read"),
}

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
EMAIL_RE = re.compile(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b")


def classify_property(
    key: str,
    value: str,
    privacy_level: Optional[str] = None,
    required_permission: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Return a conservative privacy level and permission for a field.

    The AI may propose labels, but deterministic rules can upgrade sensitive
    fields so obvious PII does not accidentally become public.
    """
    normalized_key = key.strip().lower()
    value_text = str(value)

    if normalized_key in SENSITIVE_KEY_PERMISSIONS:
        return SENSITIVE_KEY_PERMISSIONS[normalized_key]

    if SSN_RE.search(value_text):
        return "restricted", "pii.ssn.read"

    if EMAIL_RE.search(value_text):
        proposed_level = privacy_level or "internal"
        proposed_permission = required_permission or "profile.email.read"
        return proposed_level, proposed_permission

    return privacy_level or "public", required_permission or PUBLIC_PERMISSION


def classify_edge(
    edge_type: str,
    privacy_level: Optional[str] = None,
    required_permission: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Return a conservative privacy level and permission for an edge type."""
    normalized_type = edge_type.strip().lower()
    if normalized_type in EDGE_TYPE_SENSITIVITY:
        hint_level, hint_permission = EDGE_TYPE_SENSITIVITY[normalized_type]
        return privacy_level or hint_level, required_permission or hint_permission
    return privacy_level or "public", required_permission or PUBLIC_PERMISSION


def can_read_property(required_permission: Optional[str], permissions: set) -> bool:
    """Return whether a permission set can read a property."""
    return required_permission is None or required_permission in permissions
