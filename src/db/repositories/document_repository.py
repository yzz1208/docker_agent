"""
文档仓库

这个模块提供文档块的数据访问层。
封装了对 document_chunks 表的所有数据库操作。

主要功能：
1. 批量插入文档块
2. 根据向量相似度检索文档块
3. 根据关键词检索文档块
4. 统计文档块数量
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from pgvector.sqlalchemy import Vector

from ..models import DocumentChunk


class DocumentRepository:
    """
    文档仓库类
    
    提供文档块的 CRUD 操作和向量检索功能。
    """
    
    def __init__(self, db: Session):
        """
        初始化文档仓库
        
        参数:
            db: 数据库会话
        """
        self.db = db
    
    def bulk_insert(self, chunks: List[dict]) -> int:
        """
        批量插入文档块
        
        参数:
            chunks: 文档块列表，每个块是一个字典
        
        返回:
            插入的记录数
        
        示例:
            chunks = [
                {
                    "chunk_id": "chunk_001",
                    "document_id": "doc_001",
                    "title": "Docker Daemon",
                    "section_path": ["Daemon", "Troubleshooting"],
                    "content": "...",
                    "token_count": 320,
                    "embedding": [0.1, 0.2, ...]  # 1024 维向量
                }
            ]
            repo.bulk_insert(chunks)
        """
        # 创建文档块对象列表
        chunk_objects = []
        for chunk_data in chunks:
            chunk = DocumentChunk(
                chunk_id=chunk_data["chunk_id"],
                document_id=chunk_data["document_id"],
                title=chunk_data["title"],
                section_path=chunk_data["section_path"],
                content=chunk_data["content"],
                source_url=chunk_data.get("source_url"),
                file_path=chunk_data.get("file_path"),
                token_count=chunk_data["token_count"],
                embedding=chunk_data.get("embedding")
            )
            chunk_objects.append(chunk)
        
        # 批量添加到会话
        self.db.bulk_save_objects(chunk_objects)
        self.db.commit()
        
        return len(chunk_objects)
    
    def search_by_vector(
        self, 
        query_embedding: List[float], 
        top_k: int = 5
    ) -> List[dict]:
        """
        根据向量相似度检索文档块
        
        使用 pgvector 的余弦相似度进行检索。
        
        参数:
            query_embedding: 查询向量（1024 维）
            top_k: 返回的最相似文档块数量
        
        返回:
            文档块列表，按相似度降序排列
        
        示例:
            embedding = [0.1, 0.2, ...]  # 查询的向量
            results = repo.search_by_vector(embedding, top_k=5)
        """
        # 使用 pgvector 的余弦距离运算符 <=> 进行检索
        # 1 - cosine_distance = cosine_similarity
        query = text("""
            SELECT 
                chunk_id,
                document_id,
                title,
                section_path,
                content,
                source_url,
                file_path,
                token_count,
                1 - (embedding <=> :query_embedding) as similarity
            FROM document_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> :query_embedding
            LIMIT :top_k
        """)
        
        result = self.db.execute(
            query,
            {"query_embedding": str(query_embedding), "top_k": top_k}
        )
        
        # 将结果转换为字典列表
        chunks = []
        for row in result:
            chunks.append({
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "title": row.title,
                "section_path": row.section_path,
                "content": row.content,
                "source_url": row.source_url,
                "file_path": row.file_path,
                "token_count": row.token_count,
                "similarity": row.similarity
            })
        
        return chunks
    
    def search_by_keyword(self, keyword: str, top_k: int = 10) -> List[dict]:
        """
        根据关键词检索文档块
        
        使用 PostgreSQL 的全文检索功能。
        
        参数:
            keyword: 搜索关键词
            top_k: 返回的结果数量
        
        返回:
            包含关键词的文档块列表
        
        示例:
            results = repo.search_by_keyword("docker daemon", top_k=10)
        """
        # 使用 ILIKE 进行模糊匹配
        # 实际项目中应该使用 PostgreSQL 的全文检索功能（ts_vector, ts_query）
        query = text("""
            SELECT 
                chunk_id,
                document_id,
                title,
                section_path,
                content,
                source_url,
                file_path,
                token_count
            FROM document_chunks
            WHERE content ILIKE :keyword
            LIMIT :top_k
        """)
        
        result = self.db.execute(
            query,
            {"keyword": f"%{keyword}%", "top_k": top_k}
        )
        
        chunks = []
        for row in result:
            chunks.append({
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "title": row.title,
                "section_path": row.section_path,
                "content": row.content,
                "source_url": row.source_url,
                "file_path": row.file_path,
                "token_count": row.token_count
            })
        
        return chunks
    
    def count(self) -> int:
        """
        统计文档块总数
        
        返回:
            文档块的总数量
        """
        return self.db.query(DocumentChunk).count()
    
    def get_by_chunk_id(self, chunk_id: str) -> Optional[DocumentChunk]:
        """
        根据 chunk_id 获取文档块
        
        参数:
            chunk_id: 文档块的唯一标识符
        
        返回:
            文档块对象，如果不存在则返回 None
        """
        return self.db.query(DocumentChunk).filter(
            DocumentChunk.chunk_id == chunk_id
        ).first()
