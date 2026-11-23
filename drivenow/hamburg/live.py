"""Hamburg's traffic light feed, live: MQTT over a websocket, standard library only.

The city's SensorThings server (tld.iot.hamburg.de) publishes every new
observation of its datastreams over MQTT: signal colours, cycle seconds and the
loop detectors at some lanes. The topic of a datastream is
``v1.1/Datastreams(<id>)/Observations``; each message is the observation as JSON.

``LiveFeed`` opens ``wss://<host>/mqtt`` (through the HTTPS proxy of the
environment if there is one), subscribes and yields the observations as they
arrive. Only what is needed of MQTT 3.1.1 is implemented: CONNECT, SUBSCRIBE,
PUBLISH at QoS 0, PINGREQ.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import os
import re
import socket
import ssl
import struct
import time
import urllib.parse
from typing import Iterator, List, Optional, Sequence, Tuple

HOST = "tld.iot.hamburg.de"

# -- MQTT packets ---------------------------------------------------------------


def _remaining(n: int) -> bytes:
    out = b""
    while True:
        d, n = n % 128, n // 128
        out += bytes([d | (0x80 if n else 0)])
        if not n:
            return out


def _str(s: str) -> bytes:
    b = s.encode()
    return struct.pack(">H", len(b)) + b


def connect_packet(client_id: str, keepalive: int = 60) -> bytes:
    var = _str("MQTT") + bytes([4, 0x02]) + struct.pack(">H", keepalive)  # 3.1.1, clean session
    body = var + _str(client_id)
    return bytes([0x10]) + _remaining(len(body)) + body


def subscribe_packet(packet_id: int, topics: Sequence[str]) -> bytes:
    body = struct.pack(">H", packet_id) + b"".join(_str(t) + b"\x00" for t in topics)
    return bytes([0x82]) + _remaining(len(body)) + body


PINGREQ = b"\xc0\x00"


class MqttParser:
    """Splits a byte stream into MQTT packets: (type, flags, body)."""

    def __init__(self) -> None:
        self.buf = b""

    def feed(self, data: bytes) -> List[Tuple[int, int, bytes]]:
        self.buf += data
        out = []
        while len(self.buf) >= 2:
            mult, n, i = 1, 0, 1
            while True:
                if i >= len(self.buf):
                    return out
                b = self.buf[i]
                n += (b & 127) * mult
                mult *= 128
                i += 1
                if not b & 128:
                    break
            if len(self.buf) < i + n:
                return out
            out.append((self.buf[0] >> 4, self.buf[0] & 15, self.buf[i:i + n]))
            self.buf = self.buf[i + n:]
        return out


def parse_publish(flags: int, body: bytes) -> Tuple[str, bytes]:
    n = struct.unpack(">H", body[:2])[0]
    topic = body[2:2 + n].decode()
    rest = body[2 + n:]
    if (flags >> 1) & 3:          # QoS 1 or 2: a packet id comes first
        rest = rest[2:]
    return topic, rest


# -- websocket frames -------------------------------------------------------------


def ws_frame(payload: bytes, mask: Optional[bytes] = None, opcode: int = 0x2) -> bytes:
    """A client frame (clients must mask)."""
    mask = mask or os.urandom(4)
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", n)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class WsParser:
    """Splits a byte stream from the server into (opcode, payload) frames."""

    def __init__(self) -> None:
        self.buf = b""

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        self.buf += data
        out = []
        while len(self.buf) >= 2:
            op, n, o = self.buf[0] & 15, self.buf[1] & 127, 2
            masked = self.buf[1] & 128
            if n == 126:
                if len(self.buf) < 4:
                    break
                n, o = struct.unpack(">H", self.buf[2:4])[0], 4
            elif n == 127:
                if len(self.buf) < 10:
                    break
                n, o = struct.unpack(">Q", self.buf[2:10])[0], 10
            mask = b""
            if masked:
                mask, o = self.buf[o:o + 4], o + 4
            if len(self.buf) < o + n:
                break
            p = self.buf[o:o + n]
            if masked:
                p = bytes(b ^ mask[i % 4] for i, b in enumerate(p))
            out.append((op, p))
            self.buf = self.buf[o + n:]
        return out


# -- observations ------------------------------------------------------------------

_DS = re.compile(r"Datastreams\((\d+)\)")


def _epoch(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.split("/")[0].replace("Z", "+00:00")
    return _dt.datetime.fromisoformat(s).timestamp()


def parse_observation(topic: str, payload: bytes) -> Optional[Tuple[int, float, float, Optional[float]]]:
    """(datastream id, phenomenon time, result, result time) as Unix times, or None."""
    m = _DS.search(topic)
    if not m:
        return None
    try:
        obs = json.loads(payload)
        return int(m.group(1)), _epoch(obs["phenomenonTime"]), float(obs["result"]), _epoch(obs.get("resultTime"))
    except (ValueError, KeyError, TypeError):
        return None


# -- the connection ------------------------------------------------------------------


class LiveFeed:
    def __init__(self, topics: Sequence[str], host: str = HOST, path: str = "/mqtt",
                 cafile: Optional[str] = None, timeout: float = 15.0) -> None:
        self.topics = list(topics)
        self.host = host
        self.path = path
        self.cafile = cafile or (os.environ.get("SSL_CERT_FILE") or None)
        self.timeout = timeout
        self.sock: Optional[ssl.SSLSocket] = None
        self._ws = WsParser()
        self._mqtt = MqttParser()

    def _open(self) -> socket.socket:
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not proxy:
            return socket.create_connection((self.host, 443), timeout=self.timeout)
        p = urllib.parse.urlparse(proxy)
        s = socket.create_connection((p.hostname, p.port or 80), timeout=self.timeout)
        req = f"CONNECT {self.host}:443 HTTP/1.1\r\nHost: {self.host}:443\r\n"
        if p.username:
            cred = f"{urllib.parse.unquote(p.username)}:{urllib.parse.unquote(p.password or '')}"
            req += "Proxy-Authorization: Basic " + base64.b64encode(cred.encode()).decode() + "\r\n"
        s.sendall((req + "\r\n").encode())
        head = self._read_head(s)
        if b" 200" not in head.split(b"\r\n")[0]:
            raise ConnectionError("proxy refused: " + head.split(b"\r\n")[0].decode(errors="replace"))
        return s

    @staticmethod
    def _read_head(s) -> bytes:
        head = b""
        while b"\r\n\r\n" not in head:
            c = s.recv(1)
            if not c:
                raise ConnectionError("connection closed")
            head += c
        return head

    def connect(self) -> None:
        ctx = ssl.create_default_context(cafile=self.cafile) if self.cafile else ssl.create_default_context()
        self.sock = ctx.wrap_socket(self._open(), server_hostname=self.host)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {self.path} HTTP/1.1\r\nHost: {self.host}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                           f"Sec-WebSocket-Protocol: mqtt\r\n\r\n").encode())
        head = self._read_head(self.sock)
        if b" 101" not in head.split(b"\r\n")[0]:
            raise ConnectionError("no websocket: " + head.split(b"\r\n")[0].decode(errors="replace"))
        # The broker closes the connection if anything comes before its CONNACK, or before
        # the SUBACK of the previous subscription.
        self._send(connect_packet("drivenow-" + os.urandom(4).hex()))
        self._expect(2)
        for i in range(0, len(self.topics), 50):
            self._send(subscribe_packet(i // 50 + 1, self.topics[i:i + 50]))
            self._expect(9)

    def _expect(self, kind: int) -> bytes:
        """Wait for the next packet of MQTT type ``kind`` (2 CONNACK, 9 SUBACK)."""
        end = time.time() + self.timeout
        while time.time() < end:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("connection closed by the server")
            for op, payload in self._ws.feed(data):
                if op == 0x8:
                    raise ConnectionError("websocket closed by the server")
                for k, _, body in self._mqtt.feed(payload):
                    if k == kind:
                        if kind == 2 and len(body) >= 2 and body[1] != 0:
                            raise ConnectionError(f"broker refused the connection (code {body[1]})")
                        return body
        raise ConnectionError(f"no answer of MQTT type {kind}")

    def _send(self, packet: bytes) -> None:
        self.sock.sendall(ws_frame(packet))

    def observations(self, seconds: float) -> Iterator[Tuple[str, bytes, float]]:
        """(topic, payload, time received) for ``seconds``."""
        end = time.time() + seconds
        last_ping = time.time()
        self.sock.settimeout(5.0)
        while time.time() < end:
            if time.time() - last_ping > 30:
                self._send(PINGREQ)
                last_ping = time.time()
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not data:
                raise ConnectionError("connection closed by the server")
            for op, payload in self._ws.feed(data):
                if op == 0x9:                      # ping: answer
                    self.sock.sendall(ws_frame(payload, opcode=0xA))
                elif op == 0x8:
                    raise ConnectionError("websocket closed by the server")
                elif op in (0x0, 0x2):
                    for kind, flags, body in self._mqtt.feed(payload):
                        if kind == 3:
                            topic, msg = parse_publish(flags, body)
                            yield topic, msg, time.time()

    def close(self) -> None:
        if self.sock is not None:
            try:
                self._send(b"\xe0\x00")            # DISCONNECT
                self.sock.close()
            except OSError:
                pass
            self.sock = None
