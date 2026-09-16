"""
Agent 工作流图定义

这个模块定义了 LangGraph Agent 的工作流图。
使用 LangGraph 的 StateGraph 来构建 Agent 的执行流程。

工作流程：
1. 理解查询 (understand_query)
2. 分类意图 (classify_intent)
3. 根据意图路由到不同分支
4. 检索文档 (retrieve_docs)
5. 决策工具 (decide_tool)
6. 执行工具 (execute_tool)
7. 合成回答 (synthesize_answer)
"""

from typing import Literal
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from .state import AgentState, IntentType


def understand_query(state: AgentState) -> AgentState:
    """
    理解用户查询
    
    这个节点负责理解用户查询的含义。
    在实际实现中，这里应该调用 LLM 来理解查询。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态
    """
    # TODO: 实现查询理解逻辑
    # 1. 提取关键信息
    # 2. 识别实体（容器名、错误代码等）
    # 3. 理解上下文
    
    print(f"[understand_query] 处理查询: {state['user_query']}")
    
    # 暂时直接返回，后续实现 LLM 调用
    return state


async def classify_intent(state: AgentState) -> AgentState:
    """
    分类用户意图
    
    这个节点负责将用户查询分类到不同的意图类型。
    使用 LLM 的结构化输出功能。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态，包含意图分类结果
    """
    from src.llm.client import get_llm_client, ChatMessage
    from src.schemas import IntentResult
    
    # 获取 LLM 客户端（使用真实的小米 MiMo 模型）
    llm_client = get_llm_client(use_mock=False)
    
    # 准备消息
    messages = [
        ChatMessage(
            role="system",
            content="""你是 Docker 技术支持 Agent 的意图分类器。
请根据用户查询判断意图类型：

1. general_qa - 一般知识问答
2. installation - 安装相关问题
3. troubleshoot - 故障排查
4. container_diagnosis - 容器诊断
5. support_ticket - 创建支持工单

返回 JSON 格式：
{
    "intent": "意图类型",
    "confidence": 0.0-1.0,
    "missing_information": []
}"""
        ),
        ChatMessage(
            role="user",
            content=state["user_query"]
        )
    ]
    
    # 调用 LLM 进行分类
    schema = IntentResult.model_json_schema()
    result = await llm_client.structured_output(schema, messages)
    
    # 解析结果
    intent = result.get("intent", IntentType.UNKNOWN)
    confidence = result.get("confidence", 0.5)
    missing_information = result.get("missing_information", [])
    
    # 标准化意图类型
    intent_mapping = {
        "troubleshooting": IntentType.TROUBLESHOOT,
        "troubleshoot": IntentType.TROUBLESHOOT,
        "container_diagnosis": IntentType.CONTAINER_DIAGNOSIS,
        "container diagnosis": IntentType.CONTAINER_DIAGNOSIS,
        "general_qa": IntentType.GENERAL_QA,
        "general qa": IntentType.GENERAL_QA,
        "installation": IntentType.INSTALLATION,
        "support_ticket": IntentType.SUPPORT_TICKET,
        "support ticket": IntentType.SUPPORT_TICKET,
    }
    intent = intent_mapping.get(intent.lower(), intent)
    
    print(f"[classify_intent] 意图: {intent}, 置信度: {confidence}")
    
    return {
        **state,
        "intent": intent,
        "confidence": confidence,
        "missing_information": missing_information if confidence < 0.7 else []
    }


def route_by_intent(state: AgentState) -> Literal["retrieve_docs", "check_information", "decide_tool", "clarify_user"]:
    """
    根据意图路由
    
    这个函数根据意图类型决定下一步执行哪个节点。
    
    参数:
        state: 当前状态
    
    返回:
        下一个节点的名称
    """
    intent = state.get("intent")
    
    if intent == IntentType.GENERAL_QA:
        return "retrieve_docs"
    elif intent in [IntentType.TROUBLESHOOT, IntentType.CONTAINER_DIAGNOSIS]:
        return "check_information"
    elif intent == IntentType.SUPPORT_TICKET:
        return "decide_tool"
    else:
        return "clarify_user"


def check_information(state: AgentState) -> AgentState:
    """
    检查信息完整性
    
    这个节点检查是否有足够的信息来进行诊断。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态
    """
    # TODO: 实现信息检查逻辑
    # 1. 检查环境信息
    # 2. 检查错误信息
    # 3. 确定是否需要更多信息
    
    print("[check_information] 检查信息完整性")
    
    # 模拟检查结果
    has_sufficient_info = len(state.get("missing_information", [])) == 0
    
    return {
        **state,
        "missing_information": [] if has_sufficient_info else ["请提供 Docker 版本和操作系统信息"]
    }


def retrieve_docs(state: AgentState) -> AgentState:
    """
    检索相关文档
    
    这个节点从知识库中检索与用户查询相关的文档。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态，包含检索到的文档
    """
    # TODO: 实现文档检索逻辑
    # 1. 生成查询向量
    # 2. 执行向量检索
    # 3. 执行关键词检索
    # 4. 合并和重排序结果
    
    print("[retrieve_docs] 检索相关文档")
    
    # 模拟检索结果
    retrieved_docs = [
        {
            "chunk_id": "docker_engine_daemon_troubleshoot__unable_connect__001",
            "title": "Troubleshooting the Docker daemon",
            "content": "Cannot connect to the Docker daemon...",
            "similarity": 0.95
        }
    ]
    
    return {
        **state,
        "retrieved_docs": retrieved_docs
    }


async def decide_tool(state: AgentState) -> AgentState:
    """
    决策使用哪个工具
    
    这个节点根据用户查询和上下文决定使用哪个工具。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态，包含工具调用决策
    """
    from src.llm.client import get_llm_client, ChatMessage
    from src.tools.manager import get_tool_manager
    
    print("[decide_tool] 决策工具调用")
    
    # 获取工具管理器
    tool_manager = get_tool_manager()
    available_tools = tool_manager.get_available_tools()
    
    # 获取 LLM 客户端
    llm_client = get_llm_client(use_mock=True)
    
    # 准备工具描述
    tool_descriptions = []
    for tool_name in available_tools:
        desc = tool_manager.get_tool_description(tool_name)
        tool_descriptions.append(f"- {tool_name}: {desc}")
    
    tools_text = "\n".join(tool_descriptions)
    
    # 准备消息
    messages = [
        ChatMessage(
            role="system",
            content=f"""你是 Docker 技术支持 Agent 的工具决策器。
根据用户查询和上下文，决定需要调用哪些工具。

可用工具：
{tools_text}

返回 JSON 格式：
{{
    "tools": [
        {{"tool": "工具名称", "args": {{}}}}
    ]
}}"""
        ),
        ChatMessage(
            role="user",
            content=f"""用户查询：{state['user_query']}

意图：{state.get('intent', '未知')}

请决定需要调用哪些工具。"""
        )
    ]
    
    # 调用 LLM 进行工具决策
    result = await llm_client.generate(messages)
    
    # 解析工具调用（简单解析）
    tool_calls = []
    
    # 根据意图和查询内容决定工具
    intent = state.get("intent", "")
    query = state["user_query"].lower()
    
    if intent == "troubleshoot" or "daemon" in query:
        tool_calls.append({"tool": "check_daemon_status", "args": {}})
        tool_calls.append({"tool": "get_docker_info", "args": {}})
    elif intent == "container_diagnosis" or "container" in query or "容器" in query:
        tool_calls.append({"tool": "list_containers", "args": {"all": True}})
        if "api-server" in query or "api_server" in query:
            tool_calls.append({"tool": "inspect_container", "args": {"container_name": "api-server"}})
            tool_calls.append({"tool": "get_container_logs", "args": {"container_name": "api-server", "tail": 100}})
    elif "disk" in query or "磁盘" in query:
        tool_calls.append({"tool": "check_disk_usage", "args": {}})
    elif intent == "support_ticket":
        tool_calls.append({"tool": "create_support_ticket", "args": {
            "title": f"支持工单: {state['user_query'][:50]}",
            "problem": state["user_query"],
            "environment": state.get("environment", {}),
            "diagnostics": state.get("diagnosis", ""),
            "actions_taken": [],
            "logs": []
        }})
    else:
        # 默认检查 daemon 状态
        tool_calls.append({"tool": "check_daemon_status", "args": {}})
    
    print(f"  决策工具: {[tc['tool'] for tc in tool_calls]}")
    
    return {
        **state,
        "tool_calls": tool_calls
    }


async def execute_tool(state: AgentState) -> AgentState:
    """
    执行工具调用
    
    这个节点执行决策的工具调用。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态，包含工具执行结果
    """
    from src.tools.manager import get_tool_manager
    
    print("[execute_tool] 执行工具调用")
    
    # 获取工具管理器
    tool_manager = get_tool_manager()
    
    # 执行所有工具调用
    tool_results = []
    for tool_call in state.get("tool_calls", []):
        tool_name = tool_call.get("tool")
        tool_args = tool_call.get("args", {})
        
        print(f"  执行工具: {tool_name}，参数: {tool_args}")
        
        # 执行工具
        result = await tool_manager.execute_tool(tool_name, tool_args)
        tool_results.append({
            "tool": tool_name,
            "success": result.get("success", False),
            "result": result,
            "error": result.get("error") if not result.get("success") else None
        })
    
    print(f"  工具执行完成，共 {len(tool_results)} 个结果")
    
    return {
        **state,
        "tool_results": tool_results
    }


async def synthesize_answer(state: AgentState) -> AgentState:
    """
    合成最终回答
    
    这个节点根据所有收集到的信息生成最终回答。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态，包含最终回答
    """
    from src.llm.client import get_llm_client, ChatMessage
    
    print("[synthesize_answer] 合成回答")
    
    # 获取 LLM 客户端（使用真实的小米 MiMo 模型）
    llm_client = get_llm_client(use_mock=False)
    
    # 准备上下文信息
    context_parts = []
    
    # 添加检索到的文档
    if state.get("retrieved_docs"):
        context_parts.append("相关文档：")
        for doc in state["retrieved_docs"][:3]:  # 只取前3个
            context_parts.append(f"- {doc.get('title', '未知')}: {doc.get('content', '')[:200]}...")
    
    # 添加工具执行结果
    if state.get("tool_results"):
        context_parts.append("\n工具检查结果：")
        for result in state["tool_results"]:
            if result.get("success"):
                context_parts.append(f"- {result['tool']}: {result.get('result', {})}")
            else:
                context_parts.append(f"- {result['tool']}: 失败 - {result.get('error', '未知错误')}")
    
    context = "\n".join(context_parts) if context_parts else "暂无额外信息"
    
    # 准备消息
    messages = [
        ChatMessage(
            role="system",
            content="""你是 Docker 技术支持 Agent。
根据用户的问题和提供的信息，生成专业、有帮助的回答。

要求：
1. 基于事实回答，不要编造信息
2. 提供具体的排查步骤
3. 引用官方文档来源
4. 如果信息不足，说明需要什么信息

回答格式：
- 先给出结论
- 然后提供详细步骤
- 最后引用来源"""
        ),
        ChatMessage(
            role="user",
            content=f"""用户问题：{state['user_query']}

{context}

请根据以上信息生成回答。"""
        )
    ]
    
    # 调用 LLM 生成回答
    final_answer = await llm_client.generate(messages)
    
    # 生成诊断信息
    diagnosis = None
    if state.get("tool_results"):
        diagnosis = "基于工具检查结果的诊断"
    
    return {
        **state,
        "diagnosis": diagnosis,
        "final_answer": final_answer,
        "messages": [{"role": "assistant", "content": final_answer}]
    }


def clarify_user(state: AgentState) -> AgentState:
    """
    向用户请求澄清
    
    当意图不明确或信息不足时，向用户请求更多信息。
    
    参数:
        state: 当前状态
    
    返回:
        更新后的状态
    """
    print("[clarify_user] 请求用户澄清")
    
    missing_info = state.get("missing_information", [])
    if missing_info:
        clarification = f"我需要更多信息来帮助您：{', '.join(missing_info)}"
    else:
        clarification = "抱歉，我不太理解您的问题。请问您是想了解 Docker 的哪方面内容？"
    
    return {
        **state,
        "final_answer": clarification,
        "messages": [{"role": "assistant", "content": clarification}]
    }


def should_continue(state: AgentState) -> Literal["continue", "end"]:
    """
    判断是否继续执行
    
    这个函数决定是否需要继续执行工具调用。
    
    参数:
        state: 当前状态
    
    返回:
        "continue" 或 "end"
    """
    # 检查是否有未完成的工具调用
    tool_calls = state.get("tool_calls", [])
    tool_results = state.get("tool_results", [])
    
    if len(tool_calls) > len(tool_results):
        return "continue"
    
    # 检查重试次数
    retry_count = state.get("retry_count", 0)
    if retry_count >= 2:
        return "end"
    
    return "end"


# 创建状态图
workflow = StateGraph(AgentState)

# 添加节点
workflow.add_node("understand_query", understand_query)
workflow.add_node("classify_intent", classify_intent)
workflow.add_node("check_information", check_information)
workflow.add_node("retrieve_docs", retrieve_docs)
workflow.add_node("decide_tool", decide_tool)
workflow.add_node("execute_tool", execute_tool)
workflow.add_node("synthesize_answer", synthesize_answer)
workflow.add_node("clarify_user", clarify_user)

# 设置入口点
workflow.set_entry_point("understand_query")

# 添加边
workflow.add_edge("understand_query", "classify_intent")
workflow.add_conditional_edges(
    "classify_intent",
    route_by_intent,
    {
        "retrieve_docs": "retrieve_docs",
        "check_information": "check_information",
        "decide_tool": "decide_tool",
        "clarify_user": "clarify_user"
    }
)
workflow.add_edge("check_information", "decide_tool")
workflow.add_edge("retrieve_docs", "synthesize_answer")
workflow.add_edge("decide_tool", "execute_tool")
workflow.add_conditional_edges(
    "execute_tool",
    should_continue,
    {
        "continue": "decide_tool",
        "end": "synthesize_answer"
    }
)
workflow.add_edge("synthesize_answer", END)
workflow.add_edge("clarify_user", END)

# 编译图
agent_graph = workflow.compile()


async def run_agent(user_query: str) -> dict:
    """
    运行 Agent
    
    这是 Agent 的主入口函数。
    
    参数:
        user_query: 用户查询
    
    返回:
        Agent 的响应，包含回答、来源和工具调用
    """
    from .state import create_initial_state
    
    # 创建初始状态
    initial_state = create_initial_state(user_query)
    
    # 运行图
    final_state = await agent_graph.ainvoke(initial_state)
    
    return {
        "response": final_state.get("final_answer", ""),
        "sources": [doc.get("title", "") for doc in final_state.get("retrieved_docs", [])],
        "tool_calls": [call.get("tool", "") for call in final_state.get("tool_calls", [])],
        "diagnosis": final_state.get("diagnosis"),
        "intent": final_state.get("intent")
    }
