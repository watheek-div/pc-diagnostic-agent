"""Simulation harness tests.

The harness must be deterministic, isolated from the production database, and
produce the expected classification for each of the four scenarios using the
REAL diagnostic engine over fully synthetic data.
"""

import os

from common import paths
from simulation import runner, scenarios


def _run(tmp_path, scenario_type, config, generate_report=True):
    workspace = os.path.join(str(tmp_path), "ws")
    return runner.run_simulation(
        scenario_type, workspace=workspace, config=config, generate_report=generate_report
    )


def _incident(result):
    return result.get("incident")


# -- scenario classifications ------------------------------------------------
def test_hard_hang_high(tmp_path, config):
    result = _run(tmp_path, scenarios.HARD_HANG, config)
    incident = _incident(result)
    assert incident is not None
    assert incident["incident_type"] == "HARD_HANG"
    assert incident["confidence"] == "HIGH"
    assert incident["duration_estimate"] == 300.0
    assert "Kernel-Power 41 detected" in incident["evidence"]
    assert "No clean shutdown event" in incident["evidence"]
    assert "Diagnostics stopped 300s before reboot" in incident["evidence"]


def test_normal_restart_no_incident(tmp_path, config):
    result = _run(tmp_path, scenarios.NORMAL_RESTART, config)
    assert _incident(result) is None
    assert result["summary"]["clean_shutdown"] is True
    assert result["summary"]["kernel_power_detected"] is False


def test_power_loss_low(tmp_path, config):
    result = _run(tmp_path, scenarios.POWER_LOSS, config)
    incident = _incident(result)
    assert incident is not None
    assert incident["incident_type"] == "POWER_LOSS"
    assert incident["confidence"] == "LOW"
    assert 0.0 <= incident["duration_estimate"] < 60.0


def test_bsod_high(tmp_path, config):
    result = _run(tmp_path, scenarios.BSOD, config)
    incident = _incident(result)
    assert incident is not None
    assert incident["incident_type"] == "BSOD"
    assert incident["confidence"] == "HIGH"
    assert "BugCheck detected" in incident["evidence"]


# -- isolation ---------------------------------------------------------------
def test_production_database_untouched(tmp_path, config):
    prod_path = os.path.abspath(paths.database_path())
    workspace = os.path.join(str(tmp_path), "ws")
    result = runner.run_simulation(scenarios.HARD_HANG, workspace=workspace, config=config)

    sim_path = os.path.abspath(result["db_path"])
    assert sim_path != prod_path
    assert sim_path.startswith(os.path.abspath(workspace))


def test_workspace_is_isolated_directory(tmp_path, config):
    workspace = os.path.join(str(tmp_path), "sim-ws")
    result = runner.run_simulation(scenarios.BSOD, workspace=workspace, config=config)
    assert os.path.abspath(result["db_path"]).startswith(os.path.abspath(workspace))
    # It must never fall back to the production data directory.
    assert not os.path.abspath(result["db_path"]).startswith(
        os.path.abspath(paths.data_dir())
    )


# -- determinism -------------------------------------------------------------
def test_deterministic_across_runs(tmp_path, config):
    first = _run(tmp_path, scenarios.HARD_HANG, config)
    second = _run(tmp_path, scenarios.HARD_HANG, config)
    a, b = _incident(first), _incident(second)
    assert a["incident_type"] == b["incident_type"]
    assert a["confidence"] == b["confidence"]
    assert a["evidence"] == b["evidence"]
    assert a["duration_estimate"] == b["duration_estimate"]
    assert first["findings"][0]["type"] == second["findings"][0]["type"]


# -- HTML report -------------------------------------------------------------
def test_report_contains_required_sections(tmp_path, config):
    result = _run(tmp_path, scenarios.HARD_HANG, config)
    assert result.get("report_path") and os.path.exists(result["report_path"])
    content = open(result["report_path"], encoding="utf-8").read()
    for needle in (
        "SIMULATION / TEST DATA",
        "FACT",
        "EVIDENCE",
        "SESSION ANALYSIS",
        "INFERENCE",
        "HYPOTHESIS",
        "HARD_HANG",
        "HIGH",
        "Incident Summary",
        "Timeline",
        "Previous boot",
        "Current boot",
        "Last activity",
        "Findings",
        "Recommended Next Steps",
        "Maximum CPU",
        "Maximum RAM",
        "Maximum disk utilisation",
    ):
        assert needle in content, needle


def test_report_normal_restart(tmp_path, config):
    result = _run(tmp_path, scenarios.NORMAL_RESTART, config)
    content = open(result["report_path"], encoding="utf-8").read()
    assert "No incident detected" in content
    assert "FACT" in content


def test_report_terminology_internally_consistent(tmp_path, config):
    """Event facts, session facts and inference must not read as contradictions.

    Regression for the HARD_HANG report that previously showed
    "Event 6008: NO" next to "Unexpected shutdown: YES" next to
    "Unexpected reboot detected" — three different meanings of "unexpected".
    """
    result = _run(tmp_path, scenarios.HARD_HANG, config)
    content = open(result["report_path"], encoding="utf-8").read()

    # 1) Event-level facts (raw Windows events observed in the log).
    assert "Event 6008 present</th><td>NO" in content
    assert "Clean shutdown event present" in content
    assert "Kernel-Power 41 present</th><td>YES" in content
    assert "BugCheck present</th><td>NO" in content

    # 2) Session-level facts, stated separately under SESSION ANALYSIS and in
    #    the report's Previous Session section.
    assert content.count("Previous session ended cleanly") >= 2
    assert content.count("Previous session ended unexpectedly") >= 2
    assert "Previous session ended cleanly</th><td>NO" in content
    assert "Previous session ended unexpectedly</th><td>YES" in content

    # 3) Inference phrase is precise and the ambiguous wording is gone.
    assert "Unclean reboot detected" in content
    assert "Unexpected reboot detected" not in content
    assert "Unexpected shutdown event (6008)" not in content

    # 4) Classification itself is unchanged.
    assert "HARD_HANG" in content
    assert "HIGH" in content


# -- scenario registry sanity ------------------------------------------------
def test_expected_outcomes_match_scenarios():
    assert runner.expected_outcome(scenarios.HARD_HANG) == ("HARD_HANG", "HIGH")
    assert runner.expected_outcome(scenarios.POWER_LOSS) == ("POWER_LOSS", "LOW")
    assert runner.expected_outcome(scenarios.BSOD) == ("BSOD", "HIGH")
    assert runner.expected_outcome(scenarios.NORMAL_RESTART) == (None, None)
    assert "hard-hang" in scenarios.scenario_names()