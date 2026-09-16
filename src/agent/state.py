"""
Agent 状态定义

这个模块定义了 LangGraph Agent 的状态结构。
状态是 Agent 在整个工作流中传递的数据。

状态包含：
1. 用户查询
2. 意图分类结果
3. 环境信息
4. 检索到的文档
5. 工具调用和结果
6. 诊断信息
7. 最终回答
"""

from typing import List, Optional, TypedDict, Annotated
from operator import add


class AgentState(TypedDict):
    """
    Agent 状态类
    
    这个类定义了 Agent 在整个工作流中需要维护的所有信息。
    使用 TypedDict 确保类型安全。
    
    字段说明：
    - messages: 消息历史
    - user_query: 用户当前查询
    - intent: 意图分类结果
    - confidence: 意图分类置信度
    - missing_information: 缺失的信息列表
    - environment: 环境信息
    - retrieved_docs: 检索到的文档
    - tool_calls: 工具调用列表
    - tool_results: 工具执行结果
    - diagnosis: 诊断信息
    - final_answer: 最终回答
    - retry_count: 重试次数
    """
    
    # 消息历史
    messages: Annotated[List[dict], add]
    
    # 用户当前查询
    user_query: str
    
    # 意图分类结果
    intent: Optional[str]  # general_qa, installation, troubleshoot, container_diagnosis, support_ticket
    confidence: Optional[float]
    missing_information: List[str]
    
    # 环境信息
    environment: dict  # os, docker_type, docker_version, container_name 等
    
    # 检索结果
    retrieved_docs: List[dict]
    
    # 工具调用
    tool_calls: List[dict]
    tool_results: List[dict]
    
    # 诊断信息
    diagnosis: Optional[str]
    
    # 最终回答
    final_answer: Optional[str]
    
    # 重试计数
    retry_count: int


# 意图类型常量
class IntentType:
    """意图类型常量"""
    GENERAL_QA = "general_qa"  # 一般问答
    INSTALLATION = "installation"  # 安装问题
    TROUBLESHOOT = "troubleshoot"  # 故障排查
    CONTAINER_DIAGNOSIS = "container_diagnosis"  # 容器诊断
    SUPPORT_TICKET = "support_ticket"  # 创建支持工单
    UNKNOWN = "unknown"  # 未知意图


# 工具类型常量
class ToolType:
    """工具类型常量"""
    GET_DOCKER_INFO = "get_docker_info"  # 获取 Docker 信息
    CHECK_DAEMON_STATUS = "check_daemon_status"  # 检查 daemon 状态
    LIST_CONTAINERS = "list_containers"  # 列出容器
    INSPECT_CONTAINER = "inspect_container"  # 检查容器
    GET_CONTAINER_LOGS = "get_container_logs"  # 获取容器日志
    CHECK_DISK_USAGE = "check_disk_usage"  # 检查磁盘使用
    CREATE_SUPPORT_TICKET = "create_support_ticket"  # 创建支持工单


def create_initial_state(user_query: str) -> AgentState:
    """
    创建初始状态
    
    当用户发送新消息时，创建 Agent 的初始状态。
    
    参数:
        user_query: 用户查询
    
    返回:
        AgentState: 初始状态
    
    示例:
        state = create_initial_state("Docker daemon 没有响应")
    """
    return AgentState(
        messages=[{"role": "user", "content": user_query}],
        user_query=user_query,
        intent=None,
        confidence=None,
        missing_information=[],
        environment={},
        retrieved_docs=[],
        tool_calls=[],
        tool_results=[],
        diagnosis=None,
        final_answer=None,
        retry_count=0
    )
