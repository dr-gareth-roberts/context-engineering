from fastapi.testclient import TestClient

from context_engineering.api import create_app


def test_pack_validation_errors_return_structured_400() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/pack",
        json={
            "items": [{"id": "", "content": "bad item"}],
            "budget": {"maxTokens": 100},
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["details"][0]["path"] == "items[0].id"
