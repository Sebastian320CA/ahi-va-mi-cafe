"""Domain errors carry a user-facing Spanish message and an HTTP-like status code."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str, *, code: str = "domain_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotFound(DomainError):
    status_code = 404


class Forbidden(DomainError):
    status_code = 403


class Conflict(DomainError):
    status_code = 409


class ValidationFailed(DomainError):
    status_code = 422
