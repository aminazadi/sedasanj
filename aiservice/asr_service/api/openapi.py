"""Reusable OpenAPI response declarations for consistent ReDoc output."""

from .schemas.common import ErrorResponse, ValidationErrorResponse

AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "The bearer API key is missing or invalid."},
    503: {"model": ErrorResponse, "description": "The service is not configured or temporarily unavailable."},
}
VALIDATION_ERROR = {
    422: {"model": ValidationErrorResponse, "description": "The request does not satisfy the documented schema."}
}


def documented_responses(*, include_validation: bool = False, **responses):
    """Combine common authentication errors with endpoint-specific responses."""

    result = dict(AUTH_ERRORS)
    if include_validation:
        result.update(VALIDATION_ERROR)
    result.update({int(code): value for code, value in responses.items()})
    return result
