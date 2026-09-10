#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys


port = int(sys.argv[1])
token = sys.argv[2].encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(token)))
        self.end_headers()
        self.wfile.write(token)

    def log_message(self, *_arguments):
        pass


server = HTTPServer(("127.0.0.1", port), Handler)
server.timeout = 30
server.handle_request()
server.server_close()
