#!/usr/bin/env python3
"""
SSH Proxy Manager
Proxy remote VPC services to local machine through a bastion host
"""

import argparse
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import yaml
from jinja2 import Environment, BaseLoader, StrictUndefined

# Default port
DEFAULT_REMOTE_PORT = 80

# Template markers for detecting if rendering is needed
TEMPLATE_MARKERS = ('{{', '}}')


class ProxyHTTPHandler(BaseHTTPRequestHandler):
    """HTTP proxy handler that automatically sets correct Host header"""

    # Class variables for proxy configuration
    remote_host = None
    backend_port = None

    def log_message(self, format, *args):
        """Suppress logging to stderr"""
        pass

    def do_CONNECT(self):
        """Handle HTTPS CONNECT requests"""
        self.send_error(405, "Method Not Allowed")

    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def do_PUT(self):
        self._handle_request()

    def do_DELETE(self):
        self._handle_request()

    def do_PATCH(self):
        self._handle_request()

    def do_HEAD(self):
        self._handle_request()

    def do_OPTIONS(self):
        self._handle_request()

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

            # Build forwarding request with correct Host header
            request_line = f"{self.command} {self.path} HTTP/1.1\r\n"

            # Build headers, ensure Host is set to remote server's domain
            headers = []
            for key, value in self.headers.items():
                if key.lower() == 'host':
                    # Replace with remote server's Host
                    headers.append(f"Host: {self.remote_host}\r\n")
                else:
                    headers.append(f"{key}: {value}\r\n")

            # Add Host header if not present
            if not any(k.lower() == 'host' for k in self.headers.keys()):
                headers.append(f"Host: {self.remote_host}\r\n")

            # Send request
            request_data = request_line + ''.join(headers) + "\r\n"
            backend_socket.sendall(request_data.encode('utf-8'))

            if body:
                backend_socket.sendall(body)

            # Read response and forward
            response = b''
            while True:
                try:
                    chunk = backend_socket.recv(8192)
                    if not chunk:
                        break
                    response += chunk
                    # Try to parse response headers to determine if complete
                    if b'\r\n\r\n' in response:
                        # Check Content-Length
                        header_end = response.index(b'\r\n\r\n')
                        header_part = response[:header_end].decode('utf-8', errors='ignore')

                        # For chunked encoding or responses without Content-Length, read until connection closes
                        if 'Transfer-Encoding: chunked' in header_part:
                            # Continue reading until we receive 0\r\n\r\n
                            while True:
                                chunk = backend_socket.recv(8192)
                                if not chunk:
                                    break
                                response += chunk
                                if b'\r\n0\r\n\r\n' in response:
                                    break
                            break
                        elif 'Content-Length:' in header_part:
                            # Parse Content-Length
                            for line in header_part.split('\r\n'):
                                if line.lower().startswith('content-length:'):
                                    content_length = int(line.split(':')[1].strip())
                                    body_start = header_end + 4
                                    while len(response) < body_start + content_length:
                                        chunk = backend_socket.recv(8192)
                                        if not chunk:
                                            break
                                        response += chunk
                                    break
                            break
                        else:
                            # No Content-Length, read until connection closes
                            while True:
                                chunk = backend_socket.recv(8192)
                                if not chunk:
                                    break
                                response += chunk
                            break
                except socket.timeout:
                    break

            backend_socket.close()

            # Send response to client
            self.connection.sendall(response)

        except Exception as e:
            print(f"  X Proxy request failed: {e}")
            self.send_error(502, f"Bad Gateway: {e}")

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
            return
        except ConnectionResetError:
            self.close_connection = 1
            return
        except BrokenPipeError:
            self.close_connection = 1
            return


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server"""
    allow_reuse_address = True
    daemon_threads = True


class SSHProxyManager:
    """SSH Proxy Manager"""

    def __init__(self, config_path, exclude_services, use_http_proxy=True):
        self.config_path = config_path
        self.exclude_services = set(exclude_services)
        self.use_http_proxy = use_http_proxy
        self.config = None
        self.processes = {}  # service_name -> subprocess.Popen
        self.http_servers = {}  # service_name -> HTTPServer
        self.shutdown_requested = False
        self.force_exit = False
        # Create Jinja2 Environment once for reuse
        self._jinja_env = Environment(loader=BaseLoader(), undefined=StrictUndefined)

    def _render_template(self, value, env_vars):
        """Render Jinja2 template, supporting variable references"""
        if not isinstance(value, str):
            return value

        # Quick check: if string doesn't contain template markers, return as-is
        if TEMPLATE_MARKERS[0] not in value or TEMPLATE_MARKERS[1] not in value:
            return value

        try:
            template = self._jinja_env.from_string(value)
            return template.render(env=env_vars)
        except Exception as e:
            print(f"Warning: Template rendering failed for '{value}': {e}")
            return value

    def _render_config_templates(self, config):
        """Recursively render all templates in config"""
        # Extract env variables without modifying original config
        env_vars = config.get('env', {})
        return self._render_value(config, env_vars)

    def _render_value(self, value, env_vars):
        """Recursively render a single value"""
        if isinstance(value, dict):
            # Skip 'env' key, it doesn't need rendering
            return {k: self._render_value(v, env_vars) for k, v in value.items() if k != 'env'}
        elif isinstance(value, list):
            return [self._render_value(item, env_vars) for item in value]
        elif isinstance(value, str):
            return self._render_template(value, env_vars)
        else:
            return value

    def load_config(self):
        """Load configuration file"""
        config_path = Path(self.config_path).expanduser()
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}")
            sys.exit(1)

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # Render templates in config
        self.config = self._render_config_templates(self.config)

        # Validate config
        if 'remote_server' not in self.config:
            print("Error: Config missing 'remote_server' section")
            sys.exit(1)
        if 'services' not in self.config:
            print("Error: Config missing 'services' section")
            sys.exit(1)

        remote_server = self.config['remote_server']
        if 'host' not in remote_server or 'ssh_name' not in remote_server:
            print("Error: remote_server config missing 'host' or 'ssh_name'")
            sys.exit(1)

    def get_services_to_proxy(self):
        """Get list of services to proxy"""
        all_services = set(self.config['services'].keys())
        services_to_proxy = all_services - self.exclude_services
        return services_to_proxy

    def _get_service_connection_info(self, service_config):
        """Get service connection info with default value handling"""
        remote_server = self.config['remote_server']
        remote_host = service_config.get('host', remote_server['host'])
        remote_port = service_config.get('remote_port', DEFAULT_REMOTE_PORT)
        local_port = service_config.get('local_port', remote_port)
        return remote_host, remote_port, local_port

    def _find_available_port(self, start_port=20000, max_attempts=100):
        """Find an available port"""
        for port in range(start_port, start_port + max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
                    return port
            except OSError:
                continue
        raise RuntimeError("Could not find an available port")

    def build_ssh_command(self, service_name, service_config, ssh_tunnel_port):
        """Build SSH command"""
        remote_server = self.config['remote_server']
        ssh_name = remote_server['ssh_name']

        remote_host, remote_port, _ = self._get_service_connection_info(service_config)

        cmd = ['ssh', '-N', '-L', f'{ssh_tunnel_port}:{remote_host}:{remote_port}', ssh_name]
        return cmd, ssh_tunnel_port

    def start_proxy(self, service_name, service_config):
        """Start a single proxy (SSH tunnel + optional HTTP proxy)"""
        remote_host, remote_port, local_port = self._get_service_connection_info(service_config)

        if self.use_http_proxy:
            # Mode: Local HTTP proxy -> SSH tunnel (random port) -> Remote
            # SSH tunnel uses a random port
            ssh_tunnel_port = self._find_available_port()
            cmd, _ = self.build_ssh_command(service_name, service_config, ssh_tunnel_port)

            try:
                # Start SSH tunnel
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                # Wait for SSH tunnel to establish
                time.sleep(0.2)

                # Create HTTP proxy that forwards to SSH tunnel
                handler = type('ProxyHandler', (ProxyHTTPHandler,), {
                    'remote_host': remote_host,
                    'backend_port': ssh_tunnel_port
                })
                server = ThreadedHTTPServer(('127.0.0.1', local_port), handler)
                server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                server_thread.start()

                return process, server
            except Exception as e:
                print(f"X Failed to start: {service_name} - {e}")
                return None, None
        else:
            # Legacy mode: Direct SSH tunnel
            remote_server = self.config['remote_server']
            ssh_name = remote_server['ssh_name']
            cmd = ['ssh', '-N', '-L', f'{local_port}:{remote_host}:{remote_port}', ssh_name]

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                return process, None
            except Exception as e:
                print(f"X Failed to start: {service_name} - {e}")
                return None, None

    def start_all_proxies(self):
        """Start all proxies"""
        services_to_proxy = self.get_services_to_proxy()

        mode_str = "HTTP proxy mode" if self.use_http_proxy else "Direct tunnel mode"
        print(f"[ssh-proxy] Starting proxies ({mode_str})...")
        if self.exclude_services:
            print(f"[ssh-proxy] Excluded services: {', '.join(sorted(self.exclude_services))}")
        print(f"[ssh-proxy] Will proxy {len(services_to_proxy)} services\n")

        # Show services to be started
        for service_name in sorted(services_to_proxy):
            service_config = self.config['services'][service_name]
            remote_host, remote_port, local_port = self._get_service_connection_info(service_config)
            print(f"[{service_name}] -> localhost:{local_port} -> {remote_host}:{remote_port}")

        print()

        # Start all SSH processes
        startup_delay = self.config.get('options', {}).get('startup_delay', 0.5)

        for service_name in sorted(services_to_proxy):
            if self.shutdown_requested:
                break

            service_config = self.config['services'][service_name]
            process, http_server = self.start_proxy(service_name, service_config)

            if process is None:
                print(f"X Failed to start: {service_name}")
                self.stop_all_proxies()
                sys.exit(1)

            self.processes[service_name] = process
            if http_server:
                self.http_servers[service_name] = http_server

            # Brief delay
            time.sleep(startup_delay)

        # Verify all processes are running
        failed_services = []
        for service_name, process in self.processes.items():
            if process.poll() is not None:
                # Process has exited
                failed_services.append(service_name)

        if failed_services:
            print(f"\nX Failed to start: {', '.join(failed_services)}")
            print("-> Rolling back started proxies...")
            self.stop_all_proxies()
            sys.exit(1)

        print("\n[ssh-proxy] All proxies started. Press Ctrl+C to stop.\n")

    def stop_all_proxies(self):
        """Stop all proxies"""
        # Stop HTTP servers first
        for service_name, server in self.http_servers.items():
            try:
                server.shutdown()
                print(f"+ Stopped HTTP proxy: {service_name}")
            except Exception as e:
                print(f"X Failed to stop HTTP proxy: {service_name} - {e}")
        self.http_servers.clear()

        # Then stop SSH processes
        for service_name, process in self.processes.items():
            if process.poll() is None:  # Process still running
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                print(f"+ Stopped SSH tunnel: {service_name}")
        self.processes.clear()

    def wait_for_shutdown(self):
        """Wait for shutdown signal"""
        try:
            # Wait for any process to exit
            while not self.shutdown_requested:
                # Check if any process exited unexpectedly
                for service_name, process in list(self.processes.items()):
                    if process.poll() is not None:
                        print(f"\n[{service_name}] Process exited unexpectedly")
                        self.shutdown_requested = True
                        break

                if self.shutdown_requested:
                    break

                time.sleep(0.5)

        except KeyboardInterrupt:
            pass
        finally:
            if self.force_exit:
                print("\n[ssh-proxy] Force exit!")
                sys.exit(1)
            print("\n[ssh-proxy] Stopping all proxies...")
            self.stop_all_proxies()

    def run(self):
        """Run the proxy manager"""
        self.load_config()
        self.start_all_proxies()
        self.wait_for_shutdown()


# Global variable for signal handling
_manager = None


def signal_handler(signum, frame):
    """Signal handler"""
    global _manager
    if _manager is None:
        return

    if _manager.shutdown_requested:
        # Second signal, force exit
        _manager.force_exit = True
        _manager.shutdown_requested = True
    else:
        # First signal, graceful shutdown
        print(f"\n[ssh-proxy] Received signal {signum}, stopping... (send again to force exit)")
        _manager.shutdown_requested = True


def main():
    global _manager
    parser = argparse.ArgumentParser(
        description='SSH Proxy Manager - Proxy remote services to localhost',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--config', '-c',
        default='./config.yaml',
        help='Config file path (default: ./config.yaml)'
    )
    parser.add_argument(
        '--exclude', '-e',
        nargs='*',
        default=[],
        metavar='SERVICE',
        help='Services to exclude (proxy all services except these)'
    )
    parser.add_argument(
        '--no-http-proxy',
        action='store_true',
        help='Disable HTTP proxy mode, use direct SSH tunnel (Host header will not be modified)'
    )

    args = parser.parse_args()

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and run manager
    use_http_proxy = not args.no_http_proxy
    _manager = SSHProxyManager(args.config, args.exclude, use_http_proxy)
    _manager.run()


if __name__ == '__main__':
    main()
