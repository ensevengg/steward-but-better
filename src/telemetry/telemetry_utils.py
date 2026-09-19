"""Telemetry estimates with explicit units, bounded joins and missing values."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

G_ACCELERATION = 9.81


def timedelta_to_seconds(td: Any) -> float:
    if td is None:
        raise ValueError("Missing timestamp")
    if hasattr(td, "total_seconds"):
        return float(td.total_seconds())
    if isinstance(td, np.timedelta64):
        return float(td / np.timedelta64(1, "s"))
    return float(td)


def ensure_time_seconds(df, source_col="Time"):
    if "TimeSeconds" not in df.columns and source_col in df.columns:
        df["TimeSeconds"] = df[source_col].apply(timedelta_to_seconds)
    return df


def find_overlap_region(a, b, column="DistanceOffset"):
    if a.empty or b.empty or column not in a or column not in b:
        return None
    start, end = max(a[column].min(), b[column].min()), min(a[column].max(), b[column].max())
    return (start, end) if start < end else None


def compute_g_forces(df, smoothing_window=5):
    """Causal trailing estimate; signed longitudinal G; unknown stays NaN.

    Position direction is a public-feed estimate, not collision-grade geometry.
    No interpolation over holes, duplicate times, or future samples.
    """
    df = df.copy()
    df["lateral_g"] = np.nan
    df["longitudinal_g"] = np.nan
    df["lateral_g_available"] = False
    source = "SessionTime" if "SessionTime" in df else "Time"
    ensure_time_seconds(df, source)
    if len(df) < 2 or "Speed" not in df or "TimeSeconds" not in df:
        return df
    t = df["TimeSeconds"].to_numpy(float)
    if not np.isfinite(t).all() or (np.diff(t) <= 0).any():
        raise ValueError("Telemetry timestamps must be finite and strictly increasing")
    speed = df["Speed"].astype(float) / 3.6
    dt = pd.Series(t, index=df.index).diff()
    valid_dt = dt.where(dt <= 1.0)
    longitudinal = speed.diff() / valid_dt / G_ACCELERATION
    df["longitudinal_g"] = longitudinal.where(longitudinal.abs() <= 12)
    if not {"X", "Y"}.issubset(df.columns):
        return df
    window = max(1, smoothing_window)
    x = df["X"].rolling(window, min_periods=window).mean()
    y = df["Y"].rolling(window, min_periods=window).mean()
    dx, dy = x.diff(), y.diff()
    heading = pd.Series(np.arctan2(dy, dx), index=df.index).where((dx.abs() + dy.abs()) > 0)
    # Wrap the angular difference instead of unwrapping across missing segments.
    delta = (heading.diff() + np.pi) % (2 * np.pi) - np.pi
    lateral = (speed * delta / valid_dt / G_ACCELERATION).abs()
    df["lateral_g"] = lateral.where(lateral <= 12)
    df["lateral_g_available"] = df["lateral_g"].notna()
    return df


def merge_position_channels(df, pos_df, on="SessionTime", tolerance_s=0.3, position_units="decimetres"):
    """Backward-only join of FastF1 position samples; normalize units once."""
    if position_units not in {"decimetres", "metres"}:
        raise ValueError("Explicit position units required")
    if pos_df is None or pos_df.empty or not {on, "X", "Y"}.issubset(pos_df.columns) or on not in df:
        return df.copy()
    left = df.drop(columns=[c for c in ["X", "Y", "position_age_s"] if c in df]).copy()
    left["_t"] = left[on].apply(timedelta_to_seconds).astype(float)
    right = pos_df[[on, "X", "Y"]].copy()
    right["_position_t"] = right[on].apply(timedelta_to_seconds).astype(float)
    if position_units == "decimetres":
        right[["X", "Y"]] = right[["X", "Y"]] / 10.0
    merged = pd.merge_asof(
        left.sort_values("_t"),
        right[["_position_t", "X", "Y"]].sort_values("_position_t"),
        left_on="_t",
        right_on="_position_t",
        direction="backward",
        tolerance=float(tolerance_s),
    )
    merged["position_age_s"] = merged["_t"] - merged["_position_t"]
    merged["position_units"] = "metres"
    merged["position_source"] = "fastf1_normalized"
    return merged.drop(columns=["_t", "_position_t"]).reset_index(drop=True)
