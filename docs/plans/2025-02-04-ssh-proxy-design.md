# SSH代理管理脚本 - 设计文档

## 概述

创建一个SSH代理管理脚本，用于将远端VPC中的服务通过跳板机代理到本地。脚本支持反向选择服务——指定要开发的服务名，代理除了这些服务之外的所有服务。

## 配置文件格式

配置文件路径：`./config.yaml`

```yaml
# 远端服务器配置
remote_server:
  host: "your-server-ip"  # 远端服务器IP，所有服务都监听在这个IP上
  ssh_name: "your-ssh-user"     # SSH连接名称，用于ssh命令

# 服务定义
services:
  example-service:
    remote_port: 8080
    local_port: 8080  # 可选，默认使用remote_port

  another-service:
    remote_port: 3000
    # local_port未指定，将使用3000

  database:
    remote_port: 3306
    local_port: 13306  # 本地使用不同端口避免冲突
```

## 命令行接口

```bash
# 排除指定服务，代理其他所有服务
python ssh_proxy.py --exclude service-a service-b

# 代理所有服务（不排除任何）
python ssh_proxy.py

# 指定配置文件
python ssh_proxy.py --config /path/to/config.yaml --exclude service-a
```

## 核心流程

### 1. 启动流程

```
解析配置文件 → 确定需要代理的服务列表 → 并发启动SSH进程 → 验证进程状态 → 阻塞等待
```

### 2. SSH命令格式

```bash
ssh -NL <local_port>:<remote_host>:<remote_port> <ssh_name>
```

### 3. 等待与退出

- 主进程调用各子进程的`wait()`方法阻塞等待
- 捕获`SIGINT`（Ctrl+C）信号，向所有子进程发送`SIGTERM`
- 等待所有子进程清理完成后退出

## 错误处理

### 启动失败处理

当SSH进程启动失败时：
- 停止启动新进程
- 向已启动的进程发送SIGTERM
- 等待清理后退出并报错

### 运行时异常处理

- 捕获`SIGINT`、`SIGTERM`信号触发清理
- 子进程意外退出时触发清理并退出
- 所有清理操作在`finally`块中确保执行

## 信号处理

- **SIGINT（Ctrl+C）**：触发优雅关闭
  - 向所有子进程发送`SIGTERM`
  - 等待最多5秒
  - 超时则发送`SIGKILL`强制终止
- **SIGTERM**：与SIGINT相同处理

## 项目结构

```
ssh-proxy/
├── ssh_proxy.py          # 主脚本
├── config.yaml           # 配置文件示例
└── requirements.txt      # Python依赖
```

## 依赖

- `PyYAML` - 解析YAML配置文件
- Python 3.7+
