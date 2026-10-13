import json
from pathlib import Path

import httpx
import pytest

FIX = Path(__file__).parent / "fixtures"


def endpoint_fixture_name(model_id: str) -> str:
    return model_id.replace("/", "__").replace(":", "--") + ".json"


@pytest.fixture
def raw_models() -> list[dict]:
    return json.loads((FIX / "or_models.json").read_text())["data"]


@pytest.fixture
def or_transport():
    """Replays recorded OpenRouter responses; unknown endpoints -> 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/models":
            return httpx.Response(200, content=(FIX / "or_models.json").read_bytes())
        if path.endswith("/endpoints"):
            model_id = path.removeprefix("/api/v1/models/").removesuffix("/endpoints")
            f = FIX / "endpoints" / endpoint_fixture_name(model_id)
            if f.exists():
                return httpx.Response(200, content=f.read_bytes())
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)
