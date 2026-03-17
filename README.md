# SSH Proxy Manager

SSH Proxy Manager is a lightweight SSH tunnel manager that proxies remote VPC services to your local machine through a bastion host.

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## English

### Overview

SSH Proxy Manager simplifies the process of creating and managing SSH tunnels for accessing remote services. It provides:

- YAML-based configuration for managing multiple services
- HTTP proxy mode that automatically sets correct `Host` headers
- Jinja2 template support for environment variables
- Flexible service selection with include/exclude patterns
- Custom host support per service

### Prerequisites

- Python 3.6 or higher
- SSH access to a bastion host
- SSH key-based authentication configured

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ssh-proxy.git
cd ssh-proxy

# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Quick Start

1. Copy the example configuration:

   ```bash
   cp config.yaml.example config.yaml
   ```

2. Edit `config.yaml` with your settings:

   ```yaml
   remote_server:
     host: "your-server-ip"
     ssh_name: "your-ssh-user"

   services:
     my-service:
       remote_port: 8080
       local_port: 8080
   ```

3. Run the proxy manager:

   ```bash
   python ssh_proxy.py
   ```

### Usage

```bash
# Start all services defined in config
python ssh_proxy.py

# Use a different config file
python ssh_proxy.py -c /path/to/config.yaml

# Exclude specific services
python ssh_proxy.py --exclude service1 service2

# Use direct SSH tunnel mode (without HTTP proxy)
python ssh_proxy.py --no-http-proxy
```

### Configuration Reference

#### Top-level Configuration

| Field | Description | Required |
|-------|-------------|----------|
| `remote_server` | Remote server connection settings | Yes |
| `env` | Environment variables for templating | No |
| `services` | Service definitions | Yes |
| `options` | Runtime options | No |

#### remote_server Configuration

| Field | Description | Required |
|-------|-------------|----------|
| `host` | Default remote server IP address | Yes |
| `ssh_name` | SSH connection alias (from ~/.ssh/config) | Yes |

#### Service Configuration

| Field | Description | Default |
|-------|-------------|---------|
| `remote_port` | Remote service port | Required |
| `local_port` | Local port to bind | Same as `remote_port` |
| `host` | Custom remote host | `remote_server.host` |

#### Options Configuration

| Field | Description | Default |
|-------|-------------|---------|
| `startup_delay` | Delay between starting each proxy (seconds) | 0.5 |

### HTTP Proxy Mode

By default, SSH Proxy Manager operates in HTTP proxy mode:

- Creates an HTTP proxy server on the specified `local_port`
- Automatically sets the `Host` header to the remote server's domain
- Enables direct access via `http://localhost:local_port`

This eliminates the need to modify `/etc/hosts` for domain-based services.

Use `--no-http-proxy` flag to disable HTTP proxy mode and use direct SSH tunneling instead.

### Environment Variable Templating

You can use Jinja2 templates to reference environment variables in your configuration:

```yaml
env:
  MY_SERVER_IP: "192.168.1.100"

services:
  my-service:
    host: "{{ env.MY_SERVER_IP }}"
    remote_port: 8080
```

---

<a name="中文"></a>
## 中文

### 概述

SSH Proxy Manager 简化了创建和管理 SSH 隧道访问远程服务的过程。它提供:

- 基于 YAML 的配置文件管理多个服务
- HTTP 代理模式自动设置正确的 `Host` 请求头
- 支持 Jinja2 模板引用环境变量
- 灵活的服务选择,支持包含/排除模式
- 每个服务可配置独立的远程主机

### 前置条件

- Python 3.6 或更高版本
- 具有跳板机的 SSH 访问权限
- 已配置 SSH 密钥认证

### 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/ssh-proxy.git
cd ssh-proxy

# 创建虚拟环境 (推荐)
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 快速开始

1. 复制示例配置:

   ```bash
   cp config.yaml.example config.yaml
   ```

2. 编辑 `config.yaml`:

   ```yaml
   remote_server:
     host: "你的服务器IP"
     ssh_name: "你的SSH用户名"

   services:
     my-service:
       remote_port: 8080
       local_port: 8080
   ```

3. 运行代理管理器:

   ```bash
   python ssh_proxy.py
   ```

### 使用方法

```bash
# 启动配置中的所有服务
python ssh_proxy.py

# 使用其他配置文件
python ssh_proxy.py -c /path/to/config.yaml

# 排除特定服务
python ssh_proxy.py --exclude service1 service2

# 使用直接 SSH 隧道模式 (不带 HTTP 代理)
python ssh_proxy.py --no-http-proxy
```

### 配置参考

完整配置说明请参阅上方英文文档的 "Configuration Reference" 部分。

## License

MIT License. See [LICENSE](LICENSE) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.
