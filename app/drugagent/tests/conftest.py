"""
Shared test fixtures.

Two kinds of test live in this suite, and the split is deliberate:

    unit   mocked transport. No network. Runs anywhere, costs nothing,
           and proves our PARSING is right.
    smoke  real HTTP against public APIs. Proves the API still behaves
           the way probes/FINDINGS.md recorded.

Unit tests cannot catch an upstream changing its response shape, and
smoke tests cannot run in an offline CI. Neither replaces the other.
Smoke tests are marked so they can be deselected:

    pytest -m "not smoke"
"""

from __future__ import annotations

import httpx
import pytest

from utils.base import HttpClient


@pytest.fixture
def mock_http():
    """Build an HttpClient whose transport answers from a routing table.

    The real client is used -- retry policy, status handling, JSON and
    XML decoding all execute. Only the socket is replaced. A test double
    that reimplemented get_json would prove the double correct and say
    nothing about the code that ships.
    """

    def build(routes: dict[str, httpx.Response], source: str = "test") -> HttpClient:
        def handler(request: httpx.Request) -> httpx.Response:
            for fragment, response in routes.items():
                if fragment in str(request.url):
                    return response
            return httpx.Response(404, json={"error": "no route"})

        client = HttpClient(source=source)
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"Accept": "application/json"},
        )
        return client

    return build


def json_response(payload) -> httpx.Response:
    return httpx.Response(200, json=payload)


def xml_response(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "application/xml"})


def not_found() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
