"""Frontend dist path resolution for Docker vs local dev layouts."""

from pathlib import Path

from app.main import resolve_frontend_dist


def test_resolve_frontend_dist_local_repo_layout(tmp_path):
    repo = tmp_path / "workspace"
    dist = repo / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    main_py = repo / "backend" / "app" / "main.py"
    main_py.parent.mkdir(parents=True)

    resolved = resolve_frontend_dist(main_py)
    assert resolved == dist


def test_resolve_frontend_dist_docker_layout(tmp_path):
    app_root = tmp_path / "app"
    dist = app_root / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    main_py = app_root / "app" / "main.py"
    main_py.parent.mkdir(parents=True)

    resolved = resolve_frontend_dist(main_py)
    assert resolved == dist
