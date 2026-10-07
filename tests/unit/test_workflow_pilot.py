from copy import deepcopy
import json
import sys

import pytest

from evaluation.workflow_pilot import check_attempt, main


def clean_row():
    return {
        "arm": "clean", "outcome": "done", "success": True,
        "expected_fields": {"name": ["Pilot"], "consent": ["yes"], "plan": ["pro"]},
        "ledger": [{"confirmation_id": "pilot-clean-01-1", "fields": {
            "name": ["Pilot"], "consent": ["yes"], "plan": ["pro"],
        }}],
        "observed_confirmation_id": "pilot-clean-01-1", "submit_calls": 1,
        "batch_sizes": [2, 1, 1, 1, 1],
        "initial_url": "http://127.0.0.1/form/clean-01",
        "final_url": "http://127.0.0.1/form/clean-01", "document_commits": 1,
        "exception": None,
    }


@pytest.mark.parametrize("failure", ["wrong_value", "duplicate", "wrong_id", "exception"])
def test_acceptance_checker_rejects_independent_failure_evidence(failure):
    row = clean_row()
    assert check_attempt(row) == []
    if failure == "wrong_value":
        row["ledger"][0]["fields"]["plan"] = ["starter"]
    elif failure == "duplicate":
        row["ledger"].append(deepcopy(row["ledger"][0]))
    elif failure == "wrong_id":
        row["observed_confirmation_id"] = "pilot-foreign-01-1"
    else:
        row["exception"] = "Injected driver failure"
    assert check_attempt(row)


def test_failed_cli_writes_failure_artifact_before_nonzero_exit(monkeypatch, tmp_path):
    evidence = {"passed": False, "summary": {"clean": {"attempted": 1, "passed": 0}},
                "attempts": [{"failures": ["Wrong server value"]}]}

    async def failed_pilot(attempts):
        return evidence

    output = tmp_path / "failed.json"
    monkeypatch.setattr("evaluation.workflow_pilot.run_pilot", failed_pilot)
    monkeypatch.setattr(sys, "argv", ["workflow_pilot", "--output", str(output)])
    assert main() == 1
    assert json.loads(output.read_text()) == evidence
