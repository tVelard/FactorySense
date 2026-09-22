import asyncio

from app.ws import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, data):
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


def test_connect_accepts_and_tracks_websocket():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(manager.connect(ws))
    assert ws.accepted is True
    assert ws in manager.active


def test_broadcast_sends_json_to_all_connected_clients():
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    asyncio.run(manager.connect(ws1))
    asyncio.run(manager.connect(ws2))
    asyncio.run(manager.broadcast({"type": "alert_new", "alert": {"id": 1}}))
    assert "alert_new" in ws1.sent[0]
    assert "alert_new" in ws2.sent[0]


def test_broadcast_drops_clients_that_fail_to_send():
    manager = ConnectionManager()
    good, bad = FakeWebSocket(), FakeWebSocket(fail=True)
    asyncio.run(manager.connect(good))
    asyncio.run(manager.connect(bad))
    asyncio.run(manager.broadcast({"type": "ping"}))
    assert bad not in manager.active
    assert good in manager.active


def test_disconnect_removes_websocket():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(manager.connect(ws))
    manager.disconnect(ws)
    assert ws not in manager.active
