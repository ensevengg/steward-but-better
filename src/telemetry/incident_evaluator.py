"""Diagnostic comparison only: public position/brake feeds cannot establish fault."""

from __future__ import annotations


class IncidentEvaluator:
    def evaluate_overtake_legality(self, car_a_df, car_b_df, car_a_name="Car A", car_b_name="Car B"):
        result = {
            "incident_summary": {"car_a": car_a_name, "car_b": car_b_name},
            "apex_analysis": {
                "lateral_distance_m": None,
                "violation": None,
                "note": "Racing-line entitlement cannot be measured from normalized FastF1 positions.",
            },
            "braking_analysis": {
                "dive_bomb_detected": None,
                "note": "Brake is an applied/not-applied channel, not pressure. Later braking alone is legal.",
            },
            "verdict": {
                "verdict": "INCONCLUSIVE",
                "violations": [],
                "summary": "Supply reviewed video/independent spatial evidence and applicable rules to the case assessor.",
            },
        }
        if car_a_df.empty or car_b_df.empty:
            result["verdict"]["verdict"] = "NO_DATA"
        return result


def evaluate_overtake_legality(car_a_df, car_b_df, car_a_name="Car A", car_b_name="Car B"):
    return IncidentEvaluator().evaluate_overtake_legality(car_a_df, car_b_df, car_a_name, car_b_name)
