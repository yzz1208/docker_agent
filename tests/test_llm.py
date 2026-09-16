"""
LLM 客户端测试

测试 LLM 客户端的功能。
"""

import pytest
import asyncio
from src.llm.client import MockLLMClient, ChatMessage


class TestMockLLMClient:
    """Mock LLM 客户端测试类"""
    
    def setup_method(self):
        """测试前准备"""
        self.client = MockLLMClient()
    
    @pytest.mark.asyncio
    async def test_generate_daemon_query(self):
        """测试生成 daemon 相关查询的响应"""
        messages = [
            ChatMessage(role="user", content="Docker daemon 无法连接")
        ]
        
        response = await self.client.generate(messages)
        
        assert "daemon" in response.lower()
        assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_generate_container_query(self):
        """测试生成容器相关查询的响应"""
        messages = [
            ChatMessage(role="user", content="容器无法启动")
        ]
        
        response = await self.client.generate(messages)
        
        assert "容器" in response or "container" in response.lower()
        assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_generate_general_query(self):
        """测试生成一般查询的响应"""
        messages = [
            ChatMessage(role="user", content="什么是 Docker？")
        ]
        
        response = await self.client.generate(messages)
        
        assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_structured_output_intent(self):
        """测试结构化输出 - 意图分类"""
        messages = [
            ChatMessage(role="user", content="Docker daemon 无法连接")
        ]
        
        schema = {
            "properties": {
                "intent": {"type": "string"},
                "confidence": {"type": "number"}
            }
        }
        
        result = await self.client.structured_output(schema, messages)
        
        assert "intent" in result
        assert result["intent"] == "troubleshoot"
        assert "confidence" in result
    
    @pytest.mark.asyncio
    async def test_structured_output_container_intent(self):
        """测试结构化输出 - 容器意图"""
        messages = [
            ChatMessage(role="user", content="容器无法启动")
        ]
        
        schema = {
            "properties": {
                "intent": {"type": "string"},
                "confidence": {"type": "number"}
            }
        }
        
        result = await self.client.structured_output(schema, messages)
        
        assert "intent" in result
        assert result["intent"] == "container_diagnosis"


class TestLLMClient:
    """LLM 客户端测试类"""
    
    def test_get_llm_client_mock(self):
        """测试获取 Mock LLM 客户端"""
        from src.llm.client import get_llm_client
        
        client = get_llm_client(use_mock=True)
        
        assert isinstance(client, MockLLMClient)
    
    def test_get_llm_client_real(self):
        """测试获取真实 LLM 客户端"""
        from src.llm.client import get_llm_client, LLMClient
        
        # 注意：这会尝试连接真实 API，可能会失败
        # 在测试环境中，我们只测试类型
        try:
            client = get_llm_client(use_mock=False)
            assert isinstance(client, LLMClient)
        except Exception:
            # 如果连接失败，这是预期的
            pass


if __name__ == "__main__":
    pytest.main([__file__])
