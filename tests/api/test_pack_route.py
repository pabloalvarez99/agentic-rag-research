"""HTTP experiment pack route uses payloads, not server ids."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_rag.main import create_app


def test_pack_route_builds_hash_from_payloads() -> None:
    client = TestClient(create_app())
    done = client.post(
        "/v1/research",
        json={"question": "How does reciprocal rank fusion score a document?", "retriever": "fake"},
    )
    refused = client.post(
        "/v1/research",
        json={
            "question": "Who won the 2099 Antarctic chess championship?",
            "retriever": "fake",
        },
    )
    assert done.status_code == 200
    assert refused.status_code == 200
    left_id = done.json()["request_id"]
    right_id = refused.json()["request_id"]
    left = client.get(f"/v1/runs/{left_id}/run.json").json()
    right = client.get(f"/v1/runs/{right_id}/run.json").json()
    pack = client.post(
        "/v1/experiments/pack",
        json={
            "policy": {
                "retriever": "fake",
                "max_steps": 4,
                "max_calls": {"retrieve": 4},
                "season_tag": "v1.0",
                "billed": False,
            },
            "left": left,
            "right": right,
            "experiments": [],
        },
    )
    assert pack.status_code == 200, pack.text
    body = pack.json()
    assert body["manifest"]["pack_hash"]
    assert body["compare"]["identical"] is False
    assert "status" in {d["field"] for d in body["compare"]["diffs"]}
