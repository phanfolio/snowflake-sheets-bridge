"""Exception types shared by the pipeline."""


class PipelineError(Exception):
    """An expected failure whose message is safe to print in public CI logs."""
