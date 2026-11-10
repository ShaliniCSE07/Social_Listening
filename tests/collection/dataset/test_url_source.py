"""Tests for Dataset plugin URL source reader."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import zipfile
import pytest
import responses

from src.collection.base import CollectionRequest
from src.collection.plugins.dataset.catalogue import DatasetEntry
from src.collection.plugins.dataset.connector import DatasetConnector
from src.collection.plugins.dataset.sources.url import UrlSource, resolve_url
from src.contracts.enums import AttemptStatus


@pytest.fixture
def mock_csv_content() -> str:
    return "id,brand,text\nu1,Zomato,Great food from Zomato\nu2,Swiggy,Fast delivery from Swiggy\n"


@responses.activate
def test_url_source_download_then_parse(tmp_path, mock_csv_content):
    url = "https://example.com/data.csv"
    responses.add(
        responses.GET,
        url,
        body=mock_csv_content,
        status=200,
        headers={"Last-Modified": "Wed, 21 Oct 2025 07:28:00 GMT"},
    )

    entry = DatasetEntry(
        key="remote_csv",
        name="Remote CSV",
        source_type="url",
        path_or_ref=url,
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
        license_note="CC-BY-4.0",
    )

    connector = DatasetConnector(
        catalogue={"remote_csv": entry}, download_dir=tmp_path / "downloads"
    )
    # Use tmp_path for download dir
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert attempt.status == AttemptStatus.success
    assert mentions[0].item_id == "u1"
    assert "downloaded from URL" in attempt.reason
    assert "License: CC-BY-4.0" in attempt.reason

    # Basis should be http_last_modified
    assert mentions[0].raw_payload["dataset_last_updated_basis"] == "http_last_modified"


@responses.activate
def test_url_source_reuse_without_second_download(tmp_path, mock_csv_content):
    url = "https://example.com/cached.csv"
    responses.add(
        responses.GET,
        url,
        body=mock_csv_content,
        status=200,
        headers={"Last-Modified": "Wed, 21 Oct 2025 07:28:00 GMT"},
    )

    dl_dir = tmp_path / "downloads"
    source = UrlSource("Cached", "cached_key", url, "csv", download_dir=dl_dir)

    # First download
    path1, was_dl1 = source.download_if_needed()
    assert was_dl1 is True
    assert len(responses.calls) == 1

    # Second call without refresh -> reuse
    source2 = UrlSource("Cached", "cached_key", url, "csv", download_dir=dl_dir, refresh=False)
    path2, was_dl2 = source2.download_if_needed()
    assert was_dl2 is False
    assert len(responses.calls) == 1  # No second HTTP call


@responses.activate
def test_url_source_refresh_forces_download(tmp_path, mock_csv_content):
    url = "https://example.com/refresh.csv"
    responses.add(
        responses.GET,
        url,
        body=mock_csv_content,
        status=200,
    )

    dl_dir = tmp_path / "downloads"
    source = UrlSource("Refresh", "ref_key", url, "csv", download_dir=dl_dir)
    source.download_if_needed()
    assert len(responses.calls) == 1

    # Call with refresh=True -> re-downloads
    source_ref = UrlSource("Refresh", "ref_key", url, "csv", download_dir=dl_dir, refresh=True)
    _, was_dl = source_ref.download_if_needed()
    assert was_dl is True
    assert len(responses.calls) == 2


@responses.activate
def test_missing_last_modified_header_falls_back(tmp_path, mock_csv_content):
    url = "https://example.com/nomod.csv"
    responses.add(
        responses.GET,
        url,
        body=mock_csv_content,
        status=200,
        # No Last-Modified header
    )

    entry = DatasetEntry(
        key="nomod_csv",
        name="No Mod CSV",
        source_type="url",
        path_or_ref=url,
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
        last_updated_override="2024-05-01T00:00:00Z",
    )

    connector = DatasetConnector(catalogue={"nomod_csv": entry})
    request = CollectionRequest(company="Zomato")
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    # Fallback to catalogue override
    assert mentions[0].raw_payload["dataset_last_updated_basis"] == "catalogue_override"


@responses.activate
def test_no_header_and_no_override_records_unknown_source_date(tmp_path, mock_csv_content):
    url = "https://example.com/unknown_date.csv"
    responses.add(
        responses.GET,
        url,
        body=mock_csv_content,
        status=200,
    )

    entry = DatasetEntry(
        key="unk_csv",
        name="Unknown Date CSV",
        source_type="url",
        path_or_ref=url,
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
        last_updated_override=None,
    )

    connector = DatasetConnector(catalogue={"unk_csv": entry})
    request = CollectionRequest(company="Zomato")
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert mentions[0].raw_payload["dataset_last_updated_basis"] == "unknown source date"


@responses.activate
def test_url_source_404_error(tmp_path):
    url = "https://example.com/notfound.csv"
    responses.add(responses.GET, url, status=404)

    entry = DatasetEntry(
        key="err404",
        name="404 CSV",
        source_type="url",
        path_or_ref=url,
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text"},
    )

    connector = DatasetConnector(catalogue={"err404": entry})
    request = CollectionRequest(company="Zomato")
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "404" in attempt.reason


@responses.activate
def test_url_source_size_limit(tmp_path):
    url = "https://example.com/toolarge.csv"
    large_payload = "a" * (2 * 1024 * 1024)  # 2MB
    responses.add(responses.GET, url, body=large_payload, status=200)

    dl_dir = tmp_path / "downloads"
    source = UrlSource("Large", "large_key", url, "csv", download_dir=dl_dir)
    source.max_download_mb = 1.0  # Max 1 MB

    with pytest.raises(ValueError) as exc_info:
        source.download_if_needed()
    assert "exceeded maximum limit" in str(exc_info.value)
    # Ensure partial download was deleted
    assert not (dl_dir / "large_key" / "toolarge.csv.tmp").exists()


@responses.activate
def test_url_source_unpacked_size_limit(tmp_path):
    url = "https://example.com/unpacked_too_large.zip"

    # Create zip in-memory with unpacked data larger than limit
    csv_data = "x" * (2 * 1024 * 1024)  # 2MB unpacked
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("huge_file.csv", csv_data)
    zip_bytes = zip_buffer.getvalue()

    responses.add(
        responses.GET,
        url,
        body=zip_bytes,
        status=200,
        content_type="application/zip",
    )

    dl_dir = tmp_path / "downloads"
    source = UrlSource("ZipHuge", "zip_huge_key", url, "zip", download_dir=dl_dir)
    source.max_download_mb = 10.0
    source.max_unpacked_mb = 1.0  # Max 1 MB unpacked

    with pytest.raises(ValueError) as exc_info:
        source.download_if_needed()
    assert "Unpacked dataset size exceeded maximum limit" in str(exc_info.value)
    # Ensure cleaned up
    assert not (dl_dir / "zip_huge_key" / "huge_file.csv").exists()


@responses.activate
def test_url_source_zip_handling(tmp_path):
    url = "https://example.com/archive.zip"

    # Create zip in-memory
    csv_data = "id,text\nz1,Zomato inside zip\n"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inner_data.csv", csv_data)
    zip_bytes = zip_buffer.getvalue()

    responses.add(
        responses.GET,
        url,
        body=zip_bytes,
        status=200,
        content_type="application/zip",
    )

    dl_dir = tmp_path / "downloads"
    source = UrlSource("ZipDS", "zip_key", url, "zip", download_dir=dl_dir)
    rows = list(source.iter_rows())

    assert len(rows) == 1
    assert rows[0]["id"] == "z1"
    assert rows[0]["text"] == "Zomato inside zip"


def test_hf_reference_resolves_to_correct_url():
    ref = "hf://owner/my-dataset/reviews.jsonl"
    resolved = resolve_url(ref)
    assert resolved == "https://huggingface.co/datasets/owner/my-dataset/resolve/main/reviews.jsonl"


@responses.activate
def test_token_never_appears_in_logs_or_errors(monkeypatch, tmp_path):
    token = "hf_secretToken987654321"
    monkeypatch.setenv("HUGGINGFACE_TOKEN", token)

    url = "https://huggingface.co/datasets/org/repo/resolve/main/file.csv"
    responses.add(responses.GET, url, status=403, body="Forbidden")

    entry = DatasetEntry(
        key="hf_ds",
        name="HF Dataset",
        source_type="url",
        path_or_ref=url,
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text"},
    )

    connector = DatasetConnector(catalogue={"hf_ds": entry})
    request = CollectionRequest(company="Zomato")
    mentions, attempt = connector.collect(request)

    assert attempt.status == AttemptStatus.failed
    assert token not in (attempt.reason or "")

