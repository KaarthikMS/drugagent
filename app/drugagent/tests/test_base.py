"""
Transport behaviour: the rules every client inherits.

These are the tests that decide whether "the drug does not exist" can be
told apart from "the upstream is broken". Those need different answers --
the first is a real result, the second must never be presented as one.
"""

from __future__ import annotations

import httpx
import pytest

from clients.base import UpstreamBadRequest, UpstreamUnavailable
from tests.conftest import json_response, not_found, xml_response


@pytest.mark.asyncio
async def test_json_decoded(mock_http):
    client = mock_http({"/ok": json_response({"value": 1})})
    assert await client.get_json("https://x/ok") == {"value": 1}
    await client.aclose()


@pytest.mark.asyncio
async def test_404_is_a_result_not_an_error(mock_http):
    """404 means "no matches", which the system must be able to say."""
    client = mock_http({"/missing": not_found()})
    assert await client.get_json("https://x/missing") is None
    await client.aclose()


@pytest.mark.asyncio
async def test_top_level_array_survives(mock_http):
    """Clinical Tables answers with an array, not an object."""
    client = mock_http({"/arr": json_response([2, ["a", "b"], None, [["A"], ["B"]]])})
    result = await client.get_json("https://x/arr")
    assert isinstance(result, list) and result[0] == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_xml_parsed(mock_http):
    client = mock_http({"/xml": xml_response("<r><count>3</count></r>")})
    root = await client.get_xml("https://x/xml")
    assert root.findtext("count") == "3"
    await client.aclose()


@pytest.mark.asyncio
async def test_500_is_not_retried_into_success(mock_http):
    """openFDA answers 500 for malformed queries.

    Retrying spends the full backoff on a request that can never
    succeed, so 500 raises immediately rather than being retried.
    """
    client = mock_http({"/boom": httpx.Response(500, text="")})
    with pytest.raises(UpstreamUnavailable):
        await client.get_json("https://x/boom")
    await client.aclose()


@pytest.mark.asyncio
async def test_400_is_our_bug(mock_http):
    client = mock_http({"/bad": httpx.Response(400, text="")})
    with pytest.raises(UpstreamBadRequest):
        await client.get_json("https://x/bad")
    await client.aclose()


@pytest.mark.asyncio
async def test_non_json_body_is_an_upstream_failure(mock_http):
    """A 200 carrying HTML is an outage page, not an answer."""
    client = mock_http({"/html": httpx.Response(200, text="<html>down</html>")})
    with pytest.raises(UpstreamUnavailable):
        await client.get_json("https://x/html")
    await client.aclose()
