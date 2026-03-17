#!/usr/bin/env python3
"""
SSH代理管理脚本
将远端VPC中的服务通过跳板机代理到本地
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

# 默认端口号
DEFAULT_REMOTE_PORT = 80

# 模板标记，用于检测是否需要渲染
TEMPLATE_MARKERS = ('{{', '}}')


class ProxyHTTPHandler(BaseHTTPRequestHandler):
    """HTTP代理处理器，自动设置正确的Host头"""

    # 类变量，用于存储代理配置
    remote_host = None
    backend_port = None

    def log_message(self, format, *args):
        """静默日志，不输出到stderr"""
        pass

    def do_CONNECT(self):
        """处理HTTPS CONNECT请求"""
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
        """处理所有HTTP请求"""
        try:
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            # 连接后端（SSH隧道）
            backend_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend_socket.settimeout(30)
            backend_socket.connect(('127.0.0.1', self.backend_port))

            # 构建转发请求，使用正确的Host头
            request_line = f"{self.command} {self.path} HTTP/1.1\r\n"

            # 构建请求头，确保Host是远端服务器的域名
            headers = []
            for key, value in self.headers.items():
                if key.lower() == 'host':
                    # 替换为远端服务器的Host
                    headers.append(f"Host: {self.remote_host}\r\n")
                else:
                    headers.append(f"{key}: {value}\r\n")

            # 如果没有Host头，添加一个
            if not any(k.lower() == 'host' for k in self.headers.keys()):
                headers.append(f"Host: {self.remote_host}\r\n")

            # 发送请求
            request_data = request_line + ''.join(headers) + "\r\n"
            backend_socket.sendall(request_data.encode('utf-8'))

            if body:
                backend_socket.sendall(body)

            # 读取响应并转发
            response = b''
            while True:
                try:
                    chunk = backend_socket.recv(8192)
                    if not chunk:
                        break
                    response += chunk
                    # 尝试解析响应头，判断是否结束
                    if b'\r\n\r\n' in response:
                        # 检查Content-Length
                        header_end = response.index(b'\r\n\r\n')
                        header_part = response[:header_end].decode('utf-8', errors='ignore')

                        # 对于chunked编码或无Content-Length的响应，持续读取直到连接关闭
                        if 'Transfer-Encoding: chunked' in header_part:
                            # 继续读取直到收到0\r\n\r\n
                            while True:
                                chunk = backend_socket.recv(8192)
                                if not chunk:
                                    break
                                response += chunk
                                if b'\r\n0\r\n\r\n' in response:
                                    break
                            break
                        elif 'Content-Length:' in header_part:
                            # 解析Content-Length
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
                            # 无Content-Length，读取到连接关闭
                            while True:
                                chunk = backend_socket.recv(8192)
                                if not chunk:
                                    break
                                response += chunk
                            break
                except socket.timeout:
                    break

            backend_socket.close()

            # 发送响应给客户端
            self.connection.sendall(response)

        except Exception as e:
            print(f"  ✗ 代理请求失败: {e}")
            self.send_error(502, f"Bad Gateway: {e}")

    def handle_one_request(self):
        """重写以处理连接关闭的情况"""
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
    """多线程HTTP服务器"""
    allow_reuse_address = True
    daemon_threads = True


class SSHProxyManager:
    """SSH代理管理器"""

    def __init__(self, config_path, exclude_services, use_http_proxy=True):
        self.config_path = config_path
        self.exclude_services = set(exclude_services)
        self.use_http_proxy = use_http_proxy
        self.config = None
        self.processes = {}  # service_name -> subprocess.Popen
        self.http_servers = {}  # service_name -> HTTPServer
        self.shutdown_requested = False
        self.force_exit = False  # 第二次信号时强制退出
        # 创建 Jinja2 Environment 一次，复用
        self._jinja_env = Environment(loader=BaseLoader(), undefined=StrictUndefined)

    def _render_template(self, value, env_vars):
        """渲染 Jinja2 模板，支持变量引用"""
        if not isinstance(value, str):
            return value

        # 快速检查：如果字符串不包含模板标记，直接返回
        if TEMPLATE_MARKERS[0] not in value or TEMPLATE_MARKERS[1] not in value:
            return value

        try:
            template = self._jinja_env.from_string(value)
            return template.render(env=env_vars)
        except Exception as e:
            print(f"警告: 模板渲染失败 '{value}': {e}")
            return value

    def _render_config_templates(self, config):
        """递归渲染配置中的所有模板"""
        # 使用 get 提取 env 变量定义，不破坏原始配置
        env_vars = config.get('env', {})
        return self._render_value(config, env_vars)

    def _render_value(self, value, env_vars):
        """递归渲染单个值"""
        if isinstance(value, dict):
            # 跳过 'env' 键，它不需要渲染
            return {k: self._render_value(v, env_vars) for k, v in value.items() if k != 'env'}
        elif isinstance(value, list):
            return [self._render_value(item, env_vars) for item in value]
        elif isinstance(value, str):
            return self._render_template(value, env_vars)
        else:
            return value

    def load_config(self):
        """加载配置文件"""
        config_path = Path(self.config_path).expanduser()
        if not config_path.exists():
            print(f"错误: 配置文件不存在: {config_path}")
            sys.exit(1)

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # 渲染配置中的模板
        self.config = self._render_config_templates(self.config)

        # 验证配置
        if 'remote_server' not in self.config:
            print("错误: 配置文件缺少 remote_server 配置")
            sys.exit(1)
        if 'services' not in self.config:
            print("错误: 配置文件缺少 services 配置")
            sys.exit(1)

        remote_server = self.config['remote_server']
        if 'host' not in remote_server or 'ssh_name' not in remote_server:
            print("错误: remote_server 配置缺少 host 或 ssh_name")
            sys.exit(1)

    def get_services_to_proxy(self):
        """获取需要代理的服务列表"""
        all_services = set(self.config['services'].keys())
        services_to_proxy = all_services - self.exclude_services
        return services_to_proxy

    def _get_service_connection_info(self, service_config):
        """获取服务的连接信息，统一处理默认值逻辑"""
        remote_server = self.config['remote_server']
        remote_host = service_config.get('host', remote_server['host'])
        remote_port = service_config.get('remote_port', DEFAULT_REMOTE_PORT)
        local_port = service_config.get('local_port', remote_port)
        return remote_host, remote_port, local_port

    def _find_available_port(self, start_port=20000, max_attempts=100):
        """查找可用端口"""
        for port in range(start_port, start_port + max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
                    return port
            except OSError:
                continue
        raise RuntimeError("无法找到可用端口")

    def build_ssh_command(self, service_name, service_config, ssh_tunnel_port):
        """构造SSH命令"""
        remote_server = self.config['remote_server']
        ssh_name = remote_server['ssh_name']

        remote_host, remote_port, _ = self._get_service_connection_info(service_config)

        cmd = ['ssh', '-N', '-L', f'{ssh_tunnel_port}:{remote_host}:{remote_port}', ssh_name]
        return cmd, ssh_tunnel_port

    def start_proxy(self, service_name, service_config):
        """启动单个代理（SSH隧道 + 可选的HTTP代理）"""
        remote_host, remote_port, local_port = self._get_service_connection_info(service_config)

        if self.use_http_proxy:
            # 模式：本地HTTP代理 -> SSH隧道(随机端口) -> 远端
            # SSH隧道使用随机端口
            ssh_tunnel_port = self._find_available_port()
            cmd, _ = self.build_ssh_command(service_name, service_config, ssh_tunnel_port)

            try:
                # 启动SSH隧道
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                # 等待SSH隧道建立
                time.sleep(0.2)

                # 创建HTTP代理，转发到SSH隧道
                handler = type('ProxyHandler', (ProxyHTTPHandler,), {
                    'remote_host': remote_host,
                    'backend_port': ssh_tunnel_port
                })
                server = ThreadedHTTPServer(('127.0.0.1', local_port), handler)
                server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                server_thread.start()

                return process, server
            except Exception as e:
                print(f"✗ 启动失败: {service_name} - {e}")
                return None, None
        else:
            # 传统模式：直接SSH隧道
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
                print(f"✗ 启动失败: {service_name} - {e}")
                return None, None

    def start_all_proxies(self):
        """启动所有代理"""
        services_to_proxy = self.get_services_to_proxy()

        mode_str = "HTTP代理模式" if self.use_http_proxy else "直接隧道模式"
        print(f"[ssh-proxy] 正在启动代理 ({mode_str})...")
        if self.exclude_services:
            print(f"[ssh-proxy] 排除的服务: {', '.join(sorted(self.exclude_services))}")
        print(f"[ssh-proxy] 将代理 {len(services_to_proxy)} 个服务\n")

        # 先显示将要启动的服务
        for service_name in sorted(services_to_proxy):
            service_config = self.config['services'][service_name]
            remote_host, remote_port, local_port = self._get_service_connection_info(service_config)
            print(f"[{service_name}] → localhost:{local_port} -> {remote_host}:{remote_port}")

        print()

        # 启动所有SSH进程
        startup_delay = self.config.get('options', {}).get('startup_delay', 0.5)

        for service_name in sorted(services_to_proxy):
            if self.shutdown_requested:
                break

            service_config = self.config['services'][service_name]
            process, http_server = self.start_proxy(service_name, service_config)

            if process is None:
                print(f"✗ 启动失败: {service_name}")
                self.stop_all_proxies()
                sys.exit(1)

            self.processes[service_name] = process
            if http_server:
                self.http_servers[service_name] = http_server

            # 短暂延迟
            time.sleep(startup_delay)

        # 验证所有进程是否正常运行
        failed_services = []
        for service_name, process in self.processes.items():
            if process.poll() is not None:
                # 进程已退出
                failed_services.append(service_name)

        if failed_services:
            print(f"\n✗ 启动失败: {', '.join(failed_services)}")
            print("→ 正在回滚已启动的代理...")
            self.stop_all_proxies()
            sys.exit(1)

        print("\n[ssh-proxy] ✓ 所有代理已启动，按 Ctrl+C 停止\n")

    def stop_all_proxies(self):
        """停止所有代理"""
        # 先停止HTTP服务器
        for service_name, server in self.http_servers.items():
            try:
                server.shutdown()
                print(f"✓ 已停止HTTP代理: {service_name}")
            except Exception as e:
                print(f"✗ 停止HTTP代理失败: {service_name} - {e}")
        self.http_servers.clear()

        # 再停止SSH进程
        for service_name, process in self.processes.items():
            if process.poll() is None:  # 进程仍在运行
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                print(f"✓ 已停止SSH隧道: {service_name}")
        self.processes.clear()

    def wait_for_shutdown(self):
        """等待 shutdown 信号"""
        try:
            # 等待任一进程退出
            while not self.shutdown_requested:
                # 检查是否有进程意外退出
                for service_name, process in list(self.processes.items()):
                    if process.poll() is not None:
                        print(f"\n[{service_name}] 进程意外退出")
                        self.shutdown_requested = True
                        break

                if self.shutdown_requested:
                    break

                time.sleep(0.5)

        except KeyboardInterrupt:
            pass
        finally:
            if self.force_exit:
                print("\n[ssh-proxy] 强制退出！")
                sys.exit(1)
            print("\n[ssh-proxy] 正在停止所有代理...")
            self.stop_all_proxies()

    def run(self):
        """运行代理管理器"""
        self.load_config()
        self.start_all_proxies()
        self.wait_for_shutdown()


# 全局变量，用于信号处理
_manager = None


def signal_handler(signum, frame):
    """信号处理器"""
    global _manager
    if _manager is None:
        return

    if _manager.shutdown_requested:
        # 第二次信号，强制退出
        _manager.force_exit = True
        _manager.shutdown_requested = True
    else:
        # 第一次信号，体面终止
        print(f"\n[ssh-proxy] 收到信号 {signum}，正在停止... (再次发送信号将强制退出)")
        _manager.shutdown_requested = True


def main():
    global _manager
    parser = argparse.ArgumentParser(
        description='SSH代理管理脚本 - 将远端服务代理到本地',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--config', '-c',
        default='./config.yaml',
        help='配置文件路径 (默认: ./config.yaml)'
    )
    parser.add_argument(
        '--exclude', '-e',
        nargs='*',
        default=[],
        metavar='SERVICE',
        help='要排除的服务名称（将代理除这些服务外的所有服务）'
    )
    parser.add_argument(
        '--no-http-proxy',
        action='store_true',
        help='禁用HTTP代理模式，使用直接SSH隧道（Host头不会被修改）'
    )

    args = parser.parse_args()

    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 创建并运行管理器
    use_http_proxy = not args.no_http_proxy
    _manager = SSHProxyManager(args.config, args.exclude, use_http_proxy)
    _manager.run()


if __name__ == '__main__':
    main()
