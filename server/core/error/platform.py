from typing import Optional

from core.error import BaseError


class PlatformBadRequest(BaseError):
    def __init__(self, description: Optional[str] = None):
        super().__init__(description)
        self.status_code = 400


class PlatformForbidden(BaseError):
    def __init__(self, description: Optional[str] = None):
        super().__init__(description)
        self.status_code = 403


class PlatformNotFound(BaseError):
    def __init__(self, description: Optional[str] = None):
        super().__init__(description)
        self.status_code = 404
