"""
运行评估脚本

这个脚本负责运行各种评估测试。
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.retrieval import evaluate_retrieval
from src.rag.retriever import Retriever
from src.rag.embeddings import get_embedding_model
from src.db.repositories.document_repository import DocumentRepository
from src.db.session import SessionLocal


def run_retrieval_eval():
    """
    运行检索评估
    """
    print("运行检索评估...")
    
    # 加载测试用例
    test_cases = []
    with open("data/eval/retrieval_eval.jsonl", 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                test_cases.append(json.loads(line))
    
    print(f"加载了 {len(test_cases)} 个测试用例")
    
    # 创建检索器
    db = SessionLocal()
    repo = DocumentRepository(db)
    embedding_model = get_embedding_model(use_mock=True)
    retriever = Retriever(embedding_model)
    
    # 从数据库加载文档
    print("从数据库加载文档...")
    from src.db.models import DocumentChunk
    chunks = db.query(DocumentChunk).all()
    documents = []
    for chunk in chunks:
        documents.append({
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "title": chunk.title,
            "section_path": chunk.section_path,
            "content": chunk.content,
            "source_url": chunk.source_url,
            "file_path": chunk.file_path,
            "token_count": chunk.token_count,
            "embedding": chunk.embedding
        })
    retriever.load_documents(documents)
    print(f"加载了 {len(documents)} 个文档")
    
    # 运行评估
    results = evaluate_retrieval(retriever, test_cases)
    
    print("\n检索评估结果:")
    print(f"- Recall@1: {results['recall_at_1']:.2%}")
    print(f"- Recall@3: {results['recall_at_3']:.2%}")
    print(f"- Recall@5: {results['recall_at_5']:.2%}")
    print(f"- MRR: {results['mrr']:.2%}")
    
    return results


def run_tool_eval():
    """
    运行工具评估
    """
    print("\n运行工具评估...")
    
    # 加载测试用例
    test_cases = []
    with open("data/eval/tool_eval.jsonl", 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                test_cases.append(json.loads(line))
    
    print(f"加载了 {len(test_cases)} 个测试用例")
    
    # 运行工具选择评估
    from eval.tools import evaluate_tool_selection
    selection_results = evaluate_tool_selection(test_cases)
    
    print("\n工具选择评估结果:")
    print(f"- 正确选择: {selection_results['correct_selections']}/{selection_results['total_cases']}")
    print(f"- 准确率: {selection_results['accuracy']:.2%}")
    
    return selection_results


def run_agent_eval():
    """
    运行 Agent 评估
    """
    print("\n运行 Agent 评估...")
    
    # 加载测试用例
    test_cases = []
    with open("data/eval/agent_eval.jsonl", 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                test_cases.append(json.loads(line))
    
    print(f"加载了 {len(test_cases)} 个测试用例")
    
    # 运行 Agent 评估
    from eval.agent import evaluate_agent
    agent_results = evaluate_agent(test_cases)
    
    print("\nAgent 评估结果:")
    print(f"- 意图分类准确率: {agent_results['intent_accuracy']:.2%}")
    print(f"- 工具选择准确率: {agent_results['tools_accuracy']:.2%}")
    print(f"- 回答生成准确率: {agent_results['response_accuracy']:.2%}")
    print(f"- 整体准确率: {agent_results['overall_accuracy']:.2%}")
    
    return agent_results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="运行评估测试")
    parser.add_argument(
        "--eval-type",
        choices=["retrieval", "tool", "agent", "all"],
        default="all",
        help="评估类型"
    )
    
    args = parser.parse_args()
    
    if args.eval_type in ["retrieval", "all"]:
        run_retrieval_eval()
    
    if args.eval_type in ["tool", "all"]:
        run_tool_eval()
    
    if args.eval_type in ["agent", "all"]:
        run_agent_eval()
    
    print("\n评估完成!")
