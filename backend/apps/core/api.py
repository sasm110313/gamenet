"""Consistent JSON error envelope for the device/edge APIs."""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class ApiError(APIException):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(detail=message, code=code)


class AuthenticationFailed(ApiError):
    def __init__(self, message: str = "invalid credentials"):
        super().__init__("authentication_failed", message, status.HTTP_401_UNAUTHORIZED)


class Conflict(ApiError):
    def __init__(self, message: str):
        super().__init__("conflict", message, status.HTTP_409_CONFLICT)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, ApiError):
        code, message = exc.code, exc.message
    elif isinstance(exc, APIException):
        code = getattr(exc, "default_code", "error")
        detail = exc.detail
        message = detail if isinstance(detail, str) else str(detail)
    else:  # pragma: no cover
        code, message = "error", str(exc)
    response.data = {"error": {"code": code, "message": message}}
    return response
