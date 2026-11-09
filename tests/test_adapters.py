import pytest

from eventsync.adapters.calendar import CalendarFileAdapter
from eventsync.adapters.crm import CrmFileAdapter


def test_crm_adapter_reads_all_records(settings):
    recs = CrmFileAdapter(settings.data_dir / "crm_events.json").fetch()
    assert len(recs) == 20 and recs[0].source == "crm" and recs[0].source_id == "CRM-1001"
    assert recs[0].payload["meeting_date"] == "2025-03-10"


def test_calendar_adapter_reads_all_records(settings):
    recs = CalendarFileAdapter(settings.data_dir / "calendar_events.json").fetch()
    assert len(recs) == 22 and recs[3].source_id == "CAL-A4"
    assert recs[3].payload["start_time"] == "2025-03-13T19:00:00Z"


def test_adapter_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        CrmFileAdapter(tmp_path / "nope.json").fetch()
