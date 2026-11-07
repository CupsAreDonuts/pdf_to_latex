"""Domain-specific exceptions with readable messages."""


class PipelineError(RuntimeError):
    """Base class for errors that should be shown to the user."""


class DependencyError(PipelineError):
    """A required external program or Python package is missing."""


class ConfigError(PipelineError):
    """Invalid command-line configuration or environment."""


class PdfError(PipelineError):
    """The PDF could not be inspected or rendered."""


class ApiError(PipelineError):
    """The vision API failed after all retries."""


class CompileError(PipelineError):
    """A LaTeX fragment or the assembled document did not compile."""
