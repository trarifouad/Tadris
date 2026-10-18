class BusinessRuleError(Exception):
    """Raised when a domain rule is violated. Message is French and user-facing."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PermissionDenied(BusinessRuleError):
    pass


class NotFound(BusinessRuleError):
    pass


class ValidationError(BusinessRuleError):
    pass
