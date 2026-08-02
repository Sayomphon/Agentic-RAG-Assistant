"""Tests for Track A R3 performance evidence and guardrails."""

from __future__ import annotations

import unittest
from dataclasses import replace

from src.evaluation.run_track_a_performance import (
    ScenarioResult,
    _SCENARIOS,
    performance_gate_failures,
)


def _scenario(scenario_id: str) -> ScenarioResult:
    return ScenarioResult(
        schema_version="track-a-r3-performance-worker-v1",
        scenario_id=scenario_id,
        label=scenario_id,
        state=(
            "cold"
            if scenario_id.endswith("_cold")
            else "failure"
            if scenario_id in {"primary_timeout_secondary", "both_fail_closed"}
            else "concurrent"
            if scenario_id == "concurrent_busy"
            else "warm"
        ),
        model_role="primary",
        model="approved/model",
        revision="a" * 40,
        local_files_only=True,
        model_cache_ready=True,
        model_download_ms=0.0,
        model_load_ms=100.0,
        candidate_count=12,
        top_k=6,
        iteration_count=40,
        query_embedding_p50_ms=100.0,
        query_embedding_p95_ms=200.0,
        local_reranker_p50_ms=200.0,
        local_reranker_p95_ms=300.0,
        local_reranker_p99_ms=350.0,
        context_build_p50_ms=1.0,
        context_build_p95_ms=2.0,
        retrieval_e2e_p50_ms=400.0,
        retrieval_e2e_p95_ms=500.0,
        peak_rss_mb=2_000.0,
        steady_state_rss_mb=1_500.0,
        fallback_latency_ms=0.0,
        timeout_rate=0.0,
        secondary_usage_rate=0.5 if scenario_id == "concurrent_busy" else 0.0,
        unexpected_fallback_count=0,
        unhandled_exception_count=0,
        fail_closed=scenario_id == "both_fail_closed",
        within_overall_timeout=True,
        output_count=6,
    )


class PerformanceContractTests(unittest.TestCase):
    def test_matrix_records_all_warm_cold_and_failure_scenarios(self) -> None:
        scenarios = [_scenario(scenario_id) for scenario_id in _SCENARIOS]

        self.assertEqual(len(scenarios), 10)
        self.assertEqual(scenarios[0].state, "cold")
        self.assertEqual(scenarios[1].state, "warm")
        self.assertEqual(scenarios[7].state, "failure")
        self.assertEqual(scenarios[9].state, "concurrent")

    def test_guardrails_accept_bounded_healthy_and_failure_paths(self) -> None:
        scenarios = [_scenario(scenario_id) for scenario_id in _SCENARIOS]

        self.assertEqual(performance_gate_failures(scenarios), ())

    def test_guardrails_reject_latency_memory_and_unhandled_failures(self) -> None:
        scenarios = [_scenario(scenario_id) for scenario_id in _SCENARIOS]
        scenarios[5] = replace(scenarios[5], retrieval_e2e_p95_ms=3_001)
        scenarios[1] = replace(
            scenarios[1],
            local_reranker_p95_ms=2_001,
            peak_rss_mb=6_145,
        )
        scenarios[8] = replace(
            scenarios[8],
            fail_closed=False,
            unhandled_exception_count=1,
        )

        failures = performance_gate_failures(scenarios)

        self.assertIn("warm_retrieval_p95_above_3000_ms", failures)
        self.assertIn("primary_local_reranker_p95_above_2000_ms", failures)
        self.assertIn("peak_rss_above_6_gib", failures)
        self.assertIn("failure_path_unhandled_exception", failures)
        self.assertIn("both_fail_path_did_not_close", failures)


if __name__ == "__main__":
    unittest.main()
