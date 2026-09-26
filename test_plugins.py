"""Offline contract tests for the first event source connector."""

from __future__ import annotations

import json
import csv
import tempfile
import unittest
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from src.pipeline.attendance import VenueAttendanceEstimator
from src.pipeline.base import EventDraft, parse_datetime_utc
from src.pipeline.event_csv import CSV_COLUMNS
from src.pipeline.event_workbook import EventWorkbookExporter
from src.pipeline.orchestrator import EventIngestionJob
from src.pipeline.plugins.event_plugin import VanMieuEventSource
from src.pipeline.plugins.football import VffFootballEventSource, VpfFootballEventSource
from src.pipeline.plugins.concert import TicketboxConcertEventSource
from src.pipeline.plugins.festival import TicketboxFestivalEventSource
from src.pipeline.storage import EventLake


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any] | None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content

    def json(self) -> dict[str, Any] | None:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("The test supplied too few fake responses.")
        return self.responses.pop(0)


class VanMieuEventPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name) / "data"
        self.source_config = {
            "enabled": True,
            "endpoint": "https://example.test/api/events",
            "listing_url": "https://example.test/events",
            "locale": "vi",
            "limit": 2,
            "max_pages": 5,
            "timeout_seconds": 1,
            "max_retries": 0,
            "watermark_overlap_minutes": 10,
            "full_scan_every_runs": 4,
            "scope_city": "hanoi",
        }
        self.config = {
            "pipeline": {"data_dir": str(self.data_dir)},
            "events": {
                "attendance_estimation": {
                    "fill_missing_with_heuristic": True,
                    "default_venue_capacity": 1000,
                    "default_fill_rate": 0.50,
                    "fill_rates": {"cultural_event": 0.50, "other": 0.50},
                    "venue_capacities": {
                        "SVD My Dinh": {
                            "capacity": 40000,
                            "aliases": ["San van dong My Dinh"],
                        }
                    },
                },
                "sources": {"van_mieu": self.source_config},
            },
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def event_document(
        event_id: str = "event-1",
        start: str = "2026-10-01T02:00:00.000Z",
        updated: str = "2026-09-20T08:00:00.000Z",
    ) -> dict[str, Any]:
        return {
            "id": event_id,
            "title": "Su kien thu nghiem",
            "description": None,
            "contentLeft": {
                "root": {"children": [{"type": "text", "text": "Mo ta tu rich text"}]}
            },
            "contentRight": None,
            "startDate": start,
            "endDate": None,
            "location": None,
            "category": "cultural",
            "slug": "su-kien-thu-nghiem",
            "updatedAt": updated,
            "createdAt": "2026-09-01T08:00:00.000Z",
            "_status": "published",
        }

    def make_source(self, responses: list[FakeResponse]) -> tuple[VanMieuEventSource, FakeSession]:
        session = FakeSession(responses)
        source = VanMieuEventSource(
            self.source_config,
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )
        return source, session

    def test_pagination_category_and_timezone_normalization(self) -> None:
        first = self.event_document("first")
        second = self.event_document("second")
        source, session = self.make_source(
            [
                FakeResponse(
                    {
                        "docs": [first],
                        "hasNextPage": True,
                        "nextPage": 2,
                    }
                ),
                FakeResponse(
                    {
                        "docs": [second],
                        "hasNextPage": False,
                        "nextPage": None,
                    }
                ),
            ]
        )

        fetched = source.fetch({}, full_scan=True)
        normalized = source.normalize(fetched.fetched_records[0])

        self.assertEqual(2, len(fetched.fetched_records))
        self.assertEqual([1, 2], [call["params"]["page"] for call in session.calls])
        self.assertEqual("cultural_event", normalized.primary_category)
        self.assertEqual("Mo ta tu rich text", normalized.description)
        self.assertEqual(
            "2026-10-01T02:00:00Z",
            parse_datetime_utc("2026-10-01T09:00:00+07:00", "test"),
        )

    def test_utf8_response_bytes_are_parsed_directly(self) -> None:
        correct_document = {**self.event_document(), "title": "Sự kiện Văn Miếu"}
        correct_payload = {"docs": [correct_document], "hasNextPage": False}
        incorrectly_decoded_payload = {
            "docs": [
                {
                    **correct_document,
                    "title": "Sá»± kiá»‡n VÄƒn Miáº¿u",
                }
            ],
            "hasNextPage": False,
        }
        response_bytes = json.dumps(
            correct_payload, ensure_ascii=False
        ).encode("utf-8")
        source, _ = self.make_source(
            [
                FakeResponse(
                    incorrectly_decoded_payload,
                    content=response_bytes,
                )
            ]
        )

        fetched = source.fetch({}, full_scan=True)

        self.assertEqual("Sự kiện Văn Miếu", fetched.fetched_records[0]["title"])

    def test_invalid_record_is_quarantined_without_losing_valid_records(self) -> None:
        valid = self.event_document("valid")
        invalid = self.event_document(
            "invalid",
            start="2026-10-01T04:00:00.000Z",
        )
        invalid["endDate"] = "2026-10-01T03:00:00.000Z"
        source, _ = self.make_source(
            [FakeResponse({"docs": [valid, invalid], "hasNextPage": False})]
        )
        job = EventIngestionJob(
            self.config,
            "van_mieu",
            source=source,
            lake=EventLake(self.data_dir),
        )

        summary = job.run()

        self.assertEqual("success", summary["status"])
        self.assertEqual(1, summary["valid"])
        self.assertEqual(1, summary["rejected"])
        quarantine_files = list(self.data_dir.rglob("rejected_records.jsonl"))
        self.assertEqual(1, len(quarantine_files))
        self.assertIn("endDate cannot be earlier", quarantine_files[0].read_text())

    def test_identical_payload_does_not_create_a_second_revision(self) -> None:
        payload = {"docs": [self.event_document()], "hasNextPage": False}
        first_source, _ = self.make_source([FakeResponse(payload)])
        first_summary = EventIngestionJob(
            self.config,
            "van_mieu",
            source=first_source,
            lake=EventLake(self.data_dir),
        ).run()

        second_source, _ = self.make_source([FakeResponse(payload)])
        second_summary = EventIngestionJob(
            self.config,
            "van_mieu",
            source=second_source,
            lake=EventLake(self.data_dir),
        ).run()

        self.assertEqual(1, first_summary["new"])
        self.assertEqual(0, second_summary["new"])
        self.assertEqual(1, second_summary["unchanged"])
        version_records = []
        for path in self.data_dir.rglob("*.jsonl"):
            if "event_versions" in path.as_posix():
                version_records.extend(
                    json.loads(line) for line in path.read_text().splitlines() if line
                )
        self.assertEqual(1, len(version_records))
        current_files = list(self.data_dir.rglob("events_current/**/events.jsonl"))
        self.assertEqual(1, len(current_files))
        current_record = json.loads(current_files[0].read_text().strip())
        self.assertEqual(1, current_record["revision"])

    def test_csv_uses_hanoi_time_and_capacity_fill_rate(self) -> None:
        document = self.event_document()
        document["location"] = "Sân vận động Mỹ Đình"
        source, _ = self.make_source(
            [FakeResponse({"docs": [document], "hasNextPage": False})]
        )
        summary = EventIngestionJob(
            self.config,
            "van_mieu",
            source=source,
            lake=EventLake(self.data_dir),
        ).run()

        with (self.data_dir / "events.csv").open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual("events.csv", summary["csv_path"])
        self.assertEqual(1, len(rows))
        self.assertEqual("01/10/26", rows[0]["start_date"])
        self.assertEqual("09:00", rows[0]["start_time"])
        self.assertEqual("20000", rows[0]["estimate_attendence"])
        self.assertEqual(
            "https://example.test/api/events/event-1",
            rows[0]["source_url"],
        )

    def test_public_article_url_is_resolved_from_listing_pagination(self) -> None:
        source_config = {
            **self.source_config,
            "resolve_article_urls": True,
            "article_listing_urls": {
                "cultural": "https://example.test/events/cultural",
            },
            "article_listing_max_pages": 2,
        }
        document = self.event_document()
        document["slug"] = "Sự-kiện-thử-nghiệm"
        first_listing = """
        <a href="?endedPage=2">Trang 2</a>
        <a href="/vi/events/event-calendar/ended-events/su-kien-khac">
          Sự kiện khác
        </a>
        """
        second_listing = """
        <a href="/vi/events/event-calendar/ended-events/S%E1%BB%B1-ki%E1%BB%87n-th%E1%BB%AD-nghi%E1%BB%87m">
          Sự kiện thử nghiệm
        </a>
        """
        session = FakeSession(
            [
                FakeResponse({"docs": [document], "hasNextPage": False}),
                FakeResponse(None, content=first_listing.encode("utf-8")),
                FakeResponse(None, content=second_listing.encode("utf-8")),
            ]
        )
        source = VanMieuEventSource(
            source_config,
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        fetched = source.fetch({}, full_scan=True)
        draft = source.normalize(fetched.fetched_records[0])

        expected_url = (
            "https://example.test/vi/events/event-calendar/ended-events/"
            "S%E1%BB%B1-ki%E1%BB%87n-th%E1%BB%AD-nghi%E1%BB%87m"
        )
        self.assertEqual(expected_url, draft.source_url)
        self.assertEqual(
            "https://example.test/events/cultural?endedPage=2",
            session.calls[2]["url"],
        )
        self.assertEqual(
            expected_url,
            fetched.state_updates["article_url_cache_by_slug"]["sự-kiện-thử-nghiệm"],
        )

    def test_full_scan_refreshes_a_cached_public_article_url(self) -> None:
        source_config = {
            **self.source_config,
            "resolve_article_urls": True,
            "article_listing_urls": {
                "cultural": "https://example.test/events/cultural",
            },
            "article_listing_max_pages": 1,
        }
        document = self.event_document()
        document["slug"] = "su-kien-thu-nghiem"
        ended_url = (
            "https://example.test/vi/events/event-calendar/ended-events/"
            "su-kien-thu-nghiem"
        )
        listing = f'<a href="{ended_url}">Sự kiện thử nghiệm</a>'
        session = FakeSession(
            [
                FakeResponse({"docs": [document], "hasNextPage": False}),
                FakeResponse(None, content=listing.encode("utf-8")),
            ]
        )
        source = VanMieuEventSource(
            source_config,
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        fetched = source.fetch(
            {
                "etag": "old-etag",
                "article_url_cache_by_slug": {
                    "su-kien-thu-nghiem": (
                        "https://example.test/vi/events/event-calendar/"
                        "upcoming-events/su-kien-thu-nghiem"
                    )
                },
            },
            full_scan=True,
        )

        self.assertNotIn("If-None-Match", session.calls[0]["headers"])
        self.assertEqual(2, len(session.calls))
        self.assertEqual(ended_url, source.normalize(fetched.fetched_records[0]).source_url)

    def test_workbook_creates_the_five_event_sheets(self) -> None:
        self.data_dir.mkdir(parents=True)
        rows = [
            {
                "event_name": "CLB Hà Nội vs Hải Phòng",
                "venue": "SVD Hàng Đẫy",
                "start_date": "01/05/26", "start_time": "19:15", "end_time": "21:15",
                "type": "football",
                "estimate_attendence": "", "attendance_source_url": "",
                "source_url": "https://example.test/match",
            },
            {
                "event_name": "Concert Sơn Tùng MTP",
                "venue": "Mỹ Đình",
                "start_date": "02/05/26", "start_time": "20:00", "end_time": "",
                "type": "other",
                "estimate_attendence": "", "attendance_source_url": "",
                "source_url": "https://example.test/concert",
            },
            {
                "event_name": "Lễ hội mùa hè",
                "venue": "Hà Nội",
                "start_date": "03/05/26", "start_time": "09:00", "end_time": "",
                "type": "cultural_event",
                "estimate_attendence": "", "attendance_source_url": "",
                "source_url": "https://example.test/festival",
            },
            {
                "event_name": "Triển lãm di sản",
                "venue": "Văn Miếu",
                "start_date": "04/05/26", "start_time": "09:00", "end_time": "",
                "type": "cultural_event",
                "estimate_attendence": "", "attendance_source_url": "",
                "source_url": "https://example.test/exhibition",
            },
            {
                "event_name": "Ngày tựu trường",
                "venue": "Hà Nội",
                "start_date": "05/05/26", "start_time": "07:00", "end_time": "",
                "type": "school_calendar",
                "estimate_attendence": "", "attendance_source_url": "",
                "source_url": "https://example.test/school",
            },
        ]
        with (self.data_dir / "event.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        result = EventWorkbookExporter(self.data_dir).export()
        workbook = load_workbook(self.data_dir / "event.xlsx", read_only=True)

        self.assertEqual("event.xlsx", result["path"])
        self.assertEqual(
            ["all", "football", "concert", "festival", "exhibition", "other"],
            workbook.sheetnames,
        )
        self.assertEqual(
            list(CSV_COLUMNS),
            [cell.value for cell in next(workbook["football"].iter_rows(max_row=1))],
        )
        self.assertEqual(
            {
                "all": 5,
                "football": 1,
                "concert": 1,
                "festival": 1,
                "exhibition": 1,
                "other": 1,
            },
            result["sheets"],
        )
        workbook.close()

    def test_missing_attendance_stays_blank_when_heuristic_is_disabled(self) -> None:
        self.config["events"]["attendance_estimation"][
            "fill_missing_with_heuristic"
        ] = False
        document = self.event_document()
        document["location"] = "SÃ¢n váº­n Ä‘á»™ng Má»¹ ÄÃ¬nh"
        source, _ = self.make_source(
            [FakeResponse({"docs": [document], "hasNextPage": False})]
        )

        EventIngestionJob(
            self.config,
            "van_mieu",
            source=source,
            lake=EventLake(self.data_dir),
        ).run()

        with (self.data_dir / "events.csv").open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual("", rows[0]["estimate_attendence"])

    def test_verified_attendance_override_adds_its_evidence_url(self) -> None:
        estimator = VenueAttendanceEstimator(
            {
                "reported_attendance_overrides": [
                    {
                        "source": "vff_football",
                        "title": "Việt Nam vs Singapore",
                        "start_at_utc": "2026-07-31T13:00:00Z",
                        "attendance": 31569,
                        "source_url": "https://example.test/attendance-report",
                    }
                ]
            }
        )
        draft = EventDraft(
            source="vff_football",
            source_event_id="singapore-2026",
            title="Việt Nam vs Singapore",
            description=None,
            raw_category="asean_cup",
            primary_category="football",
            publication_status=None,
            event_status="scheduled",
            start_at_utc="2026-07-31T13:00:00Z",
            end_at_utc=None,
            venue_raw="SVĐQG Mỹ Đình, Hà Nội",
            source_url="https://example.test/fixture",
            source_created_at_utc=None,
            source_updated_at_utc=None,
            raw_payload_sha256="abc",
        )

        enriched = estimator.enrich(draft)

        self.assertEqual(31569, enriched.estimated_attendees)
        self.assertEqual("verified_reported_attendance", enriched.attendee_estimation_method)
        self.assertEqual(
            "https://example.test/attendance-report", enriched.attendance_source_url
        )

    def test_csv_excludes_events_outside_the_configured_date_window(self) -> None:
        self.config["events"]["event_date_window"] = {
            "start_date": "2026-04-13",
            "end_date": "2026-09-23",
        }
        source, _ = self.make_source(
            [FakeResponse({"docs": [self.event_document()], "hasNextPage": False})]
        )

        summary = EventIngestionJob(
            self.config,
            "van_mieu",
            source=source,
            lake=EventLake(self.data_dir),
        ).run()

        with (self.data_dir / "events.csv").open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(0, summary["csv_records"])
        self.assertEqual([], rows)

    def test_vpf_connector_filters_hanoi_and_keeps_reported_attendance(self) -> None:
        html = """
        <div class="jsrow-matchday-name">Vòng 2 V.League</div>
        <div class="js-matchday-wrapper">
          <p class="js-matchday-date">10 Tháng 09, 2026</p>
          <div class="jstable-row">
            <div class="jstable-cell jsMatchDivTime">19:15</div>
            <div class="jstable-cell js-ma-tran">8</div>
            <div class="jstable-cell jsMatchDivVenue">SVĐ Hàng Đẫy</div>
            <div class="jstable-cell jsMatchDivHome">Thể Công Viettel</div>
            <div class="jstable-cell jsMatchDivScore">
              <a href="/match/the-cong-viettel-vs-cong-an-ha-noi/">v</a>
            </div>
            <div class="jstable-cell jsMatchDivAway">Công an Hà Nội</div>
            <div class="jstable-cell jsChannelDiv">FPT Play</div>
            <div class="jstable-cell js-audience">KG: 8000 người</div>
          </div>
          <div class="jstable-row">
            <div class="jstable-cell jsMatchDivTime">18:00</div>
            <div class="jstable-cell jsMatchDivVenue">SVĐ Lạch Tray</div>
            <div class="jstable-cell jsMatchDivHome">Hải Phòng</div>
            <div class="jstable-cell jsMatchDivAway">Ninh Bình</div>
          </div>
        </div>
        """
        source_config = {
            "calendars": {"v_league_1": "https://example.test/calendar"},
            "hanoi_venue_allowlist": ["SVD Hang Day", "SVD My Dinh"],
            "timezone": "Asia/Ho_Chi_Minh",
            "default_duration_minutes": 120,
            "timeout_seconds": 1,
            "max_retries": 0,
        }
        source = VpfFootballEventSource(
            source_config,
            session=FakeSession([FakeResponse(None, content=html.encode("utf-8"))]),
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        fetched = source.fetch({}, full_scan=True)
        draft = source.normalize(fetched.fetched_records[0])

        self.assertEqual(1, len(fetched.fetched_records))
        self.assertEqual("football", draft.primary_category)
        self.assertEqual("2026-09-10T12:15:00Z", draft.start_at_utc)
        self.assertEqual("2026-09-10T14:15:00Z", draft.end_at_utc)
        self.assertEqual(8000, draft.official_attendance)

    def test_vff_notice_creates_a_hanoi_asean_cup_fixture(self) -> None:
        listing = """
        <div class="post-item">
          <a href="/thong-bao-ban-ve-tran-chung-ket-dt-viet-nam-vs-dt-thai-lan-asean-hyundai-cup-2026/">
            Thông báo bán vé trận chung kết ASEAN Cup
          </a>
        </div>
        """
        article = """
        <h1 class="post-title">
          Thông báo bán vé Trận chung kết ĐT Việt Nam vs ĐT Thái Lan (Asean Hyundai Cup 2026)
        </h1>
        <div class="entry-content">
          BTC thông báo trận đấu diễn ra lúc 20h00 ngày 26/8/2026 tại SVĐQG Mỹ Đình, Hà Nội như sau.
        </div>
        """
        source = VffFootballEventSource(
            {
                "listing_url": "https://vff.org.vn/chuyen-muc/tin-tuc/thong-tin-ve/",
                "max_listing_pages": 1,
                "timezone": "Asia/Ho_Chi_Minh",
                "timeout_seconds": 1,
                "max_retries": 0,
                "scope_city": "hanoi",
            },
            session=FakeSession(
                [
                    FakeResponse(None, content=listing.encode("utf-8")),
                    FakeResponse(None, content=article.encode("utf-8")),
                ]
            ),
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        fetched = source.fetch({}, full_scan=True)
        draft = source.normalize(fetched.fetched_records[0])

        self.assertEqual(1, len(fetched.fetched_records))
        self.assertEqual("football", draft.primary_category)
        self.assertEqual("asean_cup", draft.raw_category)
        self.assertEqual("2026-08-26T13:00:00Z", draft.start_at_utc)
        self.assertEqual("2026-08-26T15:00:00Z", draft.end_at_utc)
        self.assertEqual("SVĐQG Mỹ Đình, Hà Nội", draft.venue_raw)
        self.assertEqual(
            "https://vff.org.vn/thong-bao-ban-ve-tran-chung-ket-dt-viet-nam-vs-dt-thai-lan-asean-hyundai-cup-2026/",
            draft.source_url,
        )

    def test_ticketbox_concert_keeps_only_hanoi_music_events(self) -> None:
        search_payload = {
            "data": {
                "results": [
                    {
                        "id": 101,
                        "name": "Concert Hà Nội",
                        "deeplink": "https://ticketbox.vn/concert-ha-noi-101?utm_source=test",
                    },
                    {
                        "id": 102,
                        "name": "Concert Hồ Chí Minh",
                        "deeplink": "https://ticketbox.vn/concert-hcm-102",
                    },
                    {
                        "id": 103,
                        "name": "Concert Merchandise",
                        "deeplink": "https://ticketbox.vn/concert-merch-103",
                    },
                ],
                "pagination": {"hasMore": False},
            }
        }

        def event_page(event_id: int, title: str, address: str) -> bytes:
            payload = {
                "props": {
                    "pageProps": {
                        "description": "Mô tả concert",
                        "infoEvent": {
                            "id": event_id,
                            "title": title,
                            "venue": "Nhà hát thử nghiệm",
                            "address": address,
                            "startTime": "2026-07-12T13:00:00Z",
                            "endTime": "2026-07-12T15:00:00Z",
                            "categories": ["music"],
                            "status": 3,
                        },
                    }
                }
            }
            return (
                '<script id="__NEXT_DATA__" type="application/json">'
                + json.dumps(payload, ensure_ascii=False)
                + "</script>"
            ).encode("utf-8")

        session = FakeSession(
            [
                FakeResponse(search_payload),
                FakeResponse(None, content=event_page(101, "Concert Hà Nội", "Hà Nội")),
                FakeResponse(None, content=event_page(102, "Concert Hồ Chí Minh", "TP. Hồ Chí Minh")),
                FakeResponse(None, content=event_page(103, "Concert Merchandise", "Hà Nội")),
            ]
        )
        source = TicketboxConcertEventSource(
            {
                "search_url": "https://api.ticketbox.test/v2/events",
                "category": "music",
                "from_date": "2026-04-13",
                "to_date": "2026-09-22",
                "page_size": 100,
                "max_pages": 1,
                "timeout_seconds": 1,
                "max_retries": 0,
                "scope_city": "hanoi",
            },
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        fetched = source.fetch({}, full_scan=True)
        draft = source.normalize(fetched.fetched_records[0])

        self.assertEqual(1, len(fetched.fetched_records))
        self.assertEqual("concert", draft.primary_category)
        self.assertEqual("2026-07-12T13:00:00Z", draft.start_at_utc)
        self.assertEqual("2026-07-12T15:00:00Z", draft.end_at_utc)
        self.assertEqual("https://ticketbox.vn/concert-ha-noi-101", draft.source_url)

    def test_ticketbox_festival_uses_public_search_then_verifies_hanoi(self) -> None:
        search_payload = {
            "data": {
                "results": [
                    {
                        "id": 201,
                        "name": "Lễ hội thử nghiệm Hà Nội",
                        "deeplink": "https://ticketbox.vn/festival-ha-noi-201?utm_source=test",
                    },
                    {
                        "id": 202,
                        "name": "Festival tại Đà Nẵng",
                        "deeplink": "https://ticketbox.vn/festival-da-nang-202",
                    },
                ],
                "pagination": {"hasMore": False},
            }
        }

        def event_page(event_id: int, title: str, address: str) -> bytes:
            payload = {
                "props": {
                    "pageProps": {
                        "description": "Nội dung lễ hội",
                        "infoEvent": {
                            "id": event_id,
                            "title": title,
                            "venue": "Địa điểm thử nghiệm",
                            "address": address,
                            "startTime": "2026-07-12T13:00:00Z",
                            "endTime": "2026-07-12T15:00:00Z",
                            "status": 3,
                        },
                    }
                }
            }
            return (
                '<script id="__NEXT_DATA__" type="application/json">'
                + json.dumps(payload, ensure_ascii=False)
                + "</script>"
            ).encode("utf-8")

        source = TicketboxFestivalEventSource(
            {
                "search_url": "https://api.ticketbox.test/v2/events",
                "from_date": "2026-04-13",
                "to_date": "2026-09-22",
                "page_size": 100,
                "max_pages": 1,
                "timeout_seconds": 1,
                "max_retries": 0,
                "scope_city": "hanoi",
            },
            session=FakeSession(
                [
                    FakeResponse(search_payload),
                    FakeResponse(None, content=event_page(201, "Lễ hội thử nghiệm Hà Nội", "Hà Nội")),
                    FakeResponse(None, content=event_page(202, "Festival tại Đà Nẵng", "Đà Nẵng")),
                ]
            ),
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        fetched = source.fetch({}, full_scan=True)
        draft = source.normalize(fetched.fetched_records[0])

        self.assertEqual(1, len(fetched.fetched_records))
        self.assertEqual("festival", draft.primary_category)
        self.assertEqual("festival", draft.raw_category)
        self.assertEqual("2026-07-12T13:00:00Z", draft.start_at_utc)
        self.assertEqual("2026-07-12T15:00:00Z", draft.end_at_utc)
        self.assertEqual("https://ticketbox.vn/festival-ha-noi-201", draft.source_url)


if __name__ == "__main__":
    unittest.main()
