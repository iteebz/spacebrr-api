class SpaceError(Exception):
    status_code: int = 500


class NotFoundError(SpaceError):
    status_code = 404


class ConflictError(SpaceError):
    status_code = 409


class ValidationError(SpaceError):
    status_code = 400


class StateError(SpaceError):
    status_code = 409


class PermissionError(SpaceError):
    status_code = 403


class ReferenceError(SpaceError):
    status_code = 400

    def __init__(self, ref: str, count: int, sample: list[str] | None = None):
        self.ref = ref
        self.count = count
        self.sample = sample or []
        sample_note = f" (examples: {', '.join(self.sample)})" if self.sample else ""
        super().__init__(f"Ambiguous reference '{ref}' matches {count} items{sample_note}")
