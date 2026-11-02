"""Safe, observable COM automation for Aspen Plus V14."""

from .session import AspenConnectionError, AspenSession, LaunchOptions, validate_backup

__all__ = ["AspenConnectionError", "AspenSession", "LaunchOptions", "validate_backup"]
