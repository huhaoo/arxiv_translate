class ArxivTranslateError(Exception):
    """Base class for user-facing errors."""


class InvalidArxivLinkError(ArxivTranslateError):
    """Raised when an input cannot be parsed as an arXiv identifier."""


class SourceUnavailableError(ArxivTranslateError):
    """Raised when arXiv does not provide TeX source for the paper."""


class CompilationError(ArxivTranslateError):
    """Raised when LaTeX compilation fails."""


class DeepSeekError(ArxivTranslateError):
    """Raised when the DeepSeek-compatible API returns an error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        protocol_violation: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.protocol_violation = protocol_violation
