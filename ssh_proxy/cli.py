#!/usr/bin/env python3
"""SSH Proxy Manager - Command Line Interface"""

import argparse
import signal
import sys

from .manager import SSHProxyManager

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
    """Main entry point"""
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
