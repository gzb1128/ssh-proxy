#!/usr/bin/env python3
"""
SSH代理管理脚本
将远端VPC中的服务通过跳板机代理到本地
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml


class SSHProxyManager:
    """SSH代理管理器"""

    def __init__(self, config_path, exclude_services):
        self.config_path = config_path
        self.exclude_services = set(exclude_services)
        self.config = None
        self.processes = {}  # service_name -> subprocess.Popen
        self.shutdown_requested = False

    def load_config(self):
        """加载配置文件"""
        config_path = Path(self.config_path).expanduser()
        if not config_path.exists():
            print(f"错误: 配置文件不存在: {config_path}")
            sys.exit(1)

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

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

    def build_ssh_command(self, service_name, service_config):
        """构造SSH命令"""
        remote_server = self.config['remote_server']
        remote_host = remote_server['host']
        ssh_name = remote_server['ssh_name']

        remote_port = service_config['remote_port']
        local_port = service_config.get('local_port', remote_port)

        cmd = ['ssh', '-N', '-L', f'{local_port}:{remote_host}:{remote_port}', ssh_name]
        return cmd, local_port

    def start_proxy(self, service_name, service_config):
        """启动单个代理"""
        cmd, local_port = self.build_ssh_command(service_name, service_config)
        remote_host = self.config['remote_server']['host']
        remote_port = service_config['remote_port']

        try:
            # stdout/stderr直接继承到终端
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return process
        except Exception as e:
            print(f"✗ 启动失败: {service_name} - {e}")
            return None

    def start_all_proxies(self):
        """启动所有代理"""
        services_to_proxy = self.get_services_to_proxy()

        print("[ssh-proxy] 正在启动代理...")
        if self.exclude_services:
            print(f"[ssh-proxy] 排除的服务: {', '.join(sorted(self.exclude_services))}")
        print(f"[ssh-proxy] 将代理 {len(services_to_proxy)} 个服务\n")

        # 先显示将要启动的服务
        remote_host = self.config['remote_server']['host']
        for service_name in sorted(services_to_proxy):
            service_config = self.config['services'][service_name]
            remote_port = service_config['remote_port']
            local_port = service_config.get('local_port', remote_port)
            print(f"[{service_name}] → localhost:{local_port} -> {remote_host}:{remote_port}")

        print()

        # 启动所有SSH进程
        startup_delay = self.config.get('options', {}).get('startup_delay', 0.5)

        for service_name in sorted(services_to_proxy):
            if self.shutdown_requested:
                break

            service_config = self.config['services'][service_name]
            process = self.start_proxy(service_name, service_config)

            if process is None:
                print(f"✗ 启动失败: {service_name}")
                self.stop_all_proxies()
                sys.exit(1)

            self.processes[service_name] = process

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
        for service_name, process in self.processes.items():
            if process.poll() is None:  # 进程仍在运行
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                print(f"✓ 已停止: {service_name}")

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
            print("\n[ssh-proxy] 正在停止所有代理...")
            self.stop_all_proxies()

    def run(self):
        """运行代理管理器"""
        self.load_config()
        self.start_all_proxies()
        self.wait_for_shutdown()


def signal_handler(signum, frame):
    """信号处理器"""
    print(f"\n[ssh-proxy] 收到信号 {signum}")
    # 这里我们只是设置标志，实际的清理在wait_for_shutdown中处理


def main():
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

    args = parser.parse_args()

    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 创建并运行管理器
    manager = SSHProxyManager(args.config, args.exclude)
    manager.run()


if __name__ == '__main__':
    main()
