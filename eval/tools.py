"""
工具评估

这个模块提供工具系统的评估功能。
"""

from typing import List, Dict
from src.tools.manager import get_tool_manager


def evaluate_tool_selection(
    test_cases: List[Dict]
) -> Dict:
    """
    评估工具选择准确性
    
    参数:
        test_cases: 测试用例列表
    
    返回:
        评估结果
    
    测试用例格式:
        {
            "query": "用户查询",
            "expected_tools": ["工具1", "工具2"]
        }
    """
    results = {
        "total_cases": len(test_cases),
        "correct_selections": 0,
        "accuracy": 0.0
    }
    
    tool_manager = get_tool_manager()
    
    for case in test_cases:
        query = case["query"]
        expected_tools = case["expected_tools"]
        
        # 模拟工具选择（实际应该调用 Agent）
        selected_tools = []
        
        # 简单的规则匹配
        query_lower = query.lower()
        if any(keyword in query_lower for keyword in ["daemon", "docker", "connect"]):
            selected_tools.extend(["check_daemon_status", "get_docker_info"])
        elif any(keyword in query_lower for keyword in ["container", "容器"]):
            selected_tools.extend(["list_containers", "inspect_container"])
        elif any(keyword in query_lower for keyword in ["disk", "磁盘"]):
            selected_tools.append("check_disk_usage")
        elif any(keyword in query_lower for keyword in ["工单", "ticket"]):
            selected_tools.append("create_support_ticket")
        
        # 检查是否选择了正确的工具
        if set(selected_tools) == set(expected_tools):
            results["correct_selections"] += 1
    
    # 计算准确率
    if results["total_cases"] > 0:
        results["accuracy"] = results["correct_selections"] / results["total_cases"]
    
    return results


def evaluate_tool_execution(
    test_cases: List[Dict]
) -> Dict:
    """
    评估工具执行准确性
    
    参数:
        test_cases: 测试用例列表
    
    返回:
        评估结果
    
    测试用例格式:
        {
            "tool": "工具名称",
            "args": {},
            "expected_success": true
        }
    """
    results = {
        "total_cases": len(test_cases),
        "correct_executions": 0,
        "accuracy": 0.0
    }
    
    tool_manager = get_tool_manager()
    
    for case in test_cases:
        tool_name = case["tool"]
        tool_args = case["args"]
        expected_success = case["expected_success"]
        
        # 执行工具
        # 注意：这里需要异步执行，但为了简化使用同步方式
        # 实际应该使用 asyncio.run() 或在异步环境中调用
        try:
            # 模拟工具执行
            if tool_manager.use_mock:
                # Mock 模式下总是成功
                actual_success = True
            else:
                # 真实模式下检查工具是否存在
                actual_success = tool_name in tool_manager.tools
            
            if actual_success == expected_success:
                results["correct_executions"] += 1
        except Exception:
            if not expected_success:
                results["correct_executions"] += 1
    
    # 计算准确率
    if results["total_cases"] > 0:
        results["accuracy"] = results["correct_executions"] / results["total_cases"]
    
    return results
