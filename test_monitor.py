"""Tests for the Bad Bunny Tokyo concert monitor."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from monitor import detect_changes, load_last_state, parse_tokyo_info, save_state

# ---------------------------------------------------------------------------
# Fixture HTML snippets
# ---------------------------------------------------------------------------

CURRENT_HTML = """
<div class="dateWrapper" id="japan_march_2026">
  <div class="dateInnerCon">
    <p class="date">March 2026</p>
    <div class="city-country">
      <p class="city">Tokyo,</p>
      <p class="city">Japan</p>
    </div>
    <p class="venue">TBD</p>
  </div>
  <div class="butWrapper">
    <a id="japan_march_2026" href="#" class="topBut plausible-event-name=japan_march_2026">
      <p>MORE INFORMATION COMING SOON</p>
    </a>
  </div>
</div>
"""

UPDATED_HTML_DATE_AND_VENUE = """
<div class="dateWrapper" id="japan_march_14_2026">
  <div class="dateInnerCon">
    <p class="date">March 14 2026</p>
    <div class="city-country">
      <p class="city">Tokyo,</p>
      <p class="city">Japan</p>
    </div>
    <p class="venue">Tokyo Dome</p>
  </div>
  <div class="butWrapper">
    <a id="japan_march_14_2026" href="https://tickets.example.com/badbunny-tokyo"
       class="topBut onSale plausible-event-name=japan_march_14_2026">
      <p>TICKETS ON SALE NOW</p>
    </a>
  </div>
</div>
"""

UPDATED_HTML_VENUE_ONLY = """
<div class="dateWrapper" id="japan_march_2026">
  <div class="dateInnerCon">
    <p class="date">March 2026</p>
    <div class="city-country">
      <p class="city">Tokyo,</p>
      <p class="city">Japan</p>
    </div>
    <p class="venue">Tokyo Dome</p>
  </div>
  <div class="butWrapper">
    <a id="japan_march_2026" href="#" class="topBut plausible-event-name=japan_march_2026">
      <p>MORE INFORMATION COMING SOON</p>
    </a>
  </div>
</div>
"""

NO_TOKYO_HTML = """
<div class="dateWrapper" id="argentina_feb_13_2026">
  <div class="dateInnerCon">
    <p class="date">Feb 13 2026</p>
    <div class="city-country">
      <p class="city">Buenos Aires,</p>
      <p class="city">Argentina</p>
    </div>
    <p class="venue">Estadio River Plate</p>
  </div>
  <div class="butWrapper">
    <a id="argentina_feb_13_2026" href="https://tickets.example.com"
       class="topBut onSale">
      <p>TICKETS ON SALE NOW</p>
    </a>
  </div>
</div>
"""

# Fallback: no exact id match, but "Tokyo" appears in text
FALLBACK_HTML = """
<div class="dateWrapper" id="japan_apr_2026">
  <div class="dateInnerCon">
    <p class="date">April 2026</p>
    <div class="city-country">
      <p class="city">Tokyo,</p>
      <p class="city">Japan</p>
    </div>
    <p class="venue">TBD</p>
  </div>
  <div class="butWrapper">
    <a id="japan_apr_2026" href="#" class="topBut">
      <p>MORE INFORMATION COMING SOON</p>
    </a>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# parse_tokyo_info
# ---------------------------------------------------------------------------


class TestParseTokyo:
    def test_parses_current_state(self):
        info = parse_tokyo_info(CURRENT_HTML)
        assert info["date"] == "March 2026"
        assert info["venue"] == "TBD"
        assert info["button_text"] == "MORE INFORMATION COMING SOON"
        assert info["button_link"] == "#"
        assert "Tokyo" in info["city"]
        assert "Japan" in info["city"]

    def test_parses_updated_date_and_venue(self):
        info = parse_tokyo_info(UPDATED_HTML_DATE_AND_VENUE)
        assert info["date"] == "March 14 2026"
        assert info["venue"] == "Tokyo Dome"
        assert info["button_text"] == "TICKETS ON SALE NOW"
        assert "tickets.example.com" in info["button_link"]

    def test_parses_venue_only_change(self):
        info = parse_tokyo_info(UPDATED_HTML_VENUE_ONLY)
        assert info["date"] == "March 2026"
        assert info["venue"] == "Tokyo Dome"
        assert info["button_text"] == "MORE INFORMATION COMING SOON"

    def test_raises_when_tokyo_missing(self):
        with pytest.raises(ValueError, match="Could not find Tokyo"):
            parse_tokyo_info(NO_TOKYO_HTML)

    def test_fallback_finds_japan_id(self):
        info = parse_tokyo_info(FALLBACK_HTML)
        assert info["date"] == "April 2026"
        assert "Tokyo" in info["city"]

    def test_handles_empty_html(self):
        with pytest.raises(ValueError, match="Could not find Tokyo"):
            parse_tokyo_info("<html><body></body></html>")


# ---------------------------------------------------------------------------
# detect_changes
# ---------------------------------------------------------------------------


class TestDetectChanges:
    def _baseline(self):
        return {
            "date": "March 2026",
            "city": "Tokyo, Japan",
            "venue": "TBD",
            "button_text": "MORE INFORMATION COMING SOON",
            "button_link": "#",
        }

    def test_no_changes(self):
        old = self._baseline()
        new = self._baseline()
        assert detect_changes(old, new) == {}

    def test_venue_changed(self):
        old = self._baseline()
        new = {**self._baseline(), "venue": "Tokyo Dome"}
        changes = detect_changes(old, new)
        assert "venue" in changes
        assert changes["venue"] == ("TBD", "Tokyo Dome")
        assert len(changes) == 1

    def test_date_changed(self):
        old = self._baseline()
        new = {**self._baseline(), "date": "March 14 2026"}
        changes = detect_changes(old, new)
        assert "date" in changes
        assert changes["date"] == ("March 2026", "March 14 2026")

    def test_tickets_go_on_sale(self):
        old = self._baseline()
        new = {
            **self._baseline(),
            "button_text": "TICKETS ON SALE NOW",
            "button_link": "https://tickets.example.com",
        }
        changes = detect_changes(old, new)
        assert "button_text" in changes
        assert "button_link" in changes
        assert len(changes) == 2

    def test_multiple_changes(self):
        old = self._baseline()
        new = {
            **self._baseline(),
            "date": "March 14 2026",
            "venue": "Tokyo Dome",
            "button_text": "TICKETS ON SALE NOW",
            "button_link": "https://tickets.example.com",
        }
        changes = detect_changes(old, new)
        assert len(changes) == 4

    def test_old_is_none_first_run(self):
        new = self._baseline()
        changes = detect_changes(None, new)
        assert len(changes) == 5  # All fields are "new"


# ---------------------------------------------------------------------------
# State persistence (save/load)
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_save_and_load(self, tmp_path, monkeypatch):
        state_file = tmp_path / "last_state.json"
        monkeypatch.setattr("monitor.STATE_FILE", state_file)

        data = {"date": "March 2026", "venue": "TBD"}
        save_state(data)

        loaded = load_last_state()
        assert loaded == data

    def test_load_returns_none_when_missing(self, tmp_path, monkeypatch):
        state_file = tmp_path / "does_not_exist.json"
        monkeypatch.setattr("monitor.STATE_FILE", state_file)

        assert load_last_state() is None


# ---------------------------------------------------------------------------
# Email sending (mocked)
# ---------------------------------------------------------------------------


class TestSendEmail:
    def test_send_email_calls_smtp(self, monkeypatch):
        monkeypatch.setattr("monitor.GMAIL_ADDRESS", "test@gmail.com")
        monkeypatch.setattr("monitor.GMAIL_APP_PASSWORD", "fake password")

        mock_smtp = MagicMock()
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        # Suppress log file writes
        monkeypatch.setattr("monitor.LOG_FILE", Path("/dev/null"))

        with patch("monitor.smtplib.SMTP_SSL", mock_smtp):
            from monitor import send_email

            old = {"date": "March 2026", "venue": "TBD",
                   "city": "Tokyo, Japan", "button_text": "MORE INFORMATION COMING SOON",
                   "button_link": "#"}
            new = {**old, "venue": "Tokyo Dome"}
            send_email(old, new)

        mock_smtp.assert_called_once_with("smtp.gmail.com", 465)
        mock_server.login.assert_called_once_with("test@gmail.com", "fakepassword")
        mock_server.send_message.assert_called_once()

        sent_msg = mock_server.send_message.call_args[0][0]
        assert "Tokyo" in sent_msg.as_string()
        assert "Tokyo Dome" in sent_msg.as_string()


# ---------------------------------------------------------------------------
# Integration: fetch from the live site
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLiveFetch:
    """These tests hit the real website. Run with: pytest -m live"""

    def test_live_fetch_returns_expected_fields(self):
        from monitor import fetch_tokyo_info

        info = fetch_tokyo_info()
        assert info["element_id"]
        assert info["date"]
        assert "Tokyo" in info["city"]
        assert info["venue"]
        assert info["button_text"]

    def test_live_fetch_matches_current_known_state(self):
        from monitor import fetch_tokyo_info

        info = fetch_tokyo_info()
        # These are the current known values — if this test fails,
        # the concert info has changed (which is what we're monitoring!)
        assert info["date"] == "March 2026"
        assert info["venue"] == "TBD"
        assert info["button_text"] == "MORE INFORMATION COMING SOON"
        assert info["button_link"] == "#"
