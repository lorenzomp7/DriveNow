"""A Mobilithek subscription, read by client pull: DATEX II from the German access point.

Mobilithek (mobilithek.info) is Germany's national access point for mobility data. A
data user subscribes to an offer (the provider may have to approve) and gets a
subscription id and a machine certificate issued by Mobilithek. The data is then
pulled with HTTPS and that certificate (mutual TLS), as the Mobilithek technical
specification (section 7.1.2.2.1, DATEX II v2 client pull) describes:

    GET https://mobilithek.info:8443/mobilithek/api/v1.0/subscription/<id>/clientPullService?subscriptionID=<id>
    Accept-Encoding: gzip          (always gzip; 400 without it)
    If-Modified-Since: <the last package's time>

    200 the package (DATEX II, gzip) | 204 no package yet | 304 nothing newer
    403 this certificate may not read this subscription

For DriveNow the offer that matters is LSBG's "Traffic Disturbance Roadworks"
(110000000003540000): every roadworks site on Hamburg's streets in DATEX II v2, hourly,
under an open licence, provider approval required. The certificate comes as a .p12
file; Python's ssl reads PEM, so convert it first:

    openssl pkcs12 -in machine.p12 -out machine.pem -nodes

Standard library only. ``fetch`` can be given (tests, other transports): it takes the
URL and the headers and returns (status, headers, body).
"""

from __future__ import annotations

import gzip
import ssl
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from ..road_events import RoadEvent
from . import datex2

URL = "https://mobilithek.info:8443/mobilithek/api/v1.0/subscription/{id}/clientPullService?subscriptionID={id}"
LSBG_ROADWORKS_OFFER = "110000000003540000"

Fetch = Callable[[str, Dict[str, str]], Tuple[int, Dict[str, str], bytes]]


class MobilithekPull:
    def __init__(self, subscription_id: str, cert_file: Optional[str] = None, key_file: Optional[str] = None,
                 fetch: Optional[Fetch] = None, source: str = "lsbg", timeout: float = 60.0) -> None:
        subscription_id = str(subscription_id).strip()
        if not subscription_id.isdigit():
            raise ValueError("a Mobilithek subscription id is a number")
        if fetch is None and not cert_file:
            raise ValueError("Mobilithek needs the machine certificate it issued for the subscription "
                             "(PEM; convert the .p12 with: openssl pkcs12 -in machine.p12 -out machine.pem -nodes)")
        self.subscription_id = subscription_id
        self.source = source
        self.timeout = timeout
        self.last_modified: Optional[str] = None
        self._fetch = fetch
        self._context = None
        if fetch is None:
            self._context = ssl.create_default_context()
            self._context.load_cert_chain(cert_file, key_file)

    def url(self) -> str:
        return URL.format(id=self.subscription_id)

    def _https(self, url: str, headers: Dict[str, str]) -> Tuple[int, Dict[str, str], bytes]:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self._context))
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:   # 304, 403 and the like come as errors from urllib
            return e.code, dict(e.headers or {}), b""

    def pull(self) -> Tuple[List[RoadEvent], Dict[str, int]]:
        """The situations of the newest package, or ([], {"status": 204|304}) when there is none."""
        headers = {"Accept-Encoding": "gzip"}
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        status, got, body = (self._fetch or self._https)(self.url(), headers)
        if status in (204, 304):
            return [], {"status": status}
        if status == 403:
            raise PermissionError("Mobilithek refused this subscription for this certificate (403): is the "
                                  "subscription approved, and is it a DATEX II v2 one?")
        if status != 200:
            raise RuntimeError(f"Mobilithek answered {status}")
        self.last_modified = {k.lower(): v for k, v in got.items()}.get("last-modified", self.last_modified)
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        events, stats = datex2.parse_situations(body, self.source)
        return events, {"status": 200, **stats}
