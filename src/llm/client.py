"""
LLM 客户端

这个模块提供与大语言模型交互的客户端。
支持多种 LLM 提供商。

支持的提供商：
1. OpenAI
2. Claude
3. Gemini
4. 其他 OpenAI-compatible API
"""

import os
from typing import List, Dict, Optional, Any
import httpx
from pydantic import BaseModel


class ChatMessage(BaseModel):
    """聊天消息模型"""
    role: str  # system, user, assistant
    content: str


class LLMClient:
    """
    LLM 客户端类
    
    负责与大语言模型 API 交互。
    """
    
    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        初始化 LLM 客户端
        
        参数:
            provider: LLM 提供商
            model: 模型名称
            api_key: API 密钥
            base_url: API 基础 URL
        """
        self.provider = provider or os.getenv("MODEL_PROVIDER", "openai")
        self.model = model or os.getenv("MODEL_NAME", "gpt-4")
        self.api_key = api_key or os.getenv("MODEL_API_KEY", "")
        self.base_url = base_url or os.getenv("MODEL_BASE_URL", "https://api.openai.com/v1")
        
        # HTTP 客户端
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def generate(self, messages: List[ChatMessage], **kwargs) -> str:
        """
        生成文本
        
        参数:
            messages: 消息列表
            **kwargs: 其他参数
        
        返回:
            生成的文本
        """
        # 根据提供商调用不同的 API
        if self.provider == "openai":
            return await self._openai_generate(messages, **kwargs)
        else:
            # 默认使用 OpenAI 兼容的 API
            return await self._openai_generate(messages, **kwargs)
    
    async def _openai_generate(self, messages: List[ChatMessage], **kwargs) -> str:
        """
        使用 OpenAI API 生成文本
        
        参数:
            messages: 消息列表
            **kwargs: 其他参数
        
        返回:
            生成的文本
        """
        # 准备请求数据
        data = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 1000)
        }
        
        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json=data,
            headers=headers
        )
        
        if response.status_code != 200:
            raise Exception(f"LLM API error: {response.status_code} - {response.text}")
        
        # 解析响应
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    async def structured_output(self, schema: Dict, messages: List[ChatMessage]) -> Dict:
        """
        获取结构化输出
        
        参数:
            schema: JSON Schema
            messages: 消息列表
        
        返回:
            结构化数据
        """
        # 在提示中添加格式要求
        format_instruction = f"""
请以 JSON 格式返回结果，格式如下：
{schema}
"""
        
        # 添加格式要求到最后一条消息
        messages_with_format = messages.copy()
        if messages_with_format:
            last_msg = messages_with_format[-1]
            messages_with_format[-1] = ChatMessage(
                role=last_msg.role,
                content=last_msg.content + "\n\n" + format_instruction
            )
        
        # 生成响应
        response = await self.generate(messages_with_format)
        
        # 解析 JSON
        import json
        try:
            # 尝试提取 JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except Exception:
            pass
        
        # 如果解析失败，返回原始响应
        return {"raw_response": response}
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


class MockLLMClient:
    """
    模拟 LLM 客户端
    
    用于测试环境，返回模拟响应。
    """
    
    def __init__(self):
        """初始化模拟客户端"""
        self.model = "mock-model"
    
    async def generate(self, messages: List[ChatMessage], **kwargs) -> str:
        """
        模拟生成文本
        
        参数:
            messages: 消息列表
            **kwargs: 其他参数
        
        返回:
            模拟的文本
        """
        # 获取最后一条用户消息
        user_message = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_message = msg.content
                break
        
        # 生成模拟响应
        if "daemon" in user_message.lower():
            return "Docker daemon 正在运行。如果您遇到连接问题，请检查 DOCKER_HOST 环境变量。"
        elif "container" in user_message.lower():
            return "容器状态正常。建议检查容器日志以获取更多信息。"
        else:
            return f"收到您的问题：{user_message}。我将为您查找相关信息。"
    
    async def structured_output(self, schema: Dict, messages: List[ChatMessage]) -> Dict:
        """
        模拟结构化输出
        
        参数:
            schema: JSON Schema
            messages: 消息列表
        
        返回:
            模拟的结构化数据
        """
        user_message = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_message = msg.content
                break
        
        # 根据 schema 返回模拟数据
        if "intent" in schema.get("properties", {}):
            # 意图分类
            if "daemon" in user_message.lower() or "docker" in user_message.lower():
                return {"intent": "troubleshoot", "confidence": 0.9, "missing_information": []}
            else:
                return {"intent": "general_qa", "confidence": 0.7, "missing_information": []}
        
        return {}
    
    async def close(self):
        """关闭客户端"""
        pass


def get_llm_client(use_mock: bool = False) -> LLMClient:
    """
    获取 LLM 客户端实例
    
    参数:
        use_mock: 是否使用模拟客户端
    
    返回:
        LLM 客户端实例
    """
    if use_mock:
        return MockLLMClient()
    return LLMClient()
