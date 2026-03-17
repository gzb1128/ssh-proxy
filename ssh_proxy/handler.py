"""HTTP Proxy Handler"""

import socket
import socketserver
from http.server import HTTPServer, BaseHTTPRequestHandler

# HTTP header constants
HEADER_CONTENT_LENGTH = 'content-length:'
HEADER_TRANSFER_ENCODING = 'transfer-encoding:'
TRANSFER_ENCODING_CHUNKED = 'chunked'

# HTTP response markers
HEADER_END_MARKER = b'\r\n\r\n'
CHUNKED_END_MARKER = b'\r\n0\r\n\r\n'


class ProxyHTTPHandler(BaseHTTPRequestHandler):
    """HTTP proxy handler that automatically sets correct Host header.

    Due to BaseHTTPRequestHandler's design, configuration must be set via
    class attributes before instantiation. Use dynamic subclassing:
        handler = type('Handler', (ProxyHTTPHandler,), {
            'remote_host': 'example.com',
            'backend_port': 8080
        })
    """

    # Class variables for proxy configuration (set via subclassing)
    remote_host: str = None
    backend_port: int = None

    def log_message(self, format, *args):
        """Suppress logging to stderr"""
        pass

    def do_CONNECT(self):
        """Handle HTTPS CONNECT requests"""
        self.send_error(405, "Method Not Allowed")

    # All standard HTTP methods delegate to _handle_request
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = (
        lambda self: self._handle_request()
    )

    def _handle_request(self):
        """Handle all HTTP requests"""
        try:
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            # Connect to backend (SSH tunnel)
            backend_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend_socket.settimeout(30)
            backend_socket.connect(('127.0.0.1', self.backend_port))

            try:
                self._send_request(backend_socket, body)
                response = self._read_response(backend_socket)
                self.connection.sendall(response)
            finally:
                backend_socket.close()

        except Exception as e:
            print(f"  X Proxy request failed: {e}")
            self.send_error(502, f"Bad Gateway: {e}")

    def _send_request(self, backend_socket, body):
        """Send HTTP request to backend with corrected Host header"""
        request_line = f"{self.command} {self.path} HTTP/1.1\r\n"

        # Build headers, ensure Host is set to remote server's domain
        headers = []
        host_found = False
        for key, value in self.headers.items():
            if key.lower() == 'host':
                headers.append(f"Host: {self.remote_host}\r\n")
                host_found = True
            else:
                headers.append(f"{key}: {value}\r\n")

        # Add Host header if not present
        if not host_found:
            headers.append(f"Host: {self.remote_host}\r\n")

        request_data = request_line + ''.join(headers) + "\r\n"
        backend_socket.sendall(request_data.encode('utf-8'))

        if body:
            backend_socket.sendall(body)

    def _read_response(self, backend_socket):
        """Read HTTP response from backend"""
        response = b''
        while True:
            try:
                chunk = backend_socket.recv(8192)
                if not chunk:
                    break
                response += chunk

                if HEADER_END_MARKER not in response:
                    continue

                header_end = response.index(HEADER_END_MARKER)
                header_part = response[:header_end].decode('utf-8', errors='ignore').lower()

                if HEADER_TRANSFER_ENCODING in header_part and TRANSFER_ENCODING_CHUNKED in header_part:
                    response = self._read_chunked_response(backend_socket, response)
                    break
                elif HEADER_CONTENT_LENGTH in header_part:
                    response = self._read_content_length_response(backend_socket, response, header_part, header_end)
                    break
                else:
                    # No Content-Length, read until connection closes
                    response = self._read_until_close(backend_socket, response)
                    break

            except socket.timeout:
                break

        return response

    def _read_chunked_response(self, backend_socket, response):
        """Read chunked transfer encoding response"""
        while CHUNKED_END_MARKER not in response:
            chunk = backend_socket.recv(8192)
            if not chunk:
                break
            response += chunk
        return response

    def _read_content_length_response(self, backend_socket, response, header_part, header_end):
        """Read response with Content-Length header"""
        content_length = None
        for line in header_part.split('\r\n'):
            if line.startswith(HEADER_CONTENT_LENGTH):
                content_length = int(line.split(':')[1].strip())
                break

        if content_length is not None:
            body_start = header_end + 4
            while len(response) < body_start + content_length:
                chunk = backend_socket.recv(8192)
                if not chunk:
                    break
                response += chunk
        return response

    def _read_until_close(self, backend_socket, response):
        """Read response until connection closes"""
        while True:
            chunk = backend_socket.recv(8192)
            if not chunk:
                break
            response += chunk
        return response

    def handle_one_request(self):
        """Override to handle connection close gracefully"""
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = 1
                return
            if not self.parse_request():
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(501, "Unsupported method")
                return
            method = getattr(self, mname)
            method()
            self.wfile.flush()
        except socket.timeout:
            self.close_connection = 1
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = 1


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server"""
    allow_reuse_address = True
    daemon_threads = True
