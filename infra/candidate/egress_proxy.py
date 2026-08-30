from __future__ import annotations

import argparse
import select
import socket
import socketserver


class Proxy(socketserver.StreamRequestHandler):
    allowed: set[str] = set()

    def handle(self) -> None:
        line = self.rfile.readline(8192).decode("latin-1").strip()
        if not line.startswith("CONNECT "):
            self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        authority = line.split(" ", 2)[1]
        host, _, port_text = authority.partition(":")
        while self.rfile.readline(8192) not in {b"\r\n", b"\n", b""}:
            pass
        if not any(host == item or host.endswith("." + item) for item in self.allowed):
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        try:
            upstream = socket.create_connection((host, int(port_text or "443")), timeout=20)
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        sockets = (self.connection, upstream)
        try:
            while True:
                readable, _, _ = select.select(sockets, (), (), 60)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        finally:
            upstream.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--allow", action="append", default=[])
    args = parser.parse_args()
    Proxy.allowed = set(args.allow)
    with socketserver.ThreadingTCPServer(("0.0.0.0", args.port), Proxy) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
