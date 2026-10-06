"""The refusal a service raises with a message code and the status it answers."""


class CodedError(Exception):
    """A refusal carrying a ``messages.py`` code and its HTTP status.

    Services raise it rather than ``HTTPException`` so they stay callable from a
    job or a worker; ``app.main`` answers any that reaches the API with
    ``{"detail": code}`` at ``status_code``. A subclass sets its own default
    status as a class attribute.
    """

    status_code: int = 400

    def __init__(self, code: str, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        if status_code is not None:
            self.status_code = status_code
