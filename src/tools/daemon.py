"""
Docker Daemon 工具

这个模块提供检查 Docker daemon 状态的功能。

主要功能：
1. 检查 daemon 是否运行
2. 检查 daemon 是否可达
3. 获取 daemon 配置
"""

import subprocess
import json
from typing import Dict


def check_daemon_status() -> Dict:
    """
    检查 Docker daemon 状态
    
    返回 daemon 的运行状态和可达性。
    
    返回:
        包含 daemon 状态的字典
    
    示例:
        status = check_daemon_status()
        # {
        #     "status": "running",
        #     "reachable": True,
        #     "message": "Docker daemon is reachable"
        # }
    """
    try:
        # 使用 docker info 检查 daemon 状态
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "status": "running",
                "reachable": True,
                "message": "Docker daemon is reachable"
            }
        else:
            # 解析错误信息
            error_output = result.stderr
            
            if "Cannot connect to the Docker daemon" in error_output:
                return {
                    "success": False,
                    "status": "not_running",
                    "reachable": False,
                    "message": "Cannot connect to the Docker daemon",
                    "error_type": "daemon_unreachable"
                }
            elif "permission denied" in error_output.lower():
                return {
                    "success": False,
                    "status": "permission_denied",
                    "reachable": False,
                    "message": "Permission denied. Try running with sudo or add user to docker group",
                    "error_type": "permission_denied"
                }
            else:
                return {
                    "success": False,
                    "status": "error",
                    "reachable": False,
                    "message": f"Docker daemon error: {error_output}",
                    "error_type": "unknown"
                }
    
    except FileNotFoundError:
        return {
            "success": False,
            "status": "not_installed",
            "reachable": False,
            "message": "Docker is not installed",
            "error_type": "not_installed"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "status": "timeout",
            "reachable": False,
            "message": "Docker daemon check timed out",
            "error_type": "timeout"
        }
    except Exception as e:
        return {
            "success": False,
            "status": "error",
            "reachable": False,
            "message": f"Failed to check daemon status: {str(e)}",
            "error_type": "unknown"
        }


def get_daemon_config() -> Dict:
    """
    获取 Docker daemon 配置
    
    返回 daemon 的配置信息。
    
    返回:
        包含 daemon 配置的字典
    """
    try:
        # 读取 daemon.json 配置文件
        config_paths = [
            "/etc/docker/daemon.json",
            "~/.docker/daemon.json"
        ]
        
        for config_path in config_paths:
            try:
                import os
                expanded_path = os.path.expanduser(config_path)
                if os.path.exists(expanded_path):
                    with open(expanded_path, 'r') as f:
                        config = json.load(f)
                    return {
                        "success": True,
                        "config_path": expanded_path,
                        "config": config
                    }
            except Exception:
                continue
        
        return {
            "success": True,
            "config_path": None,
            "config": {},
            "message": "No daemon.json configuration found"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to read daemon configuration"
        }


# Mock 版本用于测试
def check_daemon_status_mock() -> Dict:
    """
    模拟检查 daemon 状态
    
    用于测试环境，返回模拟数据。
    """
    return {
        "success": True,
        "status": "running",
        "reachable": True,
        "message": "Docker daemon is reachable"
    }
