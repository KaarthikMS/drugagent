"""
Shared async HTTP foundation for upstream API clients.

One pooled client is reused for the process lifetime. Creating a client
per request throws away connection pooling and TLS session reuse, which
on an API like openFDA costs more than the request itself.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import (
    HTTP_CONNECT_TIMEOUT,
    HTTP_MAX_CONNECTIONS,
    HTTP_MAX_KEEPALIVE,
    HTTP_READ_TIMEOUT,
    RETRY_BACKOFF_MAX,
    RETRY_BACKOFF_MIN,
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_MAX_ATTEMPTS,
    USER_AGENT,
)

# --------------------------------------------------------------------
# Errors
#
# Typed so callers can distinguish "the drug does not exist" from "the
# upstream is broken". Those need different answers: the first is a
# real result, the second must never be presented as one.
# --------------------------------------------------------------------


class UpstreamError(Exception):
    """Base class for all upstream failures."""

    def __init__(self, message: str, *, source: str) -> None:
        super().__init__(message)
        self.source = source


class UpstreamUnavailable(UpstreamError):
    """Upstream is unreachable, timed out, or returned a server error.

    Retries have already been exhausted. The caller must degrade to
    "I cannot answer" -- never to an ungrounded answer.
    """


class UpstreamBadRequest(UpstreamError):
    """We sent a malformed request. A bug on our side; retrying cannot help."""


# Statuses worth retrying. Deliberately excludes 500: openFDA returns it
# for malformed queries, so retrying burns the full backoff on a request
# that can never succeed. 404 is absent because it is not a failure --
# see `get_json`.
RETRYABLE_STATUS: frozenset[int] = frozenset({429, 502, 503, 504})


class _RetryableStatus(Exception):
    """Internal signal that turns a retryable HTTP status into a retryable exception."""


# --------------------------------------------------------------------
# Client
# --------------------------------------------------------------------


class HttpClient:
    """A pooled async HTTP client for one upstream source."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=HTTP_CONNECT_TIMEOUT,
                read=HTTP_READ_TIMEOUT,
                write=HTTP_READ_TIMEOUT,
                pool=HTTP_READ_TIMEOUT,
            ),
            limits=httpx.Limits(
                max_connections=HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=HTTP_MAX_KEEPALIVE,
            ),
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.TimeoutException, _RetryableStatus)
        ),
        stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(
            multiplier=RETRY_BACKOFF_MULTIPLIER,
            min=RETRY_BACKOFF_MIN,
            max=RETRY_BACKOFF_MAX,
        ),
        reraise=True,
    )
    async def _request(
        self, url: str, params: dict | None, headers: dict | None
    ) -> httpx.Response:
        response = await self._client.get(url, params=params, headers=headers)
        if response.status_code in RETRYABLE_STATUS:
            raise _RetryableStatus(str(response.status_code))
        return response

    async def _fetch(
        self, url: str, params: dict | None, headers: dict | None = None
    ) -> httpx.Response | None:
        """Perform the request and normalise every failure mode.

        Returns None when the upstream reports "no matches" (HTTP 404).
        That is an ordinary result, not an error: the drug does not
        exist, which is something we must be able to say plainly.

        Raises UpstreamBadRequest for our own malformed requests and
        UpstreamUnavailable once retries are exhausted.
        """
        try:
            response = await self._request(url, params, headers)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise UpstreamUnavailable(
                f"{self.source} unreachable: {type(exc).__name__}",
                source=self.source,
            ) from exc
        except _RetryableStatus as exc:
            raise UpstreamUnavailable(
                f"{self.source} returned HTTP {exc} after retries",
                source=self.source,
            ) from exc

        if response.status_code == 404:
            return None

        if response.status_code == 400:
            raise UpstreamBadRequest(
                f"{self.source} rejected the request", source=self.source
            )

        if response.status_code >= 500:
            # Not retried: openFDA uses 500 for malformed queries, so a
            # retry would spend the full backoff on a permanent failure.
            raise UpstreamUnavailable(
                f"{self.source} returned HTTP {response.status_code}",
                source=self.source,
            )

        if response.status_code >= 400:
            raise UpstreamBadRequest(
                f"{self.source} returned HTTP {response.status_code}",
                source=self.source,
            )

        return response

    async def get_json(
        self, url: str, params: dict | None = None
    ) -> dict | list | None:
        """GET and decode a JSON body. None means "no matches".

        The return type is deliberately `dict | list`: NLM's Clinical
        Tables services answer with a top-level JSON ARRAY, not an
        object. Typing this as `dict` would be a lie the type checker
        believes and the runtime does not.
        """
        response = await self._fetch(url, params)
        if response is None:
            return None

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamUnavailable(
                f"{self.source} returned non-JSON content", source=self.source
            ) from exc

    async def get_xml(self, url: str, params: dict | None = None) -> ET.Element | None:
        """GET and parse an XML body. None means "no matches".

        MedlinePlus health-topic search answers XML only -- there is no
        JSON representation to ask for. Rather than bolt a converter
        onto get_json, the transport is shared and only the decoding
        differs, so retry, timeout and error semantics stay identical
        across every upstream.

        Returns the parsed root element. Callers own the traversal,
        because an XML shape flattened into dicts loses exactly the
        attributes MedlinePlus puts its content in.
        """
        response = await self._fetch(url, params, headers={"Accept": "application/xml"})
        if response is None:
            return None

        try:
            return ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise UpstreamUnavailable(
                f"{self.source} returned malformed XML", source=self.source
            ) from exc
