from evals.chaos.faults import FAULTS
from evals.run_chaos import score
from evals.run_evals import _label_matches, _number_matches, _prf, score_analyst


def test_numbers_match_within_tolerance_and_as_percentages():
    assert _number_matches(0.1907, 0.19068, 0.01)
    assert _number_matches(19.07, 0.19068, 0.01)  # reported as a percentage
    assert not _number_matches(0.25, 0.19068, 0.01)
    assert _number_matches(2_886_000, 2_886_142.45, 0.01)
    assert _number_matches(59, 59, 0)
    assert not _number_matches(58, 59, 0)


def test_labels_match_case_insensitively_and_on_first_neighbourhood():
    assert _label_matches("Staten Island led with 24%.", "Staten Island")
    assert _label_matches("CD 1 (Stapleton / Port Richmond) had the most", "Stapleton, Port Richmond")
    assert _label_matches("The top category was cleanliness.", "cleanliness")
    assert not _label_matches("Brooklyn led.", "Staten Island")


def test_no_data_questions_pass_only_without_numbers():
    item = {"kind": "no_data"}
    assert score_analyst(item, {"key_numbers": [], "answer_markdown": "No data before 1990."}, None)
    assert not score_analyst(item, {"key_numbers": [{"label": "rate", "value": 0.1}]}, None)


def test_precision_recall_ignores_unlabelled_columns():
    labels = {"sensitive": ["incident_address", "latitude", "longitude"],
              "not_sensitive": ["borough", "incident_zip"]}
    result = _prf({"incident_address", "latitude", "incident_zip", "street_name"}, labels)
    assert result["precision"] == round(2 / 3, 3)
    assert result["recall"] == round(2 / 3, 3)
    assert result["false_positives"] == ["incident_zip"]
    assert result["missed"] == ["longitude"]


def test_chaos_scoring_accepts_equivalent_categories():
    fault = FAULTS["partial_month_tonnage"]
    good = {"root_cause_asset": "raw_dsny.monthly_tonnage", "fault_category": "stale_source", "incident_id": 3}
    assert score(fault, good) == {"asset_correct": True, "category_correct": True,
                                  "column_correct": None, "incident_filed": True}
    wrong = {"root_cause_asset": "marts.fct_monthly_tonnage", "fault_category": "other"}
    assert score(fault, wrong)["asset_correct"] is False
