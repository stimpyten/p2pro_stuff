"""Standalone thermal utilities — no camera or USB dependencies.

Safe to import on any host (server, Pi without camera, tests).
"""


def thermal_to_celsius(raw_value: float) -> float:
    """Convert raw 16-bit thermal value to degrees Celsius."""
    return round((float(raw_value) / 64.0) - 273.15, 1)
