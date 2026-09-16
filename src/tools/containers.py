"""
容器管理工具

这个模块提供 Docker 容器的管理功能。

主要功能：
1. 列出容器
2. 检查容器状态
3. 获取容器信息
4. 检查容器日志
"""

import subprocess
import json
from typing import List, Dict, Optional


def list_containers(all: bool = True) -> List[Dict]:
    """
    列出容器
    
    参数:
        all: 是否列出所有容器（包括已停止的）
    
    返回:
        容器列表
    
    示例:
        containers = list_containers(all=True)
        # [
        #     {
        #         "id": "abc123",
        #         "name": "api-server",
        #         "status": "running",
        #         "image": "demo-api:latest"
        #     }
        # ]
    """
    try:
        # 构建命令
        cmd = ["docker", "ps", "--format", "json"]
        if all:
            cmd.append("-a")
        
        # 执行命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": "docker_error",
                "message": f"Failed to list containers: {result.stderr}"
            }
        
        # 解析 JSON 输出（每行一个 JSON 对象）
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                container = json.loads(line)
                containers.append({
                    "id": container.get("ID", ""),
                    "name": container.get("Names", ""),
                    "status": container.get("Status", ""),
                    "image": container.get("Image", ""),
                    "created": container.get("CreatedAt", ""),
                    "ports": container.get("Ports", "")
                })
        
        return {
            "success": True,
            "containers": containers,
            "count": len(containers)
        }
    
    except FileNotFoundError:
        return {
            "success": False,
            "error": "docker_not_found",
            "message": "Docker is not installed"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "timeout",
            "message": "Docker command timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "error": "unknown",
            "message": f"Failed to list containers: {str(e)}"
        }


def inspect_container(container_name: str) -> Dict:
    """
    检查容器详细信息
    
    参数:
        container_name: 容器名称或 ID
    
    返回:
        容器详细信息
    
    示例:
        info = inspect_container("api-server")
        # {
        #     "status": "exited",
        #     "exit_code": 137,
        #     "oom_killed": True,
        #     "restart_count": 3
        # }
    """
    try:
        # 执行 docker inspect 命令
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": "container_not_found",
                "message": f"Container '{container_name}' not found"
            }
        
        # 解析 JSON 输出
        inspect_data = json.loads(result.stdout)[0]
        
        # 提取关键信息
        state = inspect_data.get("State", {})
        
        return {
            "success": True,
            "container_name": container_name,
            "status": state.get("Status", "unknown"),
            "running": state.get("Running", False),
            "exit_code": state.get("ExitCode", 0),
            "oom_killed": state.get("OOMKilled", False),
            "restart_count": inspect_data.get("RestartCount", 0),
            "image": inspect_data.get("Config", {}).get("Image", ""),
            "created": inspect_data.get("Created", "")
        }
    
    except FileNotFoundError:
        return {
            "success": False,
            "error": "docker_not_found",
            "message": "Docker is not installed"
        }
    except json.JSONDecodeError:
        return {
            "success": False,
            "error": "parse_error",
            "message": "Failed to parse container information"
        }
    except Exception as e:
        return {
            "success": False,
            "error": "unknown",
            "message": f"Failed to inspect container: {str(e)}"
        }


def get_container_logs(container_name: str, tail: int = 100) -> Dict:
    """
    获取容器日志
    
    参数:
        container_name: 容器名称或 ID
        tail: 返回的日志行数
    
    返回:
        容器日志
    
    示例:
        logs = get_container_logs("api-server", tail=50)
        # {
        #     "success": True,
        #     "logs": "2024-01-01 ..."
        # }
    """
    try:
        # 执行 docker logs 命令
        result = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": "container_not_found",
                "message": f"Container '{container_name}' not found or logs unavailable"
            }
        
        return {
            "success": True,
            "container_name": container_name,
            "logs": result.stdout,
            "errors": result.stderr if result.stderr else None,
            "tail": tail
        }
    
    except FileNotFoundError:
        return {
            "success": False,
            "error": "docker_not_found",
            "message": "Docker is not installed"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "timeout",
            "message": "Docker logs command timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "error": "unknown",
            "message": f"Failed to get container logs: {str(e)}"
        }


# Mock 版本用于测试
def list_containers_mock(all: bool = True) -> List[Dict]:
    """
    模拟列出容器
    
    用于测试环境，返回模拟数据。
    """
    return {
        "success": True,
        "containers": [
            {
                "id": "abc123def456",
                "name": "api-server",
                "status": "Exited (137) 2 hours ago",
                "image": "demo-api:latest",
                "created": "2024-01-01 10:00:00",
                "ports": ""
            },
            {
                "id": "789ghi012jkl",
                "name": "postgres-db",
                "status": "Up 5 hours",
                "image": "postgres:16",
                "created": "2024-01-01 08:00:00",
                "ports": "0.0.0.0:5432->5432/tcp"
            }
        ],
        "count": 2
    }


def inspect_container_mock(container_name: str) -> Dict:
    """
    模拟检查容器
    
    用于测试环境，返回模拟数据。
    """
    mock_data = {
        "api-server": {
            "success": True,
            "container_name": "api-server",
            "status": "exited",
            "running": False,
            "exit_code": 137,
            "oom_killed": True,
            "restart_count": 3,
            "image": "demo-api:latest",
            "created": "2024-01-01T10:00:00"
        }
    }
    
    return mock_data.get(container_name, {
        "success": False,
        "error": "container_not_found",
        "message": f"Container '{container_name}' not found"
    })
