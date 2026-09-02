class VeriDeployError(Exception):
    """Base application exception."""

class ConfigurationError(VeriDeployError):
    """Raised when runtime configuration is invalid."""

class DependencyUnavailableError(VeriDeployError):
    """Raised when a required downstream dependency is unavailable."""
