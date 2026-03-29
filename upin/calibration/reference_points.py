"""
Reference Points — UPIN Calibration Module

Known geographic reference points used to calibrate sensor drift.
When UPIN passes near a reference point with known coordinates,
it compares sensor readings to ground truth and updates bias models.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations
