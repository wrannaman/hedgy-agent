from pathlib import Path


PROMPT = Path(__file__).resolve().parents[1] / "CRON_PROMPT.md"


def test_action_alert_prompt_delegates_to_renderer():
    text = PROMPT.read_text()

    # Format ownership moved to the ONE renderer \u2014 the prompt must NOT hand-format.
    assert "Do NOT format the Slack message yourself, and do NOT post it." in text
    assert "slack_format.py" in text
    assert "state/agent_decision.json" in text
    assert "OPEN / NEW / WATCH / PORTFOLIO / NEAR MISS / PAPER" in text
    assert "portfolio_review" in text
    assert "Never call the Slack webhook for any content" in text
    assert "The only Slack message you send directly" not in text
    assert "SEPARATE Slack message" not in text
    # The old hand-written layout spec is gone (the renderer is the single example).
    assert "exactly the same shape as `daily_summary.py`" not in text
    assert "*CURRENT TRADES* \u2192 what to do:" not in text
    assert "*NEW TRADES:*" not in text


def test_action_alert_prompt_bans_old_table_artifacts():
    text = PROMPT.read_text()

    forbidden = [
        "1 \u00b7 CURRENT TRADES",
        "2 \u00b7 NEW TRADES",
        "3 \u00b7 WHAT IT MEANS",
        "Section 3",
        "Position  Contract",
        "Account  Order",
        "Profit = how much",
        "Cushion = how far",
        "```text",
    ]
    for phrase in forbidden:
        assert phrase not in text
