"""
支持工单工具

这个模块提供创建和管理支持工单的功能。

主要功能：
1. 创建支持工单
2. 查询工单状态
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional


def create_support_ticket(
    title: str,
    problem: str,
    environment: Dict,
    diagnostics: str,
    actions_taken: List[str],
    logs: List[str]
) -> Dict:
    """
    创建支持工单
    
    参数:
        title: 工单标题
        problem: 问题描述
        environment: 环境信息
        diagnostics: 诊断信息
        actions_taken: 已采取的操作
        logs: 相关日志
    
    返回:
        工单信息
    
    示例:
        ticket = create_support_ticket(
            title="Docker daemon 无法启动",
            problem="Docker daemon 启动失败",
            environment={"os": "Ubuntu 24.04"},
            diagnostics="...",
            actions_taken=["重启 Docker"],
            logs=["..."]
        )
    """
    # 生成工单 ID
    ticket_id = f"T-{datetime.now().strftime('%Y')}-{str(uuid.uuid4())[:4].upper()}"
    
    return {
        "success": True,
        "ticket_id": ticket_id,
        "status": "created",
        "title": title,
        "created_at": datetime.now().isoformat()
    }


# Mock 版本用于测试
def create_support_ticket_mock(
    title: str,
    problem: str,
    environment: Dict,
    diagnostics: str,
    actions_taken: List[str],
    logs: List[str]
) -> Dict:
    """
    模拟创建支持工单
    
    用于测试环境，返回模拟数据。
    """
    return {
        "success": True,
        "ticket_id": "T-2026-0001",
        "status": "created",
        "title": title,
        "created_at": "2026-09-16T10:00:00"
    }
