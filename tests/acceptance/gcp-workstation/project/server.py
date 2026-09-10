from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"cloudmake-gcp-inbound\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


# The service must be reachable through the container runtime's published
# interface. Cloudmake still binds the host-side SSH tunnel to loopback only.
server = HTTPServer(("0.0.0.0", 18080), Handler)
server.handle_request()
server.server_close()
