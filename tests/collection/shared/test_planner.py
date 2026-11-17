"""Tests for collection planner (src/collection/planner.py)."""
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
import yaml

from src.collection.planner import InvalidCompany, Plan, Planner, Task, main, plan
from src.contracts.enums import Platform


def test_shape_a_single_company():
    """Shape (a): single company dict."""
    data = {
        "company": "TestCorp",
        "alt_spellings": ["Test Corp", "TC"],
        "handles": ["@testcorp"],
        "branches": ["New York"],
        "industry": "technology",
        "platforms": ["reddit"],
        "budget_usd": 150.0,
    }
    result = plan(data)
    assert len(result.requests) == 1
    req = result.requests[0]
    assert req.company == "TestCorp"
    assert req.alt_spellings == ["Test Corp", "TC"]
    assert req.handles == ["@testcorp"]
    assert req.branches == ["New York"]
    assert req.industry == "technology"
    assert req.platforms == [Platform.reddit]
    assert req.budget_usd == 150.0
    assert len(result.invalid) == 0
    assert Task("TestCorp", Platform.reddit) in result.tasks


def test_shape_b_plain_list():
    """Shape (b): plain list under 'companies' or as raw list."""
    # Dict with 'companies' key
    data = {
        "companies": [
            "Acme",
            {"company": "BetaCorp", "industry": "retail"},
        ]
    }
    res1 = plan(data)
    assert len(res1.requests) == 2
    names1 = {r.company for r in res1.requests}
    assert names1 == {"Acme", "BetaCorp"}
    beta = next(r for r in res1.requests if r.company == "BetaCorp")
    assert beta.industry == "retail"

    # Raw list directly
    res2 = plan(["GammaCorp", "DeltaCorp"])
    assert len(res2.requests) == 2
    names2 = {r.company for r in res2.requests}
    assert names2 == {"GammaCorp", "DeltaCorp"}


def test_shape_c_industry_grouped():
    """Shape (c): industry-grouped list."""
    data = {
        "industries": {
            "Food delivery": ["BrandA", "BrandB"],
            "Automotive": [{"name": "BrandC", "alt_spellings": ["BC"]}],
        }
    }
    result = plan(data)
    assert len(result.requests) == 3
    by_name = {r.company: r for r in result.requests}
    assert "BrandA" in by_name
    assert "BrandB" in by_name
    assert "BrandC" in by_name


def test_industry_becomes_company_industry():
    """In industry-grouped inputs, group name becomes the company's industry."""
    data = {
        "industries": {
            "Food delivery": ["ZomatoExpress", "SwiggyQuick"],
            "Automotive": [{"name": "Tata Motors", "alt_spellings": ["Tata"]}],
        }
    }
    result = plan(data)
    by_name = {r.company: r for r in result.requests}
    assert by_name["ZomatoExpress"].industry == "Food delivery"
    assert by_name["SwiggyQuick"].industry == "Food delivery"
    assert by_name["Tata Motors"].industry == "Automotive"


def test_top_level_defaults_and_company_overrides():
    """Top-level shared fields apply to all companies unless explicitly overridden."""
    data = {
        "budget_usd": 100.0,
        "date_from": "2026-01-01",
        "date_to": "2026-06-01",
        "platforms": ["reddit"],
        "scraping_allowed": True,
        "require_fresh": True,
        "companies": [
            {"company": "DefaultCo"},
            {
                "company": "CustomCo",
                "budget_usd": 25.0,
                "platforms": ["google"],
                "scraping_allowed": False,
            },
        ],
    }
    result = plan(data)
    assert len(result.requests) == 2
    by_name = {r.company: r for r in result.requests}

    default_req = by_name["DefaultCo"]
    assert default_req.budget_usd == 100.0
    assert default_req.platforms == [Platform.reddit]
    assert default_req.scraping_allowed is True
    assert default_req.require_fresh is True
    assert default_req.date_from == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert default_req.date_to == datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)

    custom_req = by_name["CustomCo"]
    assert custom_req.budget_usd == 25.0
    assert custom_req.platforms == [Platform.google]
    assert custom_req.scraping_allowed is False
    assert custom_req.require_fresh is True  # inherited from top-level
    assert custom_req.date_from == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_companies_yaml_fills_gaps_never_overrides(tmp_path):
    """companies.yaml fills in missing alt_spellings, handles, branches, and industry; input always wins."""
    yaml_file = tmp_path / "companies.yaml"
    yaml_content = {
        "companies": {
            "AcmeCorp": {
                "alt_spellings": ["Acme Ltd", "Acme International"],
                "handles": ["@acme", "@acmesupport"],
                "branches": ["London", "Berlin"],
                "industry": "manufacturing",
            }
        }
    }
    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.dump(yaml_content, f)

    planner = Planner(companies_path=yaml_file)

    # Case 1: Company has gaps -> companies.yaml fills them
    p1 = planner.plan({"company": "acmecorp"})
    assert len(p1.requests) == 1
    req1 = p1.requests[0]
    assert req1.alt_spellings == ["Acme Ltd", "Acme International"]
    assert req1.handles == ["@acme", "@acmesupport"]
    assert req1.branches == ["London", "Berlin"]
    assert req1.industry == "manufacturing"

    # Case 2: Company specifies its own values -> input wins, never overridden
    p2 = planner.plan({
        "company": "AcmeCorp",
        "alt_spellings": ["My Custom Acme"],
        "handles": ["@customhandle"],
        "branches": ["Tokyo"],
        "industry": "aerospace",
    })
    assert len(p2.requests) == 1
    req2 = p2.requests[0]
    assert req2.alt_spellings == ["My Custom Acme"]
    assert req2.handles == ["@customhandle"]
    assert req2.branches == ["Tokyo"]
    assert req2.industry == "aerospace"


def test_one_invalid_company_does_not_stop_the_rest():
    """An invalid company is recorded in .invalid with its reasons; valid ones succeed."""
    data = {
        "companies": [
            {"company": "ValidFirst"},
            {"company": ""},  # invalid: blank name
            {"company": "ValidSecond"},
        ]
    }
    result = plan(data)
    assert len(result.requests) == 2
    assert {r.company for r in result.requests} == {"ValidFirst", "ValidSecond"}

    assert len(result.invalid) == 1
    inv = result.invalid[0]
    assert inv.name == ""
    assert any("blank" in r.lower() or "missing" in r.lower() for r in inv.reasons)
    # Check dict-like access
    assert inv["name"] == ""
    assert len(inv["reasons"]) > 0


def test_duplicates_merged_and_noted():
    """Duplicate company names (case-insensitive) are merged into one request and noted."""
    data = {
        "companies": [
            {
                "company": "BetaBrand",
                "alt_spellings": ["Beta 1"],
                "handles": ["@beta1"],
                "platforms": ["reddit"],
            },
            {
                "company": "betabrand",
                "alt_spellings": ["Beta 2"],
                "handles": ["@beta2"],
                "platforms": ["google"],
            },
        ]
    }
    result = plan(data)
    assert len(result.requests) == 1
    req = result.requests[0]
    assert req.company.lower() == "betabrand"
    assert set(req.alt_spellings) == {"Beta 1", "Beta 2"}
    assert set(req.handles) == {"@beta1", "@beta2"}
    assert set(req.platforms) == {Platform.reddit, Platform.google}

    assert len(result.notes) == 1
    assert "duplicate" in result.notes[0].lower()


def test_unknown_platform_rejected():
    """Unknown platform values are collected as validation errors."""
    data = {
        "companies": [
            {"company": "CoWithBadPlat", "platforms": ["myspace_xyz"]},
            {"company": "ValidCo", "platforms": ["reddit"]},
        ]
    }
    result = plan(data)
    assert len(result.requests) == 1
    assert result.requests[0].company == "ValidCo"

    assert len(result.invalid) == 1
    assert result.invalid[0].name == "CoWithBadPlat"
    assert any("unknown platform" in r.lower() for r in result.invalid[0].reasons)


def test_unknown_dataset_key_rejected():
    """Unknown dataset keys are rejected with clear reasons."""
    data = {
        "company": "CoWithBadDataset",
        "dataset_keys": ["non_existent_catalogue_key_12345"],
    }
    result = plan(data)
    assert len(result.requests) == 0
    assert len(result.invalid) == 1
    assert result.invalid[0].name == "CoWithBadDataset"
    assert any("unknown dataset key" in r.lower() for r in result.invalid[0].reasons)


def test_date_order_check():
    """date_from after date_to is flagged as invalid."""
    data = {
        "company": "TimeTravelCo",
        "date_from": "2026-12-01",
        "date_to": "2026-01-01",
    }
    result = plan(data)
    assert len(result.requests) == 0
    assert len(result.invalid) == 1
    assert result.invalid[0].name == "TimeTravelCo"
    assert any("date_from must not be after date_to" in r.lower() for r in result.invalid[0].reasons)


def test_negative_budget_rejected():
    """Negative budget is rejected as invalid."""
    data = {
        "company": "CheapCo",
        "budget_usd": -10.0,
    }
    result = plan(data)
    assert len(result.requests) == 0
    assert len(result.invalid) == 1
    assert any("negative" in r.lower() for r in result.invalid[0].reasons)


def test_file_input_json_and_yaml(tmp_path):
    """Planner reads directly from .json and .yaml file paths."""
    # JSON file
    json_path = tmp_path / "plan_input.json"
    json_data = {"companies": ["JsonCo1", "JsonCo2"]}
    json_path.write_text(json.dumps(json_data), encoding="utf-8")

    plan_json = plan(json_path)
    assert len(plan_json.requests) == 2
    assert {r.company for r in plan_json.requests} == {"JsonCo1", "JsonCo2"}

    # YAML file
    yaml_path = tmp_path / "plan_input.yaml"
    yaml_data = {"companies": ["YamlCo1", "YamlCo2"]}
    yaml_path.write_text(yaml.dump(yaml_data), encoding="utf-8")

    plan_yaml = plan(yaml_path)
    assert len(plan_yaml.requests) == 2
    assert {r.company for r in plan_yaml.requests} == {"YamlCo1", "YamlCo2"}


def test_task_generation_platforms_and_datasets():
    """Generates Task(company, platform) per platform plus Task(company, 'dataset') per dataset key."""
    data = {
        "company": "MultiTaskCo",
        "platforms": ["reddit", "google"],
        "dataset_keys": ["sample_reviews_local"],
    }
    result = plan(data)
    assert len(result.requests) == 1
    tasks = result.tasks
    assert len(tasks) == 3

    # Check Task objects
    assert Task("MultiTaskCo", Platform.reddit) in tasks
    assert Task("MultiTaskCo", Platform.google) in tasks
    assert Task("MultiTaskCo", "dataset") in tasks


def test_cli_execution_success_and_failure(tmp_path, capsys):
    """CLI prints readable plan and exits with 0 on success, non-zero if no valid companies."""
    # Valid file -> exit code 0
    valid_file = tmp_path / "valid.json"
    valid_file.write_text(json.dumps({"company": "GoodCo"}), encoding="utf-8")

    code_success = main(["--input", str(valid_file)])
    assert code_success == 0
    out, _ = capsys.readouterr()
    assert "GoodCo" in out
    assert "Valid Requests: 1" in out

    # Invalid file -> exit code 1
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text(json.dumps({"company": "", "budget_usd": -1}), encoding="utf-8")

    code_fail = main(["--input", str(invalid_file)])
    assert code_fail == 1
    out_fail, _ = capsys.readouterr()
    assert "Invalid Companies: 1" in out_fail


def test_json_and_yaml_file_input_with_bom(tmp_path):
    """JSON and YAML input files starting with a leading UTF-8 BOM must both load successfully."""
    bom = b"\xef\xbb\xbf"

    # JSON with leading BOM bytes
    json_path = tmp_path / "bom_input.json"
    json_content = json.dumps({"company": "BomJsonCo"}).encode("utf-8")
    json_path.write_bytes(bom + json_content)

    plan_json = plan(json_path)
    assert len(plan_json.requests) == 1
    assert plan_json.requests[0].company == "BomJsonCo"

    # YAML with leading BOM bytes
    yaml_path = tmp_path / "bom_input.yaml"
    yaml_content = yaml.dump({"companies": ["BomYamlCo"]}).encode("utf-8")
    yaml_path.write_bytes(bom + yaml_content)

    plan_yaml = plan(yaml_path)
    assert len(plan_yaml.requests) == 1
    assert plan_yaml.requests[0].company == "BomYamlCo"


def test_request_with_dataset_key_creates_exactly_one_dataset_task_per_company():
    """A request with a dataset key creates exactly one dataset task per company."""
    data = {
        "companies": ["Company1", "Company2"],
        "dataset_keys": ["sample_reviews_local", "sample_reviews_local"],  # duplicate key in input
    }
    result = plan(data)
    assert len(result.requests) == 2

    for comp in ["Company1", "Company2"]:
        dataset_tasks = [t for t in result.tasks if t.company == comp and t.platform == "dataset"]
        assert len(dataset_tasks) == 1
        assert dataset_tasks[0].company == comp
        assert dataset_tasks[0].platform == "dataset"


def test_default_platforms_never_include_other():
    """Default platform list must contain only real platforms and never include 'other'."""
    data = {"companies": ["CompanyNoPlatforms"]}
    result = plan(data)
    assert len(result.requests) == 1
    req = result.requests[0]

    # Verify platforms on CollectionRequest
    assert Platform.other not in req.platforms
    assert "other" not in [p.value for p in req.platforms]
    for p in req.platforms:
        assert p in {
            Platform.reddit,
            Platform.google,
            Platform.twitter_x,
            Platform.instagram,
            Platform.linkedin,
            Platform.facebook,
            Platform.news_blog,
        }

    # Verify task platforms
    for task in result.tasks:
        assert task.platform != Platform.other
        assert task.platform != "other"


# ---------------------------------------------------------------------------
# Platform defaulting tests (requirement: fix platform defaulting behaviour)
# ---------------------------------------------------------------------------

def test_platforms_empty_list_creates_no_platform_tasks():
    """platforms: [] must create no platform tasks (do not fall back to defaults)."""
    data = {
        "company": "TestCorp",
        "platforms": [],
    }
    result = plan(data)
    platform_tasks = [t for t in result.tasks if t.platform != "dataset"]
    assert platform_tasks == [], "explicit [] platforms must yield zero platform tasks"


def test_platforms_missing_no_dataset_defaults_to_all_real_platforms():
    """platforms key missing and no dataset_keys → defaults to all real platforms."""
    result = plan({"company": "TestCorp"})
    assert len(result.tasks) > 0, "should produce tasks when only company is given"
    for t in result.tasks:
        assert t.platform != "dataset"
        assert t.platform in {
            Platform.reddit,
            Platform.google,
            Platform.twitter_x,
            Platform.instagram,
            Platform.linkedin,
            Platform.facebook,
            Platform.news_blog,
        }


def test_platforms_missing_with_dataset_creates_only_dataset_tasks():
    """platforms key missing but dataset_keys given → only dataset tasks, no platform tasks."""
    result = plan({
        "company": "TestCorp",
        "dataset_keys": ["sample_reviews_local"],
    })
    platform_tasks = [t for t in result.tasks if t.platform != "dataset"]
    assert platform_tasks == [], "dataset_keys with no platforms key must yield no platform tasks"
    dataset_tasks = [t for t in result.tasks if t.platform == "dataset"]
    assert len(dataset_tasks) == 1, "should create exactly one dataset task"


def test_explicit_reddit_platform_creates_reddit_task():
    """platforms: ['reddit'] must create the reddit task."""
    result = plan({"company": "TestCorp", "platforms": ["reddit"]})
    assert any(t.platform == Platform.reddit for t in result.tasks), (
        "explicit reddit must create a reddit task"
    )


def test_dataset_only_per_company_creates_exactly_one_dataset_task():
    """A request with a dataset_key and a platforms [] creates exactly one dataset task per company."""
    result = plan({
        "companies": [
            {"company": "Alpha", "platforms": [], "dataset_keys": ["sample_reviews_local"]},
            {"company": "Beta",  "platforms": [], "dataset_keys": ["sample_reviews_local"]},
        ]
    })
    for company in ("Alpha", "Beta"):
        ds_tasks = [
            t for t in result.tasks
            if t.company == company and t.platform == "dataset"
        ]
        assert len(ds_tasks) == 1, (
            f"{company} should have exactly 1 dataset task, got {len(ds_tasks)}"
        )
        plat_tasks = [
            t for t in result.tasks
            if t.company == company and t.platform != "dataset"
        ]
        assert plat_tasks == [], f"{company} should have no platform tasks when platforms=[]"
