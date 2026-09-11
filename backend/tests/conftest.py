"""Fixtures shared across the API test modules."""

import pytest
from fastapi.testclient import TestClient
from support import marked_image

from app.cleaning import png_bytes
from app.main import create_app


@pytest.fixture
def cleanup_client(tmp_path):
    root = tmp_path / "Dada"
    folder = root / "pair_a"
    folder.mkdir(parents=True)
    (folder / "image_REF.png").write_bytes(png_bytes(marked_image(box=True)))
    (folder / "image.png").write_bytes(png_bytes(marked_image(cross=True)))
    app = create_app(tmp_path / "state")
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "Cleaning test"}).json()["id"]
        assert client.post(f"/api/projects/{pid}/import", json={"root_directory": str(root)}).status_code == 200
        pair = client.get(f"/api/projects/{pid}/pairs").json()[0]
        pair = client.put(
            f"/api/pairs/{pair['id']}", json={"revision": pair["revision"], "gt_x": 70, "gt_y": 60}
        ).json()
        yield client, pid, pair, folder
    app.state.engine.dispose()
