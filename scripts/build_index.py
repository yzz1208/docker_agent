"""
构建索引脚本

这个脚本负责将文档块写入数据库并生成向量嵌入。
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.embeddings import get_embedding_model
from src.db.session import init_db, get_db_context
from src.db.repositories.document_repository import DocumentRepository


def build_index(
    chunks_file: str = "data/processed/chunks.jsonl",
    use_mock: bool = True
):
    """
    构建索引
    
    参数:
        chunks_file: chunks 文件路径
        use_mock: 是否使用模拟嵌入模型
    """
    chunks_path = Path(chunks_file)
    
    # 检查文件
    if not chunks_path.exists():
        print(f"错误: chunks 文件不存在: {chunks_file}")
        print("请先运行 build_documents.py 生成 chunks")
        sys.exit(1)
    
    print("开始构建索引...")
    
    # 1. 初始化数据库
    print("1. 初始化数据库...")
    init_db()
    
    # 2. 加载 chunks
    print("2. 加载 chunks...")
    chunks = []
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    print(f"   加载了 {len(chunks)} 个 chunks")
    
    # 3. 生成嵌入
    print("3. 生成嵌入向量...")
    embedding_model = get_embedding_model(use_mock=use_mock)
    
    # 批量生成嵌入
    texts = [chunk['content'] for chunk in chunks]
    embeddings = embedding_model.embed_texts(texts, batch_size=32)
    print(f"   生成了 {len(embeddings)} 个嵌入向量")
    
    # 4. 写入数据库
    print("4. 写入数据库...")
    with get_db_context() as db:
        repo = DocumentRepository(db)
        
        # 准备数据
        chunks_with_embeddings = []
        for i, chunk in enumerate(chunks):
            chunk_data = {
                **chunk,
                'embedding': embeddings[i]
            }
            chunks_with_embeddings.append(chunk_data)
        
        # 批量插入
        inserted = repo.bulk_insert(chunks_with_embeddings)
        print(f"   插入了 {inserted} 条记录")
    
    print("\n索引构建完成!")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="构建文档索引")
    parser.add_argument("--chunks-file", default="data/processed/chunks.jsonl", help="chunks 文件路径")
    parser.add_argument("--use-mock", action="store_true", help="使用模拟嵌入模型")
    
    args = parser.parse_args()
    build_index(args.chunks_file, args.use_mock)
