# Event Sync Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Event Sync Service: ingest two JSON exports, reconcile them with a transparent rule cascade, and serve meetings with per-field provenance over REST and a static web page, started by one command.

**Architecture:** A single FastAPI process. A pure pipeline (adapters → normalise → quality flags → participant resolver → dedupe → cascade → merge) rebuilds an in-memory `Store` at startup and on `POST /api/sync`. Routers read the store. A static page under `web/` is served by the same app. No database, no scheduler, no persisted decisions.

**Tech Stack:** Python 3.12, `uv`, FastAPI, pydantic v2, uvicorn, pytest + httpx (TestClient), vanilla HTML/JS/CSS.

**Spec:** `docs/superpowers/specs/2026-11-09-event-sync-service-design.md`

**Repository note:** This folder is not a git repository and is not published. Where this plan says "checkpoint", tick the task in `tasks/todo.md`; no commit step.

## Global Constraints

- Python `>=3.12`; run with `uv run eventsync`; tests with `uv run pytest`.
- Runtime dependencies limited to `fastapi`, `uvicorn`, `pydantic`; dev: `pytest`, `httpx`. Timezone data via stdlib `zoneinfo` (add `tzdata` only if `ZoneInfo("America/New_York")` raises on the host).
- `LOCAL_TZ = "America/New_York"`, `INTERNAL_DOMAIN = "firma.com"`, `TIGHT_WINDOW_MIN = 10`, `DEDUPE_WINDOW_MIN = 60`, `DEDUPE_JACCARD = 0.5`, `TITLE_OVERLAP = 0.3`, `AUTO_MERGE_LEVELS = {1}`, `NORMALIZER_VERSION = "1"`. All live in `src/eventsync/config.py` and are echoed by `/api/stats`.
- Raw payloads are never mutated. Every normalised field is `Optional`. Seconds are dropped from all times.
- Status enum values: `scheduled | confirmed | tentative | completed | cancelled`. Location kind: `virtual | in_person | unknown`. FieldView status: `agree | conflict | differs | single_source | missing | unresolved`. Match kind: `auto | proposed | singleton`.
- Comparable fields: `start, end, day, owner_email, client_name, client_company, status, location_kind, meeting_type`. Complementary: `title, notes, participants, external_domains, location_raw, created_at, is_recurring`.
- Fixtures are the real files in `data/`; tests must not copy or edit them.
- API error shape `{"error": {"code": str, "message": str}}`; unknown id → 404, bad filter → 422.

## Review Focus

1. A CRM `meeting_date` that matches neither accepted pattern (e.g. `2025/03/15`) must yield `start=None` plus `malformed_date`, never an exception. Pinned in Task 3.
2. A calendar `start_time` with a non-UTC offset (e.g. `+05:30`) must convert to local like the `Z` case and flag `utc_timestamp`. Pinned in Task 3.
3. Two CRM records on the same day both satisfying level 1 against one calendar record must yield one claim (smaller `dt`) and the other falls to the proposal pass; the store must never contain a calendar id in two auto merges. Pinned in Task 6.
4. A filter value outside the enum (`?source=outlook`) must return 422 with the error shape, not 500. Pinned in Task 9.
5. `POST /api/sync` while a file is missing must return 500 with the error shape and leave the previous store intact. Pinned in Task 8.

---

## File Structure

```
pyproject.toml                       project metadata, deps, [project.scripts] eventsync
src/eventsync/__init__.py
src/eventsync/__main__.py            main(): uvicorn.run("eventsync.api.app:app", host, port)
src/eventsync/config.py              Settings dataclass + DEFAULT settings
src/eventsync/models.py              pydantic models shared by pipeline and API
src/eventsync/adapters/__init__.py
src/eventsync/adapters/base.py       SourceAdapter protocol
src/eventsync/adapters/crm.py        CrmFileAdapter
src/eventsync/adapters/calendar.py   CalendarFileAdapter
src/eventsync/normalize.py           normalise_crm / normalise_calendar + field helpers
src/eventsync/quality.py             flag helpers used by normalize
src/eventsync/participants.py        name_key, company_key, is_contained, is_partial
src/eventsync/reconcile/__init__.py
src/eventsync/reconcile/dedupe.py    find_duplicates
src/eventsync/reconcile/cascade.py   run_cascade, evidence, match_key
src/eventsync/reconcile/merge.py     build_meeting, build_fieldviews, WINNER_RULES
src/eventsync/store.py               Store + build_store(settings)
src/eventsync/api/__init__.py
src/eventsync/api/app.py             create_app(), lifespan builds store, static mount, error handlers
src/eventsync/api/routes.py          all routers (small enough for one file)
web/index.html, web/app.js, web/styles.css
tests/conftest.py                    fixtures: settings, raw records, canonical records, store, client
tests/test_adapters.py … test_api.py one file per task
README.md
docs/ai-collaboration/README.md
```

---

### Task 1: Scaffold, config, run command, health endpoint

**Files:**
- Create: `pyproject.toml`, `src/eventsync/__init__.py`, `src/eventsync/__main__.py`, `src/eventsync/config.py`, `src/eventsync/api/__init__.py`, `src/eventsync/api/app.py`, `tests/conftest.py`, `tests/test_app.py`

**Interfaces:**
- Produces: `Settings` dataclass in `config.py` with fields `data_dir: Path`, `local_tz: str`, `internal_domain: str`, `tight_window_min: int`, `dedupe_window_min: int`, `dedupe_jaccard: float`, `title_overlap: float`, `auto_merge_levels: frozenset[int]`, `normalizer_version: str`, `host: str = "127.0.0.1"`, `port: int = 8000`; `DEFAULT = Settings(data_dir=<repo>/data, …)` using the Global Constraints values. `create_app(settings: Settings = DEFAULT) -> FastAPI` in `api/app.py`; `app = create_app()` module attribute. `main()` in `__main__.py`.

- [ ] **Step 1: Write the failing tests** in `tests/test_app.py`

```python
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}

def test_default_settings_values():
    from eventsync.config import DEFAULT
    assert DEFAULT.local_tz == "America/New_York"
    assert DEFAULT.tight_window_min == 10 and DEFAULT.dedupe_window_min == 60
    assert DEFAULT.auto_merge_levels == frozenset({1})
```
`conftest.py` provides `client` = `TestClient(create_app())`.

- [ ] **Step 2: Run** `uv run pytest tests/test_app.py -v` → FAIL (module not found).
- [ ] **Step 3: Implement** `pyproject.toml` (name `eventsync`, `[project.scripts] eventsync = "eventsync.__main__:main"`, `[tool.pytest.ini_options] pythonpath = ["src"]`), `config.py`, `api/app.py` with `/healthz` only, `__main__.py` calling `uvicorn.run`.
- [ ] **Step 4: Run** `uv run pytest tests/test_app.py -v` → PASS. Run `uv run eventsync` in the background, `curl -s 127.0.0.1:8000/healthz` → `{"ok":true}`, stop it.
- [ ] **Step 5: Checkpoint** in `tasks/todo.md`.

---

### Task 2: Models and adapters

**Files:**
- Create: `src/eventsync/models.py`, `src/eventsync/adapters/base.py`, `src/eventsync/adapters/crm.py`, `src/eventsync/adapters/calendar.py`, `tests/test_adapters.py`

**Interfaces:**
- Produces in `models.py` (pydantic `BaseModel`s unless noted):
  - `Source = Literal["crm", "calendar"]`
  - `RawRecord(source: Source, source_id: str, payload: dict[str, Any])`
  - `QualityFlag(source: Source, source_id: str, field: str, code: str, detail: str)`
  - `Status`, `LocationKind`, `FieldStatus`, `MatchKind`, `Confidence` as `str` Enums with the Global Constraints values.
  - `CanonicalRecord` with every field from spec §6 as `Optional`, plus `participants: set[str] = set()`, `external_domains: set[str] = set()`, `client_key: str | None`, `flags: list[QualityFlag] = []`, `raw: RawRecord`.
  - `Evidence(same_day: bool, dt_minutes: int | None, whole_hour_gap: bool, participants_contained: bool, participants_partial: bool, owner_agree: bool, client_agree: bool | None, title_overlap: float)`
  - `Match(kind: MatchKind, level: int | Literal["D"] | None, confidence: Confidence | None, match_key: str | None, evidence: Evidence | None)`
  - `SideValue(raw: Any, normalized: Any)`; `FieldView(value: Any, status: FieldStatus, winner: Source | None, rule: str | None, crm: SideValue | None, calendar: SideValue | None)`
  - `Meeting(meeting_id: str, match: Match, sources: dict[Source, RawRecord | None], fields: dict[str, FieldView], flags: list[QualityFlag], proposals: list[str], conflict_count: int)`
  - `ProposalSide(source: Source, source_id: str, meeting_id: str)`; `Proposal(proposal_id: str, kind: Literal["cross_source","duplicate"], level: int | Literal["D"], left: ProposalSide, right: ProposalSide, reasons: list[str], evidence: Evidence | None, preview: dict[str, Any])`
- `adapters/base.py`: `class SourceAdapter(Protocol): source: Source; def fetch(self) -> list[RawRecord]`.
- `CrmFileAdapter(path: Path)` and `CalendarFileAdapter(path: Path)` implementing it; `source_id` from `crm_id` / `event_id`.

- [ ] **Step 1: Write the failing tests**

```python
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
```
- [ ] **Step 2: Run** `uv run pytest tests/test_adapters.py -v` → FAIL.
- [ ] **Step 3: Implement** models and the two adapters (`json.load`, wrap each object).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Checkpoint.**

---

### Task 3: Normalisation and quality flags

**Files:**
- Create: `src/eventsync/quality.py`, `src/eventsync/normalize.py`, `tests/test_normalize.py`
- Modify: `tests/conftest.py` (add `crm_raw`, `cal_raw` fixtures returning `dict[str, RawRecord]` keyed by id)

**Interfaces:**
- `normalize.py`: `normalise_crm(rec: RawRecord, s: Settings) -> CanonicalRecord`, `normalise_calendar(rec: RawRecord, s: Settings) -> CanonicalRecord`, `normalise_all(crm: list[RawRecord], cal: list[RawRecord], s: Settings) -> list[CanonicalRecord]`. Helpers (module-level, pure): `parse_crm_date(s: str | None) -> tuple[date | None, QualityFlag | None]`, `parse_calendar_ts(s: str | None, tz: str) -> tuple[datetime | None, list[QualityFlag]]`, `map_status(s: str | None) -> Status | None`, `location_kind(location: str | None, meeting_type: str | None) -> LocationKind`, `clean_attendee(a: str) -> tuple[str | None, QualityFlag | None]` (returns repaired email or None for placeholders), `VIRTUAL_KEYWORDS = ("zoom","teams","meet","webex","virtual")`.
- `quality.py`: `flag(rec: RawRecord, field: str, code: str, detail: str) -> QualityFlag` and the code constants from spec §6.
- Participant derivation (`owner_email`, `client_key`, `participants`, `external_domains`) is filled in Task 4; here leave those fields empty.

- [ ] **Step 1: Write the failing tests** (one per trap row; key assertions)

```python
def test_malformed_date_second_pattern(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1008"], settings)
    assert c.day == date(2025, 3, 15) and c.start == datetime(2025, 3, 15, 12, 0)
    assert {f.code for f in c.flags} >= {"malformed_date", "weekend"}

def test_unparseable_date_is_none_with_flag(settings):
    d, f = parse_crm_date("2025/03/15")
    assert d is None and f.code == "malformed_date"

def test_missing_time(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1007"], settings)
    assert c.start is None and c.day == date(2025, 3, 18) and "missing_time" in {f.code for f in c.flags}

def test_empty_notes_becomes_none(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1010"], settings)
    assert c.notes is None and "empty_string" in {f.code for f in c.flags}

def test_utc_z_converts_to_local(cal_raw, settings):
    c = normalise_calendar(cal_raw["CAL-A4"], settings)
    assert c.start == datetime(2025, 3, 13, 15, 0) and "utc_timestamp" in {f.code for f in c.flags}

def test_non_utc_offset_converts_to_local():
    dt, flags = parse_calendar_ts("2025-03-13T19:00:00+05:30", "America/New_York")
    assert dt == datetime(2025, 3, 13, 9, 30) and flags[0].code == "utc_timestamp"

def test_truncated_end_and_empty_attendees(cal_raw, settings):
    c = normalise_calendar(cal_raw["CAL-A11"], settings)
    assert c.end == datetime(2025, 3, 14, 20, 0)
    assert {f.code for f in c.flags} >= {"truncated_timestamp", "no_participants", "missing_field"}

def test_status_map(): 
    assert map_status("Cancelled") == Status.cancelled and map_status("confirmed") == Status.confirmed

def test_location_kind_cases():
    assert location_kind("Zoom", "In-Person") == LocationKind.virtual
    assert location_kind("NYC Office - 30th Floor", "In-Person") == LocationKind.in_person
    assert location_kind(None, "Virtual") == LocationKind.virtual
    assert location_kind(None, None) == LocationKind.unknown

def test_attendee_cleaning():
    assert clean_attendee("raj.patel[at]atlasvc.com") == ("raj.patel@atlasvc.com", ANY_FLAG("malformed_email"))
    assert clean_attendee("external-guests")[0] is None

def test_placeholder_client(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1017"], settings)
    assert c.client_name is None and "placeholder_client" in {f.code for f in c.flags}
```
(`ANY_FLAG(code)` is a tiny conftest helper comparing on `.code`.)

- [ ] **Step 2: Run** `uv run pytest tests/test_normalize.py -v` → FAIL.
- [ ] **Step 3: Implement** `quality.py` then `normalize.py`. Date patterns: `%Y-%m-%d`, then `%m-%d/%Y`. Calendar ts: `datetime.fromisoformat` after replacing trailing `Z` with `+00:00`; if length of the time part is `HH:MM` append `:00` and flag `truncated_timestamp`; tz-aware → `.astimezone(ZoneInfo(tz)).replace(tzinfo=None)` + flag `utc_timestamp`. Weekend flag when `day.weekday() >= 5`. `missing_field` once per null `location`/`description`/`notes`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Checkpoint.**

---

### Task 4: Participant resolver

**Files:**
- Create: `src/eventsync/participants.py`, `tests/test_participants.py`
- Modify: `src/eventsync/normalize.py` (call resolver to fill `owner_email`, `client_key`, `participants`, `external_domains`); `tests/conftest.py` (add `canon` fixture: `dict[str, CanonicalRecord]` keyed by source_id from `normalise_all` over both adapters)

**Interfaces:**
- `name_key(name: str | None) -> str | None` → `"kevin.obrien"` from `"Kevin O'Brien"`; None for None/`"Multiple"`.
- `company_key(company: str | None) -> str | None` → `"meridian"` from `"Meridian Capital"`.
- `domain_matches(company_key: str, domain: str) -> bool` → `domain.startswith(company_key)`.
- `is_contained(crm: CanonicalRecord, cal: CanonicalRecord, s: Settings) -> bool` and `is_partial(crm, cal, s) -> bool` exactly as spec §8 definitions.
- Normalisation fills: CRM `owner_email = name_key(owner) + "@" + s.internal_domain`, `client_key = name_key(client_name)`, `participants = {owner_email} ∪ ({client_key} if any)`, `external_domains = {company_key} if any`; calendar `owner_email = organizer`, `participants = cleaned attendees ∪ {organizer}`, `external_domains = {domain of a for a in participants if not a.endswith(internal_domain)}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_name_key_strips_non_letters():
    assert name_key("Kevin O'Brien") == "kevin.obrien" and name_key("Multiple") is None

def test_company_key_prefix_matches_every_company(canon):   # canon: dict id -> CanonicalRecord
    for cid, eid in [("CRM-1001","CAL-A1"),("CRM-1005","CAL-A5"),("CRM-1012","CAL-A13"),("CRM-1018","CAL-A21")]:
        key = company_key(canon[cid].client_company)
        assert any(domain_matches(key, d) for d in canon[eid].external_domains)

def test_contained_when_organizer_differs(canon, settings):
    assert is_contained(canon["CRM-1013"], canon["CAL-A14"], settings)

def test_not_contained_internal_event_for_client_record(canon, settings):
    assert not is_contained(canon["CRM-1007"], canon["CAL-A18"], settings)
    assert is_contained(canon["CRM-1007"], canon["CAL-A8"], settings)

def test_partial_only_owner(canon, settings):
    assert is_partial(canon["CRM-1003"], canon["CAL-A7"], settings) and not is_contained(canon["CRM-1003"], canon["CAL-A7"], settings)
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** resolver and wire into normalise functions.
- [ ] **Step 4: Run** `uv run pytest tests/test_participants.py tests/test_normalize.py -v` → PASS.
- [ ] **Step 5: Checkpoint.**

---

### Task 5: Same-source duplicate detection

**Files:**
- Create: `src/eventsync/reconcile/__init__.py`, `src/eventsync/reconcile/dedupe.py`, `tests/test_dedupe.py`

**Interfaces:**
- `find_duplicates(records: list[CanonicalRecord], s: Settings) -> list[tuple[CanonicalRecord, CanonicalRecord, float, int]]` returning `(a, b, jaccard, dt_minutes)` for pairs within one source with same `owner_email`, same `day`, `dt <= s.dedupe_window_min`, `jaccard(participants) >= s.dedupe_jaccard`. Deterministic order by ids.
- `jaccard(a: set[str], b: set[str]) -> float` (0.0 when both empty).

- [ ] **Step 1: Write the failing tests**

```python
def test_pinnacle_pair_is_duplicate(canon, settings):
    cal = [c for c in canon.values() if c.raw.source == "calendar"]
    dups = find_duplicates(cal, settings)
    assert [(a.raw.source_id, b.raw.source_id) for a, b, *_ in dups] == [("CAL-A5", "CAL-A6")]
    assert dups[0][2] >= 0.5 and dups[0][3] == 30

def test_recurring_syncs_not_duplicates(canon, settings):
    cal = [c for c in canon.values() if c.raw.source == "calendar"]
    ids = {frozenset((a.raw.source_id, b.raw.source_id)) for a, b, *_ in find_duplicates(cal, settings)}
    assert frozenset(("CAL-A3", "CAL-A18")) not in ids

def test_crm_has_no_duplicates(canon, settings):
    crm = [c for c in canon.values() if c.raw.source == "crm"]
    assert find_duplicates(crm, settings) == []
```
- [ ] **Step 2: Run** → FAIL.  **Step 3: Implement.**  **Step 4: Run** → PASS.  **Step 5: Checkpoint.**

---

### Task 6: Cascade

**Files:**
- Create: `src/eventsync/reconcile/cascade.py`, `tests/test_cascade.py`

**Interfaces:**
- `evidence_for(crm: CanonicalRecord, cal: CanonicalRecord, s: Settings) -> Evidence` (`dt_minutes = None` when either start is None; `whole_hour_gap = dt is not None and dt > 0 and dt % 60 == 0`; `client_agree = None` when CRM has no client key and no company key; `title_overlap` via `token_overlap(a, b)` with `STOP_WORDS` constant).
- `level_for(ev: Evidence) -> int | None`: 1 if contained and dt ≤ tight; 2 if contained and dt > tight; 3 if contained and dt is None; 4 if partial and dt ≤ tight and title_overlap ≥ threshold; else None.
- `match_key(ev: Evidence, s: Settings) -> str` e.g. `"+DAY+START+OWNER+CLIENT"` (`-START` when dt > tight or None→`~START`, `~CLIENT` when `client_agree is None`, `+TITLE` when overlap ≥ threshold).
- `confidence_for(level: int, crm: CanonicalRecord) -> Confidence`: level 1 → high, or medium when `len(crm.participants) == 1`; 2 → medium; 3, 4 → low.
- `CascadeResult(auto: list[tuple[CanonicalRecord, CanonicalRecord, Evidence]], proposals: list[tuple[CanonicalRecord, CanonicalRecord, int, Evidence]], unmatched: list[CanonicalRecord])` (dataclass).
- `run_cascade(records: list[CanonicalRecord], s: Settings) -> CascadeResult` implementing spec §8 order of operations: level-1 pass per CRM record (sorted by id) claiming smallest-`dt` unclaimed candidate; then proposal pass per unclaimed pair.

- [ ] **Step 1: Write the failing tests**

```python
AUTO = {("CRM-1001","CAL-A1"),("CRM-1002","CAL-A2"),("CRM-1005","CAL-A5"),("CRM-1006","CAL-A7"),("CRM-1008","CAL-A9"),
        ("CRM-1009","CAL-A10"),("CRM-1011","CAL-A12"),("CRM-1012","CAL-A13"),("CRM-1013","CAL-A14"),("CRM-1014","CAL-A15"),
        ("CRM-1015","CAL-A16"),("CRM-1017","CAL-A20"),("CRM-1018","CAL-A21"),("CRM-1019","CAL-A22")}

def test_level_one_pairs(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    assert {(c.raw.source_id, k.raw.source_id) for c, k, _ in res.auto} == AUTO

def test_proposals(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    props = {(c.raw.source_id, k.raw.source_id): lvl for c, k, lvl, _ in res.proposals}
    assert props == {("CRM-1004","CAL-A4"): 2, ("CRM-1016","CAL-A17"): 2, ("CRM-1007","CAL-A8"): 3}

def test_whole_hour_gap_flagged(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    ev = {(c.raw.source_id, k.raw.source_id): e for c, k, _, e in res.proposals}
    assert ev[("CRM-1004","CAL-A4")].dt_minutes == 60 and ev[("CRM-1004","CAL-A4")].whole_hour_gap
    assert ev[("CRM-1016","CAL-A17")].dt_minutes == 120

def test_claimed_record_generates_no_proposals(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    assert not any(c.raw.source_id == "CRM-1005" for c, *_ in res.proposals)

def test_unmatched(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    assert {r.raw.source_id for r in res.unmatched} == {"CRM-1003","CRM-1004","CRM-1007","CRM-1010","CRM-1016","CRM-1020",
        "CAL-A3","CAL-A4","CAL-A6","CAL-A8","CAL-A11","CAL-A17","CAL-A18","CAL-A19"}

def test_one_calendar_record_claimed_once(canon, settings):
    # synthetic: copy CRM-1001 as CRM-9999 with time 14:05; only one may claim CAL-A1
    dup = canon["CRM-1001"].model_copy(update={"start": datetime(2025,3,10,14,5), "raw": RawRecord(source="crm", source_id="CRM-9999", payload={})})
    res = run_cascade(list(canon.values()) + [dup], settings)
    claimed = [c.raw.source_id for c, k, _ in res.auto if k.raw.source_id == "CAL-A1"]
    assert claimed == ["CRM-1001"]
    # A1 is claimed; the proposal pass only evaluates levels 2-4, and dt=5 fits none of them
    assert not any(c.raw.source_id == "CRM-9999" for c, *_ in res.proposals)
    assert "CRM-9999" in {r.raw.source_id for r in res.unmatched}

def test_match_key():
    assert match_key(Evidence(same_day=True, dt_minutes=0, whole_hour_gap=False, participants_contained=True,
        participants_partial=False, owner_agree=True, client_agree=True, title_overlap=0.0), DEFAULT) == "+DAY+START+OWNER+CLIENT"
```
- [ ] **Step 2: Run** → FAIL.  **Step 3: Implement** (`STOP_WORDS = {"the","and","a","of","with","for","re","q1","review","meeting","call","session","discussion"}`).  **Step 4: Run** → PASS.  **Step 5: Checkpoint.**

---

### Task 7: Merge, FieldViews, winner rules

**Files:**
- Create: `src/eventsync/reconcile/merge.py`, `tests/test_merge.py`
- Modify: `tests/conftest.py` (add `pair(c_id, e_id) -> Meeting` fixture factory: `build_meeting(canon[c_id], canon[e_id], Match(kind="auto", level=1, confidence="high", match_key=None, evidence=None))`)

**Interfaces:**
- `COMPARABLE: frozenset[str]`, `COMPLEMENTARY: frozenset[str]` per Global Constraints; `CANONICAL_FIELDS = tuple(COMPARABLE | COMPLEMENTARY)` in a fixed display order.
- `WinnerRule = Callable[[Any, Any], tuple[Source | None, str]]` returning `(winner, rule_text)`; `WINNER_RULES: dict[str, WinnerRule]` with the spec §9 rows and rule texts verbatim.
- `build_fieldview(field: str, crm: CanonicalRecord | None, cal: CanonicalRecord | None) -> FieldView`.
- `meeting_id_for(ids: Iterable[str]) -> str` → `"m-" + sha1("|".join(sorted(ids))).hexdigest()[:10]`; `proposal_id_for(a: str, b: str) -> str` same with `"p-"`.
- `build_meeting(crm: CanonicalRecord | None, cal: CanonicalRecord | None, match: Match) -> Meeting` (`conflict_count` = number of fields with status `conflict` or `unresolved`; `flags` = union; `proposals` filled later by store).
- `duplicate_preview(a: CanonicalRecord, b: CanonicalRecord) -> dict[str, dict]` → `{field: {"left": ..., "right": ..., "same": bool}}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_status_conflict_and_winner(pair):   # pair(c_id, e_id) fixture -> Meeting with a level-1 Match
    m = pair("CRM-1001", "CAL-A1")
    fv = m.fields["status"]
    assert fv.status == "conflict" and fv.winner == "crm" and fv.value == "completed"
    assert fv.crm.raw == "Completed" and fv.calendar.raw == "confirmed"
    assert m.conflict_count == 1

def test_location_kind_unresolved(pair):
    m = pair("CRM-1002", "CAL-A2")
    assert m.fields["location_kind"].status == "unresolved" and m.fields["location_kind"].value is None
    assert m.fields["location_raw"].status == "unresolved" and m.conflict_count == 2

def test_owner_conflict(pair):
    m = pair("CRM-1013", "CAL-A14")
    assert m.fields["owner_email"].status == "conflict" and m.fields["owner_email"].value == "sarah.chen@firma.com"

def test_complementary_fields_differ_not_conflict(pair):
    m = pair("CRM-1005", "CAL-A5")
    assert m.fields["title"].status == "differs" and m.fields["created_at"].status == "differs"
    assert m.fields["start"].status == "agree" and m.conflict_count == 0

def test_single_source_and_missing(pair):
    m = pair("CRM-1001", "CAL-A1")
    assert m.fields["end"].status == "single_source" and m.fields["end"].winner == "calendar"
    assert m.fields["meeting_type"].status == "single_source"

def test_singleton_meeting(canon):
    m = build_meeting(canon["CRM-1003"], None, Match(kind="singleton", level=None, confidence=None, match_key=None, evidence=None))
    assert all(fv.status in {"single_source", "missing"} for fv in m.fields.values()) and m.conflict_count == 0

def test_meeting_id_stable():
    assert meeting_id_for(["CAL-A1", "CRM-1001"]) == meeting_id_for(["CRM-1001", "CAL-A1"])
```
- [ ] **Step 2: Run** → FAIL.  **Step 3: Implement.**  **Step 4: Run** → PASS.  **Step 5: Checkpoint.**

---

### Task 8: Store and pipeline

**Files:**
- Create: `src/eventsync/store.py`, `tests/test_store.py`
- Modify: `tests/conftest.py` (add session-scoped `store` fixture = `build_store(settings)`)

**Interfaces:**
- `@dataclass class Store: meetings: dict[str, Meeting]; proposals: dict[str, Proposal]; raw: dict[tuple[Source, str], RawRecord]; by_source_id: dict[tuple[Source, str], str]` (→ meeting_id); `flags: list[QualityFlag]`; `rejected_best: dict[tuple[Source,str], dict]` (for `/unmatched`: `{other_id, level_reached, reasons}` or None); `settings: Settings`; `synced_at: datetime`; `normalizer_version: str`.
- `build_store(s: Settings) -> Store`: adapters → `normalise_all` → `find_duplicates` → `run_cascade` → `build_meeting` for auto pairs with `Match(kind="auto", level=1, …)` and for each unmatched record with `kind="proposed"` if it appears in any proposal else `"singleton"` → `Proposal` objects (cross_source preview = `build_meeting(...).fields`; duplicate preview = `duplicate_preview`) → fill `Meeting.proposals`.
- `stats(store: Store) -> dict` with keys `meetings_by_kind`, `proposals_by_level`, `fields_by_status`, `flags_by_code`, `source_coverage` (`{"crm": 20, "calendar": 22, "both": 14}`), `config` (the Settings as dict), `normalizer_version`, `synced_at`.

- [ ] **Step 1: Write the failing tests**

```python
def test_store_counts(store):
    kinds = Counter(m.match.kind for m in store.meetings.values())
    assert kinds == {"auto": 14, "proposed": 7, "singleton": 7} and len(store.meetings) == 28
    assert Counter(p.level for p in store.proposals.values()) == {2: 2, 3: 1, "D": 1}

def test_auto_meeting_lists_duplicate_proposal(store):
    m = store.meetings[store.by_source_id[("calendar", "CAL-A5")]]
    assert m.match.kind == "auto" and len(m.proposals) == 1 and store.proposals[m.proposals[0]].kind == "duplicate"

def test_rejected_best_for_unmatched(store):
    assert store.rejected_best[("crm", "CRM-1003")]["other_id"] == "CAL-A7"
    assert store.rejected_best[("crm", "CRM-1010")] is None

def test_sync_is_idempotent(settings):
    a, b = build_store(settings), build_store(settings)
    assert {k: m.model_dump(exclude={"flags"}) for k, m in a.meetings.items()} == {k: m.model_dump(exclude={"flags"}) for k, m in b.meetings.items()}

def test_missing_file_raises(settings):
    with pytest.raises(FileNotFoundError):
        build_store(replace(settings, data_dir=Path("/nonexistent")))
```
- [ ] **Step 2: Run** → FAIL.  **Step 3: Implement** (`rejected_best`: for each unmatched record, the same-day candidate with the highest `level_for`, else the smallest `dt`, else None; reasons from evidence, e.g. `"owner present, client absent"`, `"start differs by 60 min"`).  **Step 4: Run** → PASS.  **Step 5: Checkpoint.**

---

### Task 9: API routes

**Files:**
- Create: `src/eventsync/api/routes.py`, `tests/test_api.py`
- Modify: `src/eventsync/api/app.py` (lifespan builds store into `app.state.store`; include router; error handlers; mount `web/` at `/` after API routes)

**Interfaces:**
- Router prefix `/api`. Endpoints and filters exactly per spec §10. List endpoints accept `limit: int = 500` and `offset: int = 0` (applied after filtering). Query enums validated with `Literal` types so FastAPI returns 422; custom handler converts `RequestValidationError` and `HTTPException` to `{"error": {"code", "message"}}` (`code` = `"validation_error"` / `"not_found"` / `"sync_failed"`).
- `POST /api/sync`: `try: app.state.store = build_store(settings) except Exception as e: raise HTTPException(500, …)`; previous store untouched on failure.
- Meeting summary shape for the list: `{meeting_id, match: {kind, level, confidence, match_key}, fields: {name: {value, status}}, conflict_count, flag_count}`.
- `GET /api/unmatched` → `{"crm": [{meeting_id, source_id, best_candidate}], "calendar": [...]}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_meetings_list_and_filters(client):
    assert len(client.get("/api/meetings").json()) == 28
    assert len(client.get("/api/meetings?source=both").json()) == 14
    assert len(client.get("/api/meetings?has_conflict=true").json()) == 4
    assert len(client.get("/api/meetings?level=1").json()) == 14

def test_bad_filter_422(client):
    r = client.get("/api/meetings?source=outlook")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"

def test_meeting_detail_and_diff(client):
    mid = client.get("/api/sources/crm/CRM-1004").json()["meeting_id"]
    d = client.get(f"/api/meetings/{mid}").json()
    assert d["match"]["kind"] == "proposed" and d["sources"]["calendar"] is None
    assert client.get("/api/meetings/nope").status_code == 404
    mid1 = client.get("/api/sources/crm/CRM-1001").json()["meeting_id"]
    diff = client.get(f"/api/meetings/{mid1}/diff").json()
    assert "status" in diff and "start" not in diff

def test_proposals_conflicts_quality_unmatched_stats(client):
    assert len(client.get("/api/proposals").json()) == 4
    assert len(client.get("/api/proposals?kind=duplicate").json()) == 1
    assert len(client.get("/api/conflicts").json()) == 5          # 1001 status, 1002 kind + raw, 1009 status, 1013 owner
    assert any(f["code"] == "malformed_email" for f in client.get("/api/quality").json())
    u = client.get("/api/unmatched").json()
    assert {x["source_id"] for x in u["crm"]} == {"CRM-1003","CRM-1004","CRM-1007","CRM-1010","CRM-1016","CRM-1020"}
    s = client.get("/api/stats").json()
    assert s["meetings_by_kind"] == {"auto": 14, "proposed": 7, "singleton": 7} and s["config"]["tight_window_min"] == 10

def test_sync_and_failure_keeps_store(client, monkeypatch):
    assert client.post("/api/sync").status_code == 200
    import eventsync.api.routes as routes
    monkeypatch.setattr(routes, "build_store", lambda s: (_ for _ in ()).throw(FileNotFoundError("x")))
    r = client.post("/api/sync")
    assert r.status_code == 500 and r.json()["error"]["code"] == "sync_failed"
    assert len(client.get("/api/meetings").json()) == 28

def test_root_serves_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
```
(`test_root_serves_page` passes once Task 10 adds `web/index.html`; a placeholder `index.html` with `<html></html>` is created in this task.)

- [ ] **Step 2: Run** → FAIL.  **Step 3: Implement.**  **Step 4: Run** `uv run pytest -v` → all PASS.  **Step 5: Checkpoint.**

---

### Task 10: Frontend

**Files:**
- Create/replace: `web/index.html`, `web/app.js`, `web/styles.css`

**Interfaces:**
- Consumes the API from Task 9 only. No build step, no framework, no external CDN (works offline).
- Tabs: Meetings, Proposals, Quality, Unmatched. Detail panel per spec §11 with three columns (Reconciled, CRM, Calendar), row class = field status, rule text shown under the reconciled value, match key and evidence at the top, collapsible raw JSON per source.
- Filters: source, has_conflict, level, owner, status; all map 1:1 to query params.
- Status colours as CSS classes `.agree .conflict .differs .single_source .missing .unresolved` with a legend.

- [ ] **Step 1: Write a smoke test** in `tests/test_web.py`: `GET /` contains `id="tab-meetings"`, `GET /app.js` and `GET /styles.css` return 200.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the three files. `app.js` fetches `/api/meetings` with current filters, renders the table, fetches `/api/meetings/{id}` on row click.
- [ ] **Step 4: Run** tests → PASS. Start `uv run eventsync`, open `http://127.0.0.1:8000/`, check manually: 28 rows; CRM-1002 detail shows location kind row as unresolved with Zoom vs In-Person; Proposals tab shows 4 with the 60-minute whole-hour reason on 1004/A4; Unmatched shows CRM-1003 with CAL-A7 as best rejected. Record the check in `tasks/todo.md`.
- [ ] **Step 5: Checkpoint.**

---

### Task 11: README and AI-collaboration docs

**Files:**
- Create: `README.md`, `docs/ai-collaboration/README.md`
- Modify: `tasks/todo.md` (review section, time log)

**Interfaces:** none; documentation of Tasks 1–10 and the spec.

- [ ] **Step 1: Write `README.md`** with, in order: title and one-paragraph purpose; **Run** (`uv run eventsync`, URL, `uv run pytest`); **What you will see** (tabs, status colours); **Approach** (pipeline diagram from the plan header, the identity principle "participants plus a tight start window, nothing merged on behavioural assumptions"); **Data findings** (spec §4 trap table with a "what the service does" column); **Reconciliation cascade** (spec §8 table with authority and the resulting counts 14/7/7, 28 meetings); **Winner rules** (spec §9); **API** (spec §10 table); **Key decisions** (one paragraph each: cascade over scoring; ±10 minute window; UTC taken at face value; comparable vs complementary fields; proposals read-only; in-memory store); **Not built, and where it would go** (spec §12); **Project layout**; **Time spent** (table: research, EDA, design, build, docs; honest hours); **AI collaboration** (link to `docs/ai-collaboration/README.md`).
- [ ] **Step 2: Write `docs/ai-collaboration/README.md`**: index linking `notebooks/eda.ipynb`, `notebooks/research_notes/`, `notebooks/reports/Enterprise dirty record reconciliation.md`, the spec, this plan, `tasks/todo.md`, `tasks/lessons.md`; a short narrative (how the EDA drove the design, the correction from day+client identity to participant containment, the research findings that changed the design: differs status, whole-hour gap, decisions ledger as future work).
- [ ] **Step 3: Verify** every README command runs as written from a fresh shell (`uv run eventsync`, `uv run pytest`), every file link resolves, counts in the README match `GET /api/stats`.
- [ ] **Step 4: Fill** the review section and time log in `tasks/todo.md`. Checkpoint.
