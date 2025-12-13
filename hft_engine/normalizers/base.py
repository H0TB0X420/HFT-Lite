"""
Abstract base class for exchange normalizers.
"""
from abc import ABC, abstractmethod

from ..core.normalized_tick import NormalizedTick

class BaseNormalizer(ABC):
    """Abstract normalizer interface."""
    
    @abstractmethod
    def normalize(self, raw_message: dict) -> NormalizedTick | None:
        """
        Convert raw exchange message to NormalizedTick.
        
        Returns None if message cannot be normalized (e.g., non-tick message).
        """
        pass
