"""Tests for commitment detection and tracking."""

from app.services.agent.commitments import (
    CommitmentDirection,
    CommitmentStatus,
    detect_commitments,
    format_commitments_for_display,
)


class TestDetectCommitments:
    """Test commitment detection from natural language."""

    def test_i_will_send(self):
        results = detect_commitments("I'll send the report by Friday")
        assert len(results) >= 1
        assert results[0].direction == CommitmentDirection.I_PROMISED
        assert "report" in results[0].what.lower()

    def test_i_will_russian(self):
        results = detect_commitments("Я отправлю документы завтра")
        assert len(results) >= 1
        assert results[0].direction == CommitmentDirection.I_PROMISED

    def test_they_promised(self):
        results = detect_commitments("Alex said he'd prepare the presentation")
        assert len(results) >= 1
        assert results[0].direction == CommitmentDirection.THEY_PROMISED
        assert results[0].who.lower() == "alex"

    def test_they_promised_russian(self):
        results = detect_commitments("Мария обещала прислать отчёт")
        assert len(results) >= 1
        assert results[0].direction == CommitmentDirection.THEY_PROMISED

    def test_deadline_extraction(self):
        results = detect_commitments("I'll send it by Friday")
        assert len(results) >= 1
        assert results[0].deadline is not None
        assert "friday" in results[0].deadline.lower()

    def test_deadline_russian(self):
        results = detect_commitments("Я сделаю это до пятницы")
        assert len(results) >= 1
        assert results[0].deadline is not None

    def test_no_commitments(self):
        results = detect_commitments("The weather is nice today")
        assert len(results) == 0

    def test_source_context_stored(self):
        text = "I'll handle the deployment by Monday"
        results = detect_commitments(text)
        assert len(results) >= 1
        assert results[0].source_context is not None

    def test_user_name_in_i_promised(self):
        results = detect_commitments("I'll send the full report to the team", user_name="Mik")
        assert len(results) >= 1
        assert results[0].who == "Mik"

    def test_default_status_is_open(self):
        results = detect_commitments("I'll do it tomorrow")
        assert len(results) >= 1
        assert results[0].status == CommitmentStatus.OPEN


class TestFormatCommitments:
    """Test commitment display formatting."""

    def test_empty_list(self):
        result = format_commitments_for_display([])
        assert "no open commitments" in result.lower()

    def test_i_promised_section(self):
        from app.services.agent.commitments import CommitmentData

        commitments = [
            CommitmentData(
                who="Mik", what="send the report",
                direction=CommitmentDirection.I_PROMISED, deadline="Friday",
            )
        ]
        result = format_commitments_for_display(commitments)
        assert "you promised" in result.lower()
        assert "send the report" in result
        assert "Friday" in result

    def test_they_promised_section(self):
        from app.services.agent.commitments import CommitmentData

        commitments = [
            CommitmentData(
                who="Alex", what="prepare slides",
                direction=CommitmentDirection.THEY_PROMISED,
            )
        ]
        result = format_commitments_for_display(commitments)
        assert "others promised" in result.lower()
        assert "Alex" in result
        assert "prepare slides" in result
