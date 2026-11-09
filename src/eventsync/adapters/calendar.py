from eventsync.adapters.base import JsonFileAdapter


class CalendarFileAdapter(JsonFileAdapter):
    source = "calendar"
    id_field = "event_id"
