"""
数据模式定义

这个模块定义了项目中使用的 Pydantic 数据模型。
用于数据验证和序列化。

主要模式：
1. 意图分类结果
2. 诊断结果
3. 工具调用参数
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """
    意图分类结果
    
    用于 LLM 的结构化输出，识别用户意图。
    
    属性:
        intent: 意图类型
        confidence: 置信度
        missing_information: 缺失的信息列表
    """
    intent: Literal[
        "general_qa",
        "installation",
        "troubleshoot",
        "container_diagnosis",
        "support_ticket",
        "unknown"
    ] = Field(description="用户意图类型")
    
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="分类置信度"
    )
    
    missing_information: List[str] = Field(
        default_factory=list,
        description="缺失的信息列表"
    )


class DiagnosisResult(BaseModel):
    """
    诊断结果
    
    用于 LLM 的结构化输出，提供诊断信息。
    
    属性:
        summary: 诊断摘要
        possible_causes: 可能的原因
        recommended_actions: 建议的操作
        need_more_info: 是否需要更多信息
    """
    summary: str = Field(description="诊断摘要")
    
    possible_causes: List[str] = Field(
        default_factory=list,
        description="可能的原因列表"
    )
    
    recommended_actions: List[str] = Field(
        default_factory=list,
        description="建议的操作列表"
    )
    
    need_more_info: bool = Field(
        default=False,
        description="是否需要更多信息"
    )


class ToolCall(BaseModel):
    """
    工具调用
    
    表示一个工具调用请求。
    
    属性:
        tool: 工具名称
        args: 工具参数
    """
    tool: str = Field(description="工具名称")
    args: dict = Field(default_factory=dict, description="工具参数")


class ToolResult(BaseModel):
    """
    工具执行结果
    
    表示工具执行的结果。
    
    属性:
        tool: 工具名称
        success: 是否成功
        result: 执行结果
        error: 错误信息
    """
    tool: str = Field(description="工具名称")
    success: bool = Field(description="是否成功")
    result: Optional[dict] = Field(default=None, description="执行结果")
    error: Optional[str] = Field(default=None, description="错误信息")


class RetrievalResult(BaseModel):
    """
    检索结果
    
    表示文档检索的结果。
    
    属性:
        chunk_id: 文档块 ID
        title: 文档标题
        content: 文档内容
        similarity: 相似度分数
        source_url: 来源 URL
    """
    chunk_id: str = Field(description="文档块 ID")
    title: str = Field(description="文档标题")
    content: str = Field(description="文档内容")
    similarity: float = Field(default=0.0, description="相似度分数")
    source_url: Optional[str] = Field(default=None, description="来源 URL")


class AgentResponse(BaseModel):
    """
    Agent 响应
    
    表示 Agent 的最终响应。
    
    属性:
        response: 响应文本
        sources: 参考来源
        tool_calls: 工具调用列表
        diagnosis: 诊断信息
        intent: 意图类型
    """
    response: str = Field(description="响应文本")
    sources: List[str] = Field(default_factory=list, description="参考来源")
    tool_calls: List[str] = Field(default_factory=list, description="工具调用列表")
    diagnosis: Optional[str] = Field(default=None, description="诊断信息")
    intent: Optional[str] = Field(default=None, description="意图类型")


class ChatRequest(BaseModel):
    """
    聊天请求
    
    表示用户的聊天请求。
    
    属性:
        message: 用户消息
        conversation_id: 会话 ID
    """
    message: str = Field(description="用户消息")
    conversation_id: Optional[int] = Field(default=None, description="会话 ID")


class ChatResponse(BaseModel):
    """
    聊天响应
    
    表示 Agent 的聊天响应。
    
    属性:
        response: 响应文本
        sources: 参考来源
        tool_calls: 工具调用列表
        conversation_id: 会话 ID
    """
    response: str = Field(description="响应文本")
    sources: List[str] = Field(default_factory=list, description="参考来源")
    tool_calls: List[str] = Field(default_factory=list, description="工具调用列表")
    conversation_id: int = Field(description="会话 ID")
