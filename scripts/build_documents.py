"""
构建文档脚本

这个脚本负责处理 Docker 文档：
1. 加载文档
2. 清洗文档
3. 分割文档
4. 保存为 JSONL 格式
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.loader import DocumentLoader
from src.rag.cleaner import MarkdownCleaner
from src.rag.splitter import DocumentSplitter


def build_documents(
    input_dir: str = "data/raw/docker-docs",
    output_dir: str = "data/processed"
):
    """
    构建文档
    
    参数:
        input_dir: 输入目录
        output_dir: 输出目录
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    # 检查输入目录
    if not input_path.exists():
        print(f"错误: 输入目录不存在: {input_dir}")
        print("请先运行 download_docs.py 下载文档")
        sys.exit(1)
    
    # 创建输出目录
    output_path.mkdir(parents=True, exist_ok=True)
    
    print("开始处理文档...")
    
    # 1. 加载文档
    print("1. 加载文档...")
    loader = DocumentLoader(input_dir)
    documents = loader.load_directory()
    print(f"   加载了 {len(documents)} 个文档")
    
    # 2. 清洗文档
    print("2. 清洗文档...")
    cleaner = MarkdownCleaner()
    cleaned_docs = []
    for doc in documents:
        cleaned_content = cleaner.clean(doc['content'])
        sections = cleaner.extract_sections(cleaned_content)
        cleaned_doc = {
            **doc,
            'content': cleaned_content,
            'sections': sections
        }
        cleaned_docs.append(cleaned_doc)
    print(f"   清洗了 {len(cleaned_docs)} 个文档")
    
    # 3. 分割文档
    print("3. 分割文档...")
    splitter = DocumentSplitter(max_tokens=512, min_tokens=100)
    all_chunks = []
    for doc in cleaned_docs:
        chunks = splitter.split_document(doc)
        all_chunks.extend(chunks)
    print(f"   生成了 {len(all_chunks)} 个 chunks")
    
    # 4. 保存文档
    print("4. 保存文档...")
    
    # 保存 documents.jsonl
    docs_file = output_path / "documents.jsonl"
    with open(docs_file, 'w', encoding='utf-8') as f:
        for doc in cleaned_docs:
            # 移除 sections 字段（太大）
            doc_to_save = {k: v for k, v in doc.items() if k != 'sections'}
            f.write(json.dumps(doc_to_save, ensure_ascii=False) + '\n')
    print(f"   保存了 {docs_file}")
    
    # 保存 chunks.jsonl
    chunks_file = output_path / "chunks.jsonl"
    with open(chunks_file, 'w', encoding='utf-8') as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
    print(f"   保存了 {chunks_file}")
    
    # 统计信息
    print("\n处理完成!")
    print(f"- 文档数量: {len(cleaned_docs)}")
    print(f"- Chunk 数量: {len(all_chunks)}")
    
    # 计算平均 chunk 大小
    if all_chunks:
        avg_tokens = sum(c.get('token_count', 0) for c in all_chunks) / len(all_chunks)
        print(f"- 平均 chunk 大小: {avg_tokens:.0f} tokens")


if __name__ == "__main__":
    build_documents()
