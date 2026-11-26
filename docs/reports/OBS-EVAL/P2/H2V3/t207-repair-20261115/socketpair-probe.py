import json
import socket
import _socket

socket.setdefaulttimeout(2)
try:
    a, b = socket.socketpair()
    a.close()
    b.close()
    result = "connected"
except OSError as exc:
    result = type(exc).__name__
listener = socket.socket()
client = socket.socket()
try:
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    client.settimeout(2)
    _socket.socket.connect(client, listener.getsockname())
    peer, _ = listener.accept()
    peer.close()
    direct = "connected"
except OSError as exc:
    direct = type(exc).__name__
finally:
    client.close()
    listener.close()
print(json.dumps({"socketpair": result, "native_loopback": direct}))
