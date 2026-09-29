from __future__ import annotations

import base64
import struct
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import load_demo_geo as loader  # noqa: E402


def test_gds_uid_maps_series_accessions() -> None:
    assert loader.gds_uid("GSE98969") == "200098969"
    with pytest.raises(ValueError):
        loader.gds_uid("GSM1")


def test_demo_id_is_deterministic() -> None:
    assert loader.demo_id("GSE98969") == loader.demo_id("GSE98969")
    assert loader.demo_id("GSE98969") != loader.demo_id("GSE98970")


def test_parse_esummary_keeps_titled_series_and_first_pubmed_id() -> None:
    result = {
        "uids": ["200000001", "200000002", "200000003"],
        "200000001": {"accession": "GSE1", "title": " Title one ", "summary": "S1",
                      "pubmedids": ["111", "222"]},
        "200000002": {"accession": "GSE2", "title": "Title two", "summary": "S2", "pubmedids": []},
        "200000003": {"accession": "GSE3", "title": ""},
    }
    assert loader.parse_esummary(result) == {
        "GSE1": {"title": "Title one", "summary": "S1", "pmid": "111"},
        "GSE2": {"title": "Title two", "summary": "S2", "pmid": None},
    }


def test_append_abstracts_uses_full_corpus_format_and_reports_unavailable_ids() -> None:
    records = [
        {"source_id": "GSE1", "abstract_pubmed_pmid": "111"},
        {"source_id": "GSE2", "abstract_pubmed_pmid": "222"},
        {"source_id": "GSE3", "abstract_pubmed_pmid": "333"},
        {"source_id": "GSE4", "abstract_pubmed_pmid": None},
        {"source_id": "GSE5", "abstract_pubmed_pmid": "555"},  # not returned by GEO
    ]
    texts = {
        "GSE1": {"title": "t", "summary": "Short summary. ", "pmid": "111"},
        "GSE2": {"title": "t", "summary": "data", "pmid": "222"},
        "GSE3": {"title": "t", "summary": "Another.", "pmid": "333"},
        "GSE4": {"title": "t", "summary": "Unchanged.", "pmid": None},
    }
    appended, unavailable = loader.append_abstracts(
        records, texts, {"111": "Abstract one.", "222": "Abstract two."})

    assert appended == 2
    assert unavailable == ["333"]
    assert texts["GSE1"]["summary"] == "Short summary.\n\n[PubMed PMID:111] Abstract one."
    assert texts["GSE2"]["summary"] == "[PubMed PMID:222] Abstract two."
    assert texts["GSE3"]["summary"] == "Another."
    assert texts["GSE4"]["summary"] == "Unchanged."


async def test_fetch_summaries_requests_missing_accessions_again(monkeypatch) -> None:
    calls: list[list[str]] = []

    async def fake_esummary(_client: Any, accessions: list[str], _key: Any) -> dict[str, Any]:
        calls.append(list(accessions))
        # The first, large batch loses GSE2; the retry returns it. GSE3 never exists.
        answered = [a for a in accessions if a != "GSE3" and not (a == "GSE2" and len(calls) == 1)]
        result: dict[str, Any] = {"uids": []}
        for accession in answered:
            uid = loader.gds_uid(accession)
            result["uids"].append(uid)
            result[uid] = {"accession": accession, "title": f"title {accession}", "summary": ""}
        return result

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(loader, "_esummary", fake_esummary)
    monkeypatch.setattr(loader.asyncio, "sleep", no_sleep)

    found = await loader.fetch_summaries(["GSE1", "GSE2", "GSE3"], batch=200)

    assert sorted(found) == ["GSE1", "GSE2"]
    assert calls[0] == ["GSE1", "GSE2", "GSE3"]
    assert calls[1] == ["GSE2", "GSE3"]


def test_vector_of_rejects_wrong_dimension() -> None:
    good = {"source_id": "GSE1",
            "vector_f32_b64": base64.b64encode(struct.pack("<1024f", *([0.5] * 1024))).decode()}
    assert loader.vector_of(good)[:2] == [0.5, 0.5]
    bad = {"source_id": "GSE1", "vector_f32_b64": base64.b64encode(b"\0" * 16).decode()}
    with pytest.raises(SystemExit):
        loader.vector_of(bad)


def test_row_for_marks_demo_rows() -> None:
    record = {"source_id": "GSE1", "submission_date": "2020-01-02", "in_blinded_pool": True,
              "modality": ["scRNA-seq"], "platform": "21493"}
    row = loader.row_for(record, {"title": "t", "summary": "  s  ", "pmid": None})
    assert row["id"] == loader.demo_id("GSE1")
    assert row["abstract"] == "s"
    assert row["platform"] == "21493"
    assert '"demo_profile": "geo-v1"' in row["raw_metadata"]
    assert '"in_blinded_pool": true' in row["raw_metadata"]


def test_partition_excludes_records_whose_pubmed_abstract_was_not_restored() -> None:
    records = [
        {"source_id": "GSE1", "abstract_pubmed_pmid": "111"},
        {"source_id": "GSE2", "abstract_pubmed_pmid": "222"},
        {"source_id": "GSE3", "abstract_pubmed_pmid": None},
        {"source_id": "GSE4", "abstract_pubmed_pmid": None},
    ]
    texts = {accession: {"title": "t", "summary": "s", "pmid": None} for accession in ("GSE1", "GSE2", "GSE3")}
    kept, missing, excluded = loader.partition_records(records, texts, ["222"])
    assert [record["source_id"] for record, _ in kept] == ["GSE1", "GSE3"]
    assert missing == ["GSE4"]
    assert excluded == ["GSE2"]


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    async def post(self, _url: str, data: dict[str, Any]) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse(self.payload)


async def test_esummary_treats_no_document_answer_as_missing() -> None:
    client = _FakeClient({"header": {}, "esummaryresult": ["Invalid uid 200309831 at position=0"]})
    assert await loader._esummary(client, ["GSE309831"], None) == {"uids": []}
    assert client.calls == 1


async def test_esummary_fails_on_unexpected_answer(monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(loader.asyncio, "sleep", no_sleep)
    client = _FakeClient({"unexpected": True})
    with pytest.raises(SystemExit):
        await loader._esummary(client, ["GSE1"], None)
    assert client.calls == 4

