"""SSH Proxy Manager"""

import socket
import subprocess
import sys
import threading
import time

from .config import ConfigLoader
from .handler import ThreadedHTTPServer, ProxyHTTPHandler

# Default port
DEFAULT_REMOTE_PORT = 80


class SSHProxyManager:
    """SSH Proxy Manager - manages SSH tunnels and HTTP proxies"""

    def __init__(self, config_path: str, exclude_services: list, use_http_proxy: bool = True):
        self.config_loader = ConfigLoader(config_path)
        self.exclude_services = set(exclude_services)
        self.use_http_proxy = use_http_proxy
        self.config = None
        self.processes = {}  # service_name -> subprocess.Popen
        self.http_servers = {}  # service_name -> HTTPServer
        self.shutdown_requested = False
        self.force_exit = False

    def load_config(self):
        """Load configuration file"""
        self.config = self.config_loader.load()

    def get_services_to_proxy(self) -> set:
        """Get list of services to proxy"""
        return self.config_loader.get_services(self.exclude_services)

    def _get_service_connection_info(self, service_config: dict) -> tuple:
        """Get service connection info with default value handling"""
        remote_server = self.config['remote_server']
        remote_host = service_config.get('host', remote_server['host'])
        remote_port = service_config.get('remote_port', DEFAULT_REMOTE_PORT)
        local_port = service_config.get('local_port', remote_port)
        return remote_host, remote_port, local_port

    def _find_available_port(self, start_port: int = 20000, max_attempts: int = 100) -> int:
        """Find an available port"""
        for port in range(start_port, start_port + max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
                    return port
            except OSError:
                continue
        raise RuntimeError("Could not find an available port")

    def build_ssh_command(self, service_name: str, service_config: dict, ssh_tunnel_port: int) -> tuple:
        """Build SSH command"""
        remote_server = self.config['remote_server']
        ssh_name = remote_server['ssh_name']

        remote_host, remote_port, _ = self._get_service_connection_info(service_config)

        cmd = ['ssh', '-N', '-L', f'{ssh_tunnel_port}:{remote_host}:{remote_port}', ssh_name]
        return cmd, ssh_tunnel_port

    def start_proxy(self, service_name: str, service_config: dict) -> tuple:
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
