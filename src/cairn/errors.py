"""User-facing error types. Messages are safe to print to a terminal."""


class CairnError(Exception):
    """Base class for errors cairn reports to the user."""


class CairnInputError(CairnError):
    """A user-editable input file (config, relations, authored) is invalid."""

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"{path}: {detail}")
        self.path = path
        self.detail = detail


class WorkspaceStoreError(CairnError):
    """The generated workspace map is unreadable or from an unsupported version."""
