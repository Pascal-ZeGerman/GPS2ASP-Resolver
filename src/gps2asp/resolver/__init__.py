"""GPS2ASP resolver public API - placeholder until Task 3 assembles the full pipeline."""

from gps2asp.resolver.converter import convert

# resolve and resolve_segment will be implemented in Task 3
__all__ = ["convert"]


async def resolve(lat: float, lon: float, **kwargs):
    """Placeholder - implemented in Task 3."""
    raise NotImplementedError("resolve() will be assembled in Task 3")


async def resolve_segment(x: float, y: float, **kwargs):
    """Placeholder - implemented in Task 3."""
    raise NotImplementedError("resolve_segment() will be assembled in Task 3")
