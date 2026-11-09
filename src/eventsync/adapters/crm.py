from eventsync.adapters.base import JsonFileAdapter


class CrmFileAdapter(JsonFileAdapter):
    source = "crm"
    id_field = "crm_id"
