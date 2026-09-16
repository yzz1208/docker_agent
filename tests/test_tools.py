"""
工具系统测试

测试工具管理器和各个工具的功能。
"""

import pytest
import asyncio
from src.tools.manager import ToolManager, get_tool_manager


class TestToolManager:
    """工具管理器测试类"""
    
    def setup_method(self):
        """测试前准备"""
        self.tool_manager = ToolManager(use_mock=True)
    
    def test_get_available_tools(self):
        """测试获取可用工具列表"""
        tools = self.tool_manager.get_available_tools()
        
        assert len(tools) > 0
        assert "get_docker_info" in tools
        assert "check_daemon_status" in tools
        assert "list_containers" in tools
        assert "inspect_container" in tools
        assert "get_container_logs" in tools
        assert "check_disk_usage" in tools
        assert "create_support_ticket" in tools
    
    def test_get_tool_description(self):
        """测试获取工具描述"""
        desc = self.tool_manager.get_tool_description("get_docker_info")
        
        assert desc is not None
        assert len(desc) > 0
    
    def test_get_tool_description_not_found(self):
        """测试获取不存在的工具描述"""
        desc = self.tool_manager.get_tool_description("nonexistent_tool")
        
        assert desc is None
    
    @pytest.mark.asyncio
    async def test_execute_tool_get_docker_info(self):
        """测试执行 get_docker_info 工具"""
        result = await self.tool_manager.execute_tool("get_docker_info", {})
        
        assert result["success"] is True
        assert "version" in result
        assert "os" in result
    
    @pytest.mark.asyncio
    async def test_execute_tool_check_daemon_status(self):
        """测试执行 check_daemon_status 工具"""
        result = await self.tool_manager.execute_tool("check_daemon_status", {})
        
        assert result["success"] is True
        assert "status" in result
        assert "reachable" in result
    
    @pytest.mark.asyncio
    async def test_execute_tool_list_containers(self):
        """测试执行 list_containers 工具"""
        result = await self.tool_manager.execute_tool("list_containers", {"all": True})
        
        assert result["success"] is True
        assert "containers" in result
        assert "count" in result
    
    @pytest.mark.asyncio
    async def test_execute_tool_inspect_container(self):
        """测试执行 inspect_container 工具"""
        result = await self.tool_manager.execute_tool("inspect_container", {"container_name": "api-server"})
        
        assert result["success"] is True
        assert "container_name" in result
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        """测试执行不存在的工具"""
        result = await self.tool_manager.execute_tool("nonexistent_tool", {})
        
        assert result["success"] is False
        assert result["error"] == "tool_not_found"


class TestMockTools:
    """Mock 工具测试类"""
    
    def test_get_docker_info_mock(self):
        """测试 Mock Docker 信息"""
        from src.tools.docker_info import get_docker_info_mock
        
        result = get_docker_info_mock()
        
        assert result["success"] is True
        assert "version" in result
        assert "os" in result
    
    def test_check_daemon_status_mock(self):
        """测试 Mock daemon 状态检查"""
        from src.tools.daemon import check_daemon_status_mock
        
        result = check_daemon_status_mock()
        
        assert result["success"] is True
        assert result["status"] == "running"
        assert result["reachable"] is True
    
    def test_list_containers_mock(self):
        """测试 Mock 容器列表"""
        from src.tools.containers import list_containers_mock
        
        result = list_containers_mock()
        
        assert result["success"] is True
        assert "containers" in result
        assert len(result["containers"]) > 0
    
    def test_inspect_container_mock(self):
        """测试 Mock 容器检查"""
        from src.tools.containers import inspect_container_mock
        
        result = inspect_container_mock("api-server")
        
        assert result["success"] is True
        assert result["container_name"] == "api-server"
        assert "exit_code" in result
    
    def test_check_disk_usage_mock(self):
        """测试 Mock 磁盘使用检查"""
        from src.tools.disk import check_disk_usage_mock
        
        result = check_disk_usage_mock()
        
        assert result["success"] is True
        assert "disk_total_gb" in result
        assert "disk_used_percent" in result


if __name__ == "__main__":
    pytest.main([__file__])
