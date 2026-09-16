"""
磁盘检查工具

这个模块提供检查磁盘使用情况的功能。

主要功能：
1. 检查磁盘使用情况
2. 检查 Docker 占用的磁盘空间
"""

import subprocess
import json
from typing import Dict


def check_disk_usage() -> Dict:
    """
    检查磁盘使用情况
    
    返回磁盘使用统计信息。
    
    返回:
        包含磁盘使用信息的字典
    
    示例:
        usage = check_disk_usage()
        # {
        #     "disk_total_gb": 512,
        #     "disk_used_percent": 94,
        #     "docker_root_usage_gb": 180
        # }
    """
    try:
        # 获取磁盘使用情况
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": "df_error",
                "message": "Failed to get disk usage"
            }
        
        # 解析输出
        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            return {
                "success": False,
                "error": "parse_error",
                "message": "Failed to parse disk usage output"
            }
        
        # 解析第二行（数据行）
        parts = lines[1].split()
        
        # 提取信息
        total = parts[1]  # 总容量
        used = parts[2]   # 已使用
        available = parts[3]  # 可用
        use_percent = parts[4]  # 使用百分比
        
        # 转换为 GB
        def parse_size(size_str: str) -> float:
            """解析大小字符串（如 512G, 1T）"""
            if 'T' in size_str:
                return float(size_str.replace('T', '')) * 1024
            elif 'G' in size_str:
                return float(size_str.replace('G', ''))
            elif 'M' in size_str:
                return float(size_str.replace('M', '')) / 1024
            return 0
        
        return {
            "success": True,
            "disk_total_gb": parse_size(total),
            "disk_used_gb": parse_size(used),
            "disk_available_gb": parse_size(available),
            "disk_used_percent": int(use_percent.replace('%', ''))
        }
    
    except FileNotFoundError:
        return {
            "success": False,
            "error": "command_not_found",
            "message": "df command not found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": "unknown",
            "message": f"Failed to check disk usage: {str(e)}"
        }


def check_docker_disk_usage() -> Dict:
    """
    检查 Docker 使用的磁盘空间
    
    返回 Docker 使用的磁盘空间统计。
    
    返回:
        包含 Docker 磁盘使用信息的字典
    """
    try:
        # 获取 Docker 磁盘使用情况
        result = subprocess.run(
            ["docker", "system", "df"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "error": "docker_error",
                "message": "Failed to get Docker disk usage"
            }
        
        # 解析输出
        output = result.stdout
        
        # 提取关键信息
        # 这里简化处理，实际应该解析表格
        return {
            "success": True,
            "raw_output": output,
            "message": "Docker disk usage retrieved"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": "unknown",
            "message": f"Failed to check Docker disk usage: {str(e)}"
        }


# Mock 版本用于测试
def check_disk_usage_mock() -> Dict:
    """
    模拟检查磁盘使用
    
    用于测试环境，返回模拟数据。
    """
    return {
        "success": True,
        "disk_total_gb": 512,
        "disk_used_gb": 481,
        "disk_available_gb": 31,
        "disk_used_percent": 94
    }
