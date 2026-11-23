import struct

from drivenow.hamburg.live import (MqttParser, WsParser, connect_packet, parse_observation, parse_publish,
                                   subscribe_packet, ws_frame)


def test_connect_and_subscribe_packets():
    p = connect_packet("dn", keepalive=60)
    # fixed header, remaining length 14, "MQTT", level 4, clean session, keepalive 60, client id
    assert p == b"\x10\x0e\x00\x04MQTT\x04\x02\x00\x3c\x00\x02dn"
    s = subscribe_packet(1, ["a/b"])
    assert s == b"\x82\x08\x00\x01\x00\x03a/b\x00"


def test_websocket_frames_round_trip_and_split_reads():
    frame = ws_frame(b"hello", mask=b"\x01\x02\x03\x04")
    assert frame[:2] == b"\x82\x85" and frame[2:6] == b"\x01\x02\x03\x04"
    ws = WsParser()
    assert ws.feed(frame[:4]) == []                       # incomplete
    assert ws.feed(frame[4:]) == [(2, b"hello")]
    big = bytes(range(256)) * 2                            # 512 bytes: 16-bit length
    server = b"\x82\x7e" + struct.pack(">H", len(big)) + big
    assert WsParser().feed(server) == [(2, big)]


def test_publish_packets_split_across_frames():
    topic, body = "v1.1/Datastreams(16538)/Observations", b'{"result": 1}'
    pkt = bytes([0x30]) + bytes([2 + len(topic) + len(body)]) + struct.pack(">H", len(topic)) + topic.encode() + body
    m = MqttParser()
    assert m.feed(pkt[:7]) == []
    (kind, flags, raw), = m.feed(pkt[7:])
    assert kind == 3 and parse_publish(flags, raw) == (topic, body)


def test_observation_from_hamburg():
    payload = (b'{"@iot.id":130372626556,"phenomenonTime":"2026-11-22T20:19:36Z",'
               b'"resultTime":"2026-11-22T20:19:36.83409Z","result":2}')
    ds, t, result, rt = parse_observation("v1.1/Datastreams(18491)/Observations", payload)
    assert ds == 18491 and result == 2.0
    assert abs((rt - t) - 0.83409) < 1e-6
    assert parse_observation("v1.1/Things(1)", b"{}") is None
    assert parse_observation("v1.1/Datastreams(1)/Observations", b"not json") is None
