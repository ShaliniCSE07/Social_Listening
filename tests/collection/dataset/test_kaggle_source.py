"""Unit tests for Kaggle dataset source reader and connector integration."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional
import pytest

from src.collection.base import CollectionRequest
from src.collection.plugins.dataset.catalogue import DatasetEntry
from src.collection.plugins.dataset.connector import DatasetConnector
from src.collection.plugins.dataset.sources.kaggle import KaggleSource
from src.contracts.enums import AttemptStatus


@dataclass
class MockDataset:
    ref: str
    last_updated: datetime
    license_name: str


class MockKaggleApi:
    """Mock Kaggle client for testing without network."""

    def __init__(self, download_action=None, datasets=None, metadata_path=None):
        self.download_action = download_action
        self.datasets = datasets or []
        self.metadata_path = metadata_path
        self.download_file_calls = []
        self.download_files_calls = []
        self.authenticate_called = False

    def authenticate(self):
        self.authenticate_called = True

    def dataset_list(self, search=None):
        return self.datasets

    def dataset_download_file(
        self, dataset, file_name, path=None, force=False, quiet=True, unzip=True
    ):
        self.download_file_calls.append(
            {"dataset": dataset, "file_name": file_name, "path": path, "force": force}
        )
        if self.download_action:
            self.download_action(dataset, file_name, path)

    def dataset_download_files(
        self, dataset, path=None, force=False, quiet=True, unzip=True
    ):
        self.download_files_calls.append(
            {"dataset": dataset, "path": path, "force": force}
        )
        if self.download_action:
            self.download_action(dataset, None, path)

    def dataset_metadata(self, dataset, path):
        return self.metadata_path


@pytest.fixture
def sample_csv():
    return "id,brand,text\nk1,Zomato,Great food from Zomato\nk2,Swiggy,Fast delivery\n"


def test_kaggle_missing_credentials_skipped(monkeypatch, tmp_path):
    """When KAGGLE_USERNAME or KAGGLE_KEY are missing, can_run is False and attempt is skipped."""
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)

    can_run, reason = KaggleSource.can_run()
    assert can_run is False
    assert "Kaggle credentials missing" in reason

    entry = DatasetEntry(
        key="k_entry",
        name="Kaggle Dataset",
        source_type="kaggle",
        path_or_ref="owner/dataset-name",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
    )

    connector = DatasetConnector(
        catalogue={"k_entry": entry}, download_dir=tmp_path / "downloads"
    )
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.skipped
    assert "Kaggle credentials missing" in attempt.reason


def test_kaggle_success(monkeypatch, tmp_path, sample_csv):
    """Successful download and collection from Kaggle dataset."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey123")

    def fake_download(dataset, file_name, path):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        fname = file_name or "data.csv"
        (p / fname).write_text(sample_csv, encoding="utf-8")

    mock_datasets = [
        MockDataset(
            ref="owner/food-reviews",
            last_updated=datetime(2025, 7, 10, 12, 0, tzinfo=timezone.utc),
            license_name="CC-BY-4.0",
        )
    ]
    mock_api = MockKaggleApi(download_action=fake_download, datasets=mock_datasets)

    entry = DatasetEntry(
        key="food_revs",
        name="Food Reviews",
        source_type="kaggle",
        path_or_ref="owner/food-reviews",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
    )

    connector = DatasetConnector(
        catalogue={"food_revs": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert attempt.status == AttemptStatus.success
    assert mentions[0].item_id == "k1"
    assert "downloaded from Kaggle" in attempt.reason
    assert "License: CC-BY-4.0" in attempt.reason
    assert mentions[0].raw_payload["dataset_license"] == "CC-BY-4.0"
    assert "2025-07-10" in mentions[0].raw_payload["dataset_last_updated"]


def test_kaggle_not_found(monkeypatch, tmp_path):
    """When Kaggle returns 404 / dataset not found, attempt fails with clear reason."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey123")

    def raise_not_found(dataset, file_name, path):
        raise Exception("404 - Not Found: dataset owner/nonexistent does not exist")

    mock_api = MockKaggleApi(download_action=raise_not_found)

    entry = DatasetEntry(
        key="nonexistent",
        name="Nonexistent Dataset",
        source_type="kaggle",
        path_or_ref="owner/nonexistent",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
    )

    connector = DatasetConnector(
        catalogue={"nonexistent": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "Kaggle dataset not found: owner/nonexistent" in attempt.reason


def test_kaggle_metadata_date_and_license_captured(monkeypatch, tmp_path, sample_csv):
    """Metadata last_updated date and license from Kaggle are captured into payload and attempt reason."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey123")

    def fake_download(dataset, file_name, path):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "reviews.csv").write_text(sample_csv, encoding="utf-8")

    target_dt = datetime(2025, 4, 1, 8, 30, tzinfo=timezone.utc)
    mock_datasets = [
        MockDataset(
            ref="owner/licensed-ds",
            last_updated=target_dt,
            license_name="MIT",
        )
    ]
    mock_api = MockKaggleApi(download_action=fake_download, datasets=mock_datasets)

    entry = DatasetEntry(
        key="licensed_ds",
        name="Licensed DS",
        source_type="kaggle",
        path_or_ref="owner/licensed-ds",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
    )

    connector = DatasetConnector(
        catalogue={"licensed_ds": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert mentions[0].raw_payload["dataset_license"] == "MIT"
    assert mentions[0].raw_payload["dataset_last_updated"] == target_dt.isoformat()
    assert "License: MIT" in attempt.reason


def test_kaggle_reuse_downloaded_copy(monkeypatch, tmp_path, sample_csv):
    """Downloaded dataset is reused on subsequent calls without re-downloading."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey123")

    def fake_download(dataset, file_name, path):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "cached.csv").write_text(sample_csv, encoding="utf-8")

    mock_api = MockKaggleApi(download_action=fake_download)

    entry = DatasetEntry(
        key="cached_kaggle",
        name="Cached Kaggle",
        source_type="kaggle",
        path_or_ref="owner/cached-dataset",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
    )

    connector = DatasetConnector(
        catalogue={"cached_kaggle": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )
    request = CollectionRequest(company="Zomato")

    # First call downloads
    mentions1, attempt1 = connector.collect(request)
    assert len(mentions1) == 1
    assert "downloaded from Kaggle" in attempt1.reason
    assert len(mock_api.download_files_calls) == 1

    # Second call reuses downloaded copy
    mentions2, attempt2 = connector.collect(request)
    assert len(mentions2) == 1
    assert "reused local copy" in attempt2.reason
    assert len(mock_api.download_files_calls) == 1  # No second download


def test_kaggle_refresh_forces_download(monkeypatch, tmp_path, sample_csv):
    """When refresh=True, Kaggle dataset is downloaded again."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey123")

    def fake_download(dataset, file_name, path):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "data.csv").write_text(sample_csv, encoding="utf-8")

    mock_api = MockKaggleApi(download_action=fake_download)

    entry = DatasetEntry(
        key="refresh_kaggle",
        name="Refresh Kaggle",
        source_type="kaggle",
        path_or_ref="owner/refresh-dataset",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
    )

    connector = DatasetConnector(
        catalogue={"refresh_kaggle": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )

    # First call
    connector.collect(CollectionRequest(company="Zomato"))
    assert len(mock_api.download_files_calls) == 1

    # Second call with refresh=True
    _, attempt2 = connector.collect(CollectionRequest(company="Zomato", refresh=True))
    assert "downloaded from Kaggle" in attempt2.reason
    assert len(mock_api.download_files_calls) == 2


def test_kaggle_file_selection_multi_file_dataset(monkeypatch, tmp_path):
    """Specific file is selected when dataset contains multiple files."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey123")

    def fake_download(dataset, file_name, path):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        # Create multiple CSV files in destination
        (p / "users.csv").write_text(
            "id,brand,text\nu1,Zomato,User file record\n", encoding="utf-8"
        )
        (p / "reviews.csv").write_text(
            "id,brand,text\nr1,Zomato,Review file record\n", encoding="utf-8"
        )

    mock_api = MockKaggleApi(download_action=fake_download)

    # Specify "reviews.csv" in ref
    entry = DatasetEntry(
        key="multi_file",
        name="Multi File DS",
        source_type="kaggle",
        path_or_ref="owner/multi-file/reviews.csv",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
    )

    connector = DatasetConnector(
        catalogue={"multi_file": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert mentions[0].item_id == "r1"
    assert "Review file record" in mentions[0].raw_payload["text"]


@pytest.mark.parametrize(
    "error_text,expected_reason_substr",
    [
        ("401 Unauthorized", "Kaggle authentication failed or access forbidden (401/403)"),
        ("403 Forbidden", "Kaggle authentication failed or access forbidden (401/403)"),
        ("Please accept the competition or dataset terms of use", "Kaggle terms of use not accepted"),
        ("429 Too Many Requests: Rate limit", "Kaggle rate limit exceeded (429)"),
        ("HTTPSConnectionPool: Read timed out", "Kaggle request timed out"),
    ],
)
def test_kaggle_errors_handled_gracefully(
    monkeypatch, tmp_path, error_text, expected_reason_substr
):
    """Kaggle errors (401/403, terms, 429, timeouts) produce clear failure attempt reasons."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey123")

    def raise_error(dataset, file_name, path):
        raise Exception(error_text)

    mock_api = MockKaggleApi(download_action=raise_error)

    entry = DatasetEntry(
        key="err_ds",
        name="Error DS",
        source_type="kaggle",
        path_or_ref="owner/err-ds",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
    )

    connector = DatasetConnector(
        catalogue={"err_ds": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert expected_reason_substr in attempt.reason


def test_kaggle_credentials_never_leaked(monkeypatch, tmp_path):
    """Kaggle secret keys never appear in attempt reasons."""
    secret_key = "KGAT_af9e72230d588a28d40f7b44d7d8ef7b"
    username = "kaggshalini"
    monkeypatch.setenv("KAGGLE_USERNAME", username)
    monkeypatch.setenv("KAGGLE_KEY", secret_key)

    def raise_leaky_error(dataset, file_name, path):
        raise Exception(f"Failed with key {secret_key} for user {username}")

    mock_api = MockKaggleApi(download_action=raise_leaky_error)

    entry = DatasetEntry(
        key="leak_test",
        name="Leak Test",
        source_type="kaggle",
        path_or_ref="owner/leak-test",
        format="csv",
        platform="other",
        content_type="post",
        enabled=True,
    )

    connector = DatasetConnector(
        catalogue={"leak_test": entry},
        download_dir=tmp_path / "downloads",
        kaggle_api=mock_api,
    )
    request = CollectionRequest(company="Zomato")

    _, attempt = connector.collect(request)

    assert secret_key not in attempt.reason
    assert "[REDACTED]" in attempt.reason


def test_kaggle_download_size_limit_exceeded(monkeypatch, tmp_path):
    """When downloaded file exceeds max_download_mb, attempt fails and files are cleaned up."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey")

    def download_large_file(dataset, file_name, path):
        target = Path(path) / "large.zip"
        target.write_bytes(b"0" * (2 * 1024 * 1024))  # 2MB

    mock_api = MockKaggleApi(download_action=download_large_file)
    dl_dir = tmp_path / "downloads"
    source = KaggleSource(
        name="Large Kaggle",
        key="large_kaggle",
        ref="owner/large-dataset",
        file_format="csv",
        download_dir=dl_dir,
        api=mock_api,
    )
    source.max_download_mb = 1.0  # Limit 1MB

    with pytest.raises(ValueError) as exc_info:
        source.download_if_needed()
    assert "exceeded maximum limit" in str(exc_info.value)
    # Ensure partial download deleted
    assert not (dl_dir / "large_kaggle" / "large.zip").exists()


def test_kaggle_unpacked_size_limit_exceeded(monkeypatch, tmp_path):
    """When unpacked archive exceeds max_unpacked_mb, attempt fails and files are cleaned up."""
    monkeypatch.setenv("KAGGLE_USERNAME", "testuser")
    monkeypatch.setenv("KAGGLE_KEY", "testkey")

    def download_huge_zip(dataset, file_name, path):
        import zipfile
        target = Path(path) / "huge.zip"
        with zipfile.ZipFile(target, "w") as zf:
            zf.writestr("huge.csv", "a" * (2 * 1024 * 1024))  # 2MB uncompressed

    mock_api = MockKaggleApi(download_action=download_huge_zip)
    dl_dir = tmp_path / "downloads"
    source = KaggleSource(
        name="Huge Kaggle",
        key="huge_kaggle",
        ref="owner/huge-dataset",
        file_format="csv",
        download_dir=dl_dir,
        api=mock_api,
    )
    source.max_download_mb = 10.0
    source.max_unpacked_mb = 1.0  # Limit 1MB uncompressed

    with pytest.raises(ValueError) as exc_info:
        source.download_if_needed()
    assert "Unpacked dataset size exceeded maximum limit" in str(exc_info.value)
    assert not (dl_dir / "huge_kaggle" / "huge.csv").exists()


