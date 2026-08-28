from platform_core.bootstrap import choose_project


def test_empty_preferred_project_does_not_hide_populated_project():
    projects = [
        {"id": "empty", "updated_at": "2026-08-28"},
        {"id": "real", "updated_at": "2026-08-27"},
    ]
    counts = {
        "empty": {"images": 0, "algorithms": 0, "versions": 0, "jobs": 0},
        "real": {"images": 100, "algorithms": 2, "versions": 3, "jobs": 4},
    }
    assert choose_project(projects, "empty", counts)["id"] == "real"

