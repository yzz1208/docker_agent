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
        if "daemon" in user_message.lower() or "docker" in user_message.lower():
            return """根据 Docker 官方文档，Docker daemon 无法连接的常见原因包括：

1. **Docker daemon 未运行**
   - 检查命令：`systemctl status docker`
   - 启动命令：`sudo systemctl start docker`

2. **DOCKER_HOST 环境变量配置错误**
   - 检查命令：`echo $DOCKER_HOST`
   - 应该为空或指向正确的 Docker socket

3. **权限问题**
   - 将用户添加到 docker 组：`sudo usermod -aG docker $USER`
   - 或使用 sudo 运行 Docker 命令

4. **Docker socket 问题**
   - 检查 socket 文件：`ls -la /var/run/docker.sock`
   - 重启 Docker 服务

参考来源：Docker Docs - Troubleshooting the Docker daemon"""
        
        elif "container" in user_message.lower() or "容器" in user_message:
            return """容器相关问题的排查步骤：

1. **检查容器状态**
   - `docker ps -a` 查看所有容器
   - `docker inspect <container_name>` 查看详细信息

2. **查看容器日志**
   - `docker logs <container_name>` 查看日志
   - `docker logs --tail 100 <container_name>` 查看最后100行

3. **常见问题**
   - Exit code 137: OOM（内存不足）
   - Exit code 1: 应用错误
   - Exit code 139: 段错误

4. **资源限制**
   - 检查内存限制：`docker inspect --format='{{.HostConfig.Memory}}' <container>`
   - 检查 CPU 限制

参考来源：Docker Docs - Container troubleshooting"""
        
        elif "install" in user_message.lower() or "安装" in user_message:
            return """Docker 安装指南：

1. **Ubuntu/Debian**
   ```bash
   sudo apt-get update
   sudo apt-get install docker.io
   sudo systemctl start docker
   sudo systemctl enable docker
   ```

2. **CentOS/RHEL**
   ```bash
   sudo yum install docker
   sudo systemctl start docker
   sudo systemctl enable docker
   ```

3. **验证安装**
   ```bash
   docker --version
   docker run hello-world
   ```

参考来源：Docker Docs - Install Docker Engine"""
        
        else:
            return f"""感谢您的提问！

我收到了您的问题："{user_message}"

作为 Docker 技术支持 Agent，我可以帮助您解决：
- Docker 安装和配置问题
- 容器管理和故障排查
- Docker daemon 连接问题
- 镜像和存储问题
- 网络配置问题

请提供更多详细信息，以便我为您提供更准确的帮助。

参考来源：Docker 官方文档"""
    
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
            if any(keyword in user_message.lower() for keyword in ["daemon", "docker", "connect", "安装"]):
                return {
                    "intent": "troubleshoot",
                    "confidence": 0.9,
                    "missing_information": []
                }
            elif any(keyword in user_message.lower() for keyword in ["容器", "container", "exit", "oom"]):
                return {
                    "intent": "container_diagnosis",
                    "confidence": 0.85,
                    "missing_information": []
                }
            elif any(keyword in user_message.lower() for keyword in ["工单", "ticket", "支持"]):
                return {
                    "intent": "support_ticket",
                    "confidence": 0.9,
                    "missing_information": []
                }
            else:
                return {
                    "intent": "general_qa",
                    "confidence": 0.7,
                    "missing_information": []
                }
        
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
