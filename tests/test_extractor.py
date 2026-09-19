import numpy as np
import pandas as pd
import pytest
from src.telemetry.f1_monitor import TelemetryExtractor


def test_native_irregular_time_distance_not_fixed_frequency():
    extractor = TelemetryExtractor(cache_enabled=False)
    result = extractor._calculate_distance_from_speed(
        pd.Series([36.0, 36.0, 36.0]), pd.Series(pd.to_timedelta([0, 0.2, 0.9], unit="s"))
    )
    np.testing.assert_allclose(result, [0, 2, 9])


def test_gap_or_missing_time_does_not_invent_distance():
    extractor = TelemetryExtractor(cache_enabled=False)
    speed = pd.Series([36.0, 36.0, 36.0])
    assert extractor._calculate_distance_from_speed(speed).isna().all()
    result = extractor._calculate_distance_from_speed(
        speed, pd.Series(pd.to_timedelta([0, 3, 3.2], unit="s"))
    )
    assert result.iloc[1:].isna().all()
    with pytest.raises(ValueError):
        extractor._calculate_distance_from_speed(speed, pd.Series(pd.to_timedelta([0, 0, 1], unit="s")))
