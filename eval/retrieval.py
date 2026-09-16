"""
检索评估

这个模块提供检索系统的评估功能。
"""

from typing import List, Dict
from src.rag.retriever import Retriever


def evaluate_retrieval(
    retriever: Retriever,
    test_cases: List[Dict]
) -> Dict:
    """
    评估检索系统
    
    参数:
        retriever: 检索器实例
        test_cases: 测试用例列表
    
    返回:
        评估结果
    
    测试用例格式:
        {
            "query": "用户查询",
            "relevant_document": "相关文档 ID",
            "relevant_section": "相关章节"
        }
    """
    results = {
        "total_cases": len(test_cases),
        "recall_at_1": 0,
        "recall_at_3": 0,
        "recall_at_5": 0,
        "mrr": 0
    }
    
    for case in test_cases:
        query = case["query"]
        relevant_doc = case["relevant_document"]
        
        # 执行检索
        retrieved_docs = retriever.retrieve(query, search_type="hybrid")
        
        # 计算指标
        retrieved_doc_ids = [doc["document_id"] for doc in retrieved_docs]
        
        # Recall@K
        if relevant_doc in retrieved_doc_ids[:1]:
            results["recall_at_1"] += 1
        if relevant_doc in retrieved_doc_ids[:3]:
            results["recall_at_3"] += 1
        if relevant_doc in retrieved_doc_ids[:5]:
            results["recall_at_5"] += 1
        
        # MRR (Mean Reciprocal Rank)
        if relevant_doc in retrieved_doc_ids:
            rank = retrieved_doc_ids.index(relevant_doc) + 1
            results["mrr"] += 1 / rank
    
    # 计算平均值
    n = len(test_cases)
    if n > 0:
        results["recall_at_1"] /= n
        results["recall_at_3"] /= n
        results["recall_at_5"] /= n
        results["mrr"] /= n
    
    return results
