import errno


def test_tcp_transport_retries_transient_connect_errors(monkeypatch):
    from xpctl.transport.tcp import TCPTransport

    attempts = []
    sleeps = []

    class FakeSocket:
        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, addr):
            attempts.append(addr)
            if len(attempts) < 3:
                raise OSError(errno.EHOSTUNREACH, "No route to host")

        def close(self):
            return None

    monkeypatch.setattr("xpctl.transport.tcp.socket.socket", lambda *args, **kwargs: FakeSocket())
    monkeypatch.setattr("xpctl.transport.tcp.time.sleep", lambda seconds: sleeps.append(seconds))

    transport = TCPTransport(host="xp-truvoice-w02", port=9578, timeout=1.0)
    transport.connect()

    assert len(attempts) == 3
    assert attempts[-1] == ("xp-truvoice-w02", 9578)
    assert sleeps == [0.2, 0.4]
    assert transport.is_connected()
