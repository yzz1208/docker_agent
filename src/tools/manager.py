"""
工具管理器

这个模块负责管理所有工具的调用。
支持 Mock 模式和真实模式。
"""

import os
from typing import Dict, Any, Optional
from .docker_info import get_docker_info, get_docker_info_mock
from .daemon import check_daemon_status, check_daemon_status_mock
from .containers import list_containers, list_containers_mock, inspect_container, inspect_container_mock, get_container_logs
from .disk import check_disk_usage, check_disk_usage_mock
from .ticket import create_support_ticket, create_support_ticket_mock


class ToolManager:
    """
    工具管理器类
    
    负责管理所有工具的调用。
    """
    
    def __init__(self, use_mock: bool = True):
        """
        初始化工具管理器
        
        参数:
            use_mock: 是否使用 Mock 模式
        """
        self.use_mock = use_mock
        self.tools = {
            "get_docker_info": self._get_docker_info,
            "check_daemon_status": self._check_daemon_status,
            "list_containers": self._list_containers,
            "inspect_container": self._inspect_container,
            "get_container_logs": self._get_container_logs,
            "check_disk_usage": self._check_disk_usage,
            "create_support_ticket": self._create_support_ticket,
        }
    
    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具
        
        参数:
            tool_name: 工具名称
            args: 工具参数
        
        返回:
            工具执行结果
        """
        if tool_name not in self.tools:
            return {
                "success": False,
                "error": "tool_not_found",
                "message": f"工具 '{tool_name}' 不存在"
            }
        
        try:
            tool_func = self.tools[tool_name]
            result = await tool_func(**args)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": "execution_error",
                "message": f"工具执行失败: {str(e)}"
            }
    
    async def _get_docker_info(self) -> Dict[str, Any]:
        """获取 Docker 信息"""
        if self.use_mock:
            return get_docker_info_mock()
        return get_docker_info()
    
    async def _check_daemon_status(self) -> Dict[str, Any]:
        """检查 daemon 状态"""
        if self.use_mock:
            return check_daemon_status_mock()
        return check_daemon_status()
    
    async def _list_containers(self, all: bool = True) -> Dict[str, Any]:
        """列出容器"""
        if self.use_mock:
            return list_containers_mock(all)
        return list_containers(all)
    
    async def _inspect_container(self, container_name: str) -> Dict[str, Any]:
        """检查容器"""
        if self.use_mock:
            return inspect_container_mock(container_name)
        return inspect_container(container_name)
    
    async def _get_container_logs(self, container_name: str, tail: int = 100) -> Dict[str, Any]:
        """获取容器日志"""
        if self.use_mock:
            return {
                "success": True,
                "container_name": container_name,
                "logs": f"Mock 日志: 容器 {container_name} 的最后 {tail} 行日志",
                "tail": tail
            }
        return get_container_logs(container_name, tail)
    
    async def _check_disk_usage(self) -> Dict[str, Any]:
        """检查磁盘使用"""
        if self.use_mock:
            return check_disk_usage_mock()
        return check_disk_usage()
    
    async def _create_support_ticket(
        self,
        title: str,
        problem: str,
        environment: Dict,
        diagnostics: str,
        actions_taken: list,
        logs: list
    ) -> Dict[str, Any]:
        """创建支持工单"""
        if self.use_mock:
            return create_support_ticket_mock(title, problem, environment, diagnostics, actions_taken, logs)
        return create_support_ticket(title, problem, environment, diagnostics, actions_taken, logs)
    
    def get_available_tools(self) -> list:
        """
        获取可用工具列表
        
        返回:
            工具名称列表
        """
        return list(self.tools.keys())
    
    def get_tool_description(self, tool_name: str) -> Optional[str]:
        """
        获取工具描述
        
        参数:
            tool_name: 工具名称
        
        返回:
            工具描述
        """
        descriptions = {
            "get_docker_info": "获取 Docker 环境信息，包括版本、系统信息等",
            "check_daemon_status": "检查 Docker daemon 运行状态",
            "list_containers": "列出所有容器",
            "inspect_container": "检查容器详细信息",
            "get_container_logs": "获取容器日志",
            "check_disk_usage": "检查磁盘使用情况",
            "create_support_ticket": "创建支持工单",
        }
        return descriptions.get(tool_name)


# 全局工具管理器实例
_tool_manager = None


def get_tool_manager(use_mock: bool = None) -> ToolManager:
    """
    获取工具管理器实例
    
    参数:
        use_mock: 是否使用 Mock 模式，如果为 None 则从环境变量读取
    
    返回:
        工具管理器实例
    """
    global _tool_manager
    
    if use_mock is None:
        use_mock = os.getenv("TOOL_MODE", "mock").lower() == "mock"
    
    if _tool_manager is None or _tool_manager.use_mock != use_mock:
        _tool_manager = ToolManager(use_mock=use_mock)
    
    return _tool_manager
