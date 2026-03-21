"""Shared exception types for slopmop."""


class MissingDependencyError(ImportError):
    """A required dependency is not installed.

    Raised at command-call time (not import time) so that unrelated
    verbs still work when only one verb's dependency is missing.
    The top-level CLI entry point catches this and prints a
    human-readable diagnostic instead of a raw traceback.
    """

    def __init__(self, package: str, verb: str, reason: str = "") -> None:
        self.package = package
        self.verb = verb
        detail = f" ({reason})" if reason else ""
        super().__init__(
            f"The '{verb}' command requires the '{package}' package{detail}.\n"
            f"\n"
            f"  pip install {package}\n"
            f"\n"
            f"If you installed slopmop via pipx:\n"
            f"\n"
            f"  pipx inject slopmop {package}\n"
            f"\n"
            f"This will be fixed in the next release. "
            f"Run 'sm doctor' (when available) for full diagnostics."
        )
