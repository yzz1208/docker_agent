"""
Docker 信息工具

这个模块提供获取 Docker 环境基本信息的功能。

主要功能：
1. 获取 Docker 版本信息
2. 获取系统信息
3. 检查 Docker 是否安装
"""

import subprocess
import json
from typing import Dict, Optional


def get_docker_info() -> Dict:
    """
    获取 Docker 环境信息
    
    返回 Docker 的版本、系统信息等。
    
    返回:
        包含 Docker 信息的字典
    
    示例:
        info = get_docker_info()
        # {
        #     "version": "27.1.1",
        #     "server_version": "27.1.1",
        #     "os": "linux",
        #     "architecture": "x86_64"
        # }
    """
    try:
        # 获取 Docker 版本信息
        result = subprocess.run(
            ["docker", "version", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": "docker_not_found",
                "message": "Docker 未安装或无法访问"
            }
        
        # 解析 JSON 输出
        version_info = json.loads(result.stdout)
        
        return {
            "success": True,
            "version": version_info.get("Client", {}).get("Version", "unknown"),
            "server_version": version_info.get("Server", {}).get("Version", "unknown"),
            "os": version_info.get("Server", {}).get("Os", "unknown"),
            "architecture": version_info.get("Server", {}).get("Arch", "unknown")
        }
    
    except FileNotFoundError:
        return {
            "success": False,
            "error": "docker_not_found",
            "message": "Docker 命令未找到，请确保 Docker 已安装"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "timeout",
            "message": "Docker 命令执行超时"
        }
    except Exception as e:
        return {
            "success": False,
            "error": "unknown",
            "message": f"获取 Docker 信息失败: {str(e)}"
        }


def get_docker_system_info() -> Dict:
    """
    获取 Docker 系统信息
    
    返回更详细的系统信息，包括容器数量、镜像数量等。
    
    返回:
        包含系统信息的字典
    """
    try:
        # 获取系统信息
        result = subprocess.run(
            ["docker", "system", "df", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": "docker_error",
                "message": "无法获取 Docker 系统信息"
            }
        
        # 解析输出
        df_info = json.loads(result.stdout)
        
        return {
            "success": True,
            "containers": df_info.get("Containers", {}),
            "images": df_info.get("Images", {}),
            "volumes": df_info.get("Volumes", {}),
            "build_cache": df_info.get("BuildCache", {})
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": "unknown",
            "message": f"获取系统信息失败: {str(e)}"
        }


# Mock 版本用于测试
def get_docker_info_mock() -> Dict:
    """
    模拟获取 Docker 信息
    
    用于测试环境，返回模拟数据。
    
    返回:
        模拟的 Docker 信息
    """
    return {
        "success": True,
        "version": "27.1.1",
        "server_version": "27.1.1",
        "os": "linux",
        "architecture": "x86_64"
    }
