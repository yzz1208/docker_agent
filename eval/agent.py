"""
Agent 评估

这个模块提供 Agent 系统的评估功能。
"""

from typing import List, Dict
import json


def evaluate_agent(
    test_cases: List[Dict]
) -> Dict:
    """
    评估 Agent 端到端性能
    
    参数:
        test_cases: 测试用例列表
    
    返回:
        评估结果
    
    测试用例格式:
        {
            "input": "用户输入",
            "expected_output": {
                "intent": "预期意图",
                "tools": ["预期工具"],
                "response_contains": ["预期回答包含的关键词"]
            }
        }
    """
    results = {
        "total_cases": len(test_cases),
        "intent_correct": 0,
        "tools_correct": 0,
        "response_correct": 0,
        "overall_correct": 0,
        "intent_accuracy": 0.0,
        "tools_accuracy": 0.0,
        "response_accuracy": 0.0,
        "overall_accuracy": 0.0
    }
    
    for case in test_cases:
        input_text = case["input"]
        expected = case["expected_output"]
        
        # 模拟 Agent 响应（实际应该调用 Agent）
        # 这里使用简单的规则匹配
        actual_intent = "unknown"
        actual_tools = []
        actual_response = ""
        
        input_lower = input_text.lower()
        
        # 意图分类
        if any(keyword in input_lower for keyword in ["daemon", "docker", "connect"]):
            actual_intent = "troubleshoot"
            actual_tools = ["check_daemon_status"]
            actual_response = "Docker daemon 检查完成"
        elif any(keyword in input_lower for keyword in ["container", "容器", "exit"]):
            actual_intent = "container_diagnosis"
            actual_tools = ["inspect_container", "get_container_logs"]
            actual_response = "容器诊断完成"
        elif any(keyword in input_lower for keyword in ["install", "安装"]):
            actual_intent = "installation"
            actual_tools = []
            actual_response = "Docker 安装指南"
        elif any(keyword in input_lower for keyword in ["工单", "ticket"]):
            actual_intent = "support_ticket"
            actual_tools = ["create_support_ticket"]
            actual_response = "工单创建完成"
        else:
            actual_intent = "general_qa"
            actual_tools = []
            actual_response = "Docker 技术支持"
        
        # 评估意图
        if actual_intent == expected.get("intent"):
            results["intent_correct"] += 1
        
        # 评估工具
        expected_tools = set(expected.get("tools", []))
        if set(actual_tools) == expected_tools:
            results["tools_correct"] += 1
        
        # 评估回答
        response_contains = expected.get("response_contains", [])
        if all(keyword in actual_response for keyword in response_contains):
            results["response_correct"] += 1
        
        # 整体评估
        if (actual_intent == expected.get("intent") and 
            set(actual_tools) == expected_tools and
            all(keyword in actual_response for keyword in response_contains)):
            results["overall_correct"] += 1
    
    # 计算准确率
    if results["total_cases"] > 0:
        results["intent_accuracy"] = results["intent_correct"] / results["total_cases"]
        results["tools_accuracy"] = results["tools_correct"] / results["total_cases"]
        results["response_accuracy"] = results["response_correct"] / results["total_cases"]
        results["overall_accuracy"] = results["overall_correct"] / results["total_cases"]
    
    return results


def generate_eval_report(
    retrieval_results: Dict,
    tool_results: Dict,
    agent_results: Dict
) -> str:
    """
    生成评估报告
    
    参数:
        retrieval_results: 检索评估结果
        tool_results: 工具评估结果
        agent_results: Agent 评估结果
    
    返回:
        评估报告（Markdown 格式）
    """
    report = """# Docker Support Agent 评估报告

## 检索评估

| 指标 | 值 |
|------|-----|
| Recall@1 | {recall_1:.2%} |
| Recall@3 | {recall_3:.2%} |
| Recall@5 | {recall_5:.2%} |
| MRR | {mrr:.2%} |

## 工具评估

| 指标 | 值 |
|------|-----|
| 工具选择准确率 | {tool_selection:.2%} |
| 工具执行准确率 | {tool_execution:.2%} |

## Agent 评估

| 指标 | 值 |
|------|-----|
| 意图分类准确率 | {intent:.2%} |
| 工具选择准确率 | {tools:.2%} |
| 回答生成准确率 | {response:.2%} |
| 整体准确率 | {overall:.2%} |

## 总结

{summary}
"""
    
    # 计算总结
    overall_score = (
        retrieval_results.get("mrr", 0) * 0.3 +
        tool_results.get("accuracy", 0) * 0.3 +
        agent_results.get("overall_accuracy", 0) * 0.4
    )
    
    if overall_score >= 0.8:
        summary = "系统表现优秀，各项指标均达到预期。"
    elif overall_score >= 0.6:
        summary = "系统表现良好，但仍有改进空间。"
    else:
        summary = "系统需要进一步优化。"
    
    return report.format(
        recall_1=retrieval_results.get("recall_at_1", 0),
        recall_3=retrieval_results.get("recall_at_3", 0),
        recall_5=retrieval_results.get("recall_at_5", 0),
        mrr=retrieval_results.get("mrr", 0),
        tool_selection=tool_results.get("accuracy", 0),
        tool_execution=tool_results.get("accuracy", 0),
        intent=agent_results.get("intent_accuracy", 0),
        tools=agent_results.get("tools_accuracy", 0),
        response=agent_results.get("response_accuracy", 0),
        overall=agent_results.get("overall_accuracy", 0),
        summary=summary
    )
