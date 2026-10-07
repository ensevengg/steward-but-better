import numpy as np
import pandas as pd
import pytest
from src.telemetry.telemetry_utils import compute_g_forces, merge_position_channels, timedelta_to_seconds


def frame():
    t = np.arange(0, 12, 0.05)
    speed = 200.0
    radius = 60.0
    angle = t * speed / 3.6 / radius
    return pd.DataFrame(
        {"TimeSeconds": t, "Speed": speed, "X": radius * np.cos(angle), "Y": radius * np.sin(angle)}
    )


def test_circle_physics_matches_theory():
    out = compute_g_forces(frame())
    assert abs(out.lateral_g.iloc[30:].median() - (200 / 3.6) ** 2 / (60 * 9.81)) < 0.15


def test_causal_estimates_do_not_change_with_future_data():
    data = frame()
    prefix = compute_g_forces(data.iloc[:100])
    whole = compute_g_forces(data)
    np.testing.assert_allclose(prefix.lateral_g, whole.lateral_g.iloc[:100], equal_nan=True)


def test_missing_positions_stay_unknown():
    out = compute_g_forces(frame().drop(columns=["X", "Y"]))
    assert out.lateral_g.isna().all() and not out.lateral_g_available.any()
    assert compute_g_forces(pd.DataFrame()).longitudinal_g.isna().all()


def test_longitudinal_acceleration_is_signed():
    d = frame()
    d["Speed"] = np.linspace(250, 50, len(d))
    assert compute_g_forces(d).longitudinal_g.dropna().lt(0).all()
    d["Speed"] = np.linspace(50, 250, len(d))
    assert compute_g_forces(d).longitudinal_g.dropna().gt(0).all()


@pytest.mark.parametrize("bad", [0, -1, float("nan")])
def test_invalid_times_rejected(bad):
    d = frame()
    d.loc[1, "TimeSeconds"] = bad
    with pytest.raises(ValueError):
        compute_g_forces(d)


def test_position_units_staleness_and_no_future_join():
    left = pd.DataFrame({"SessionTime": pd.to_timedelta([0, 0.1, 0.4, 100], unit="s"), "Speed": [100] * 4})
    right = pd.DataFrame({"SessionTime": pd.to_timedelta([0.05], unit="s"), "X": [20], "Y": [12]})
    out = merge_position_channels(left, right)
    assert pd.isna(out.X.iloc[0])
    assert out.Y.iloc[1] == 1.2 and out.position_age_s.iloc[1] == pytest.approx(0.05)
    assert out.X.iloc[2:].isna().all()


def test_missing_segment_not_interpolated_into_geometry():
    d = frame()
    d.loc[50:70, "X"] = np.nan
    assert compute_g_forces(d).lateral_g.iloc[50:70].isna().all()


def test_timedelta_types_and_missing_time():
    assert timedelta_to_seconds(np.timedelta64(1500, "ms")) == 1.5
    assert timedelta_to_seconds(pd.Timedelta(seconds=1.5)) == 1.5
    with pytest.raises(ValueError):
        timedelta_to_seconds(None)
