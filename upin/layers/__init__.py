"""
UPIN Navigation and Positioning Layers.

60 independent layers organized into 11 groups (A-K),
each operating on a fundamentally different physical principle.
"""

from upin.layers.registry import LayerRegistry, create_all_layers

__all__ = ["LayerRegistry", "create_all_layers"]
