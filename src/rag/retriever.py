"""
检索器

这个模块负责从向量数据库中检索相关文档。
支持向量检索和关键词检索。

检索模式：
1. V1: 纯向量检索
2. V2: 混合检索（向量 + 关键词）
3. V3: 混合检索 + 重排序
"""

from typing import List, Dict, Optional
from .embeddings import get_embedding_model, EmbeddingModel


class Retriever:
    """
    检索器类
    
    负责从知识库中检索相关文档。
    """
    
    def __init__(
        self, 
        embedding_model: Optional[EmbeddingModel] = None,
        top_k: int = 10
    ):
        """
        初始化检索器
        
        参数:
            embedding_model: 嵌入模型
            top_k: 返回的文档数量
        """
        self.embedding_model = embedding_model or get_embedding_model(use_mock=True)
        self.top_k = top_k
        self.documents = []  # 存储文档列表
    
    def load_documents(self, documents: List[Dict]):
        """
        加载文档列表
        
        参数:
            documents: 文档列表，每个文档包含 'content' 字段
        """
        self.documents = documents
        print(f"加载了 {len(documents)} 个文档")
    
    def retrieve(self, query: str, search_type: str = "vector") -> List[Dict]:
        """
        检索相关文档
        
        参数:
            query: 用户查询
            search_type: 检索类型
                - "vector": 纯向量检索（默认）
                - "keyword": 关键词检索
        
        返回:
            检索到的文档列表
        
        示例:
            retriever = Retriever(embedding_model)
            retriever.load_documents(docs)
            results = retriever.retrieve("Docker daemon 无法连接")
        """
        if not self.documents:
            raise RuntimeError("请先加载文档")
        
        if search_type == "vector":
            return self._vector_search(query)
        elif search_type == "keyword":
            return self._keyword_search(query)
        else:
            raise ValueError(f"不支持的检索类型: {search_type}")
    
    def _vector_search(self, query: str) -> List[Dict]:
        """
        向量检索
        
        使用嵌入模型将查询转换为向量，
        然后与文档向量进行相似度计算。
        
        参数:
            query: 用户查询
        
        返回:
            检索到的文档列表
        """
        # 生成查询向量
        query_embedding = self.embedding_model.embed_text(query)
        
        # 计算相似度
        results = []
        for doc in self.documents:
            if 'embedding' in doc:
                # 计算余弦相似度
                similarity = self._cosine_similarity(query_embedding, doc['embedding'])
                results.append({
                    **doc,
                    'similarity': similarity
                })
        
        # 按相似度排序
        results.sort(key=lambda x: x['similarity'], reverse=True)
        
        # 返回 top_k
        return results[:self.top_k]
    
    def _keyword_search(self, query: str) -> List[Dict]:
        """
        关键词检索
        
        使用关键词在文档中进行搜索。
        适合精确匹配错误代码、命令名等。
        
        参数:
            query: 用户查询
        
        返回:
            检索到的文档列表
        """
        # 提取关键词
        keywords = self._extract_keywords(query)
        
        results = []
        for doc in self.documents:
            content = doc.get('content', '').lower()
            
            # 计算关键词匹配分数
            score = 0
            for keyword in keywords:
                if keyword.lower() in content:
                    score += 1
            
            if score > 0:
                results.append({
                    **doc,
                    'keyword_score': score
                })
        
        # 按分数排序
        results.sort(key=lambda x: x['keyword_score'], reverse=True)
        
        # 返回 top_k
        return results[:self.top_k]
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算余弦相似度
        
        参数:
            vec1: 向量1
            vec2: 向量2
        
        返回:
            余弦相似度
        """
        import numpy as np
        
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def _extract_keywords(self, query: str) -> List[str]:
        """
        从查询中提取关键词
        
        提取可能的关键词用于精确匹配：
        - 错误代码（如 exit code 137）
        - 命令名（如 docker daemon）
        - 配置参数（如 DOCKER_HOST）
        
        参数:
            query: 用户查询
        
        返回:
            关键词列表
        """
        import re
        
        keywords = []
        
        # 提取错误代码
        error_codes = re.findall(r'exit code \d+|error code \w+-\d+', query, re.IGNORECASE)
        keywords.extend(error_codes)
        
        # 提取 Docker 相关关键词
        docker_keywords = re.findall(
            r'docker\s+\w+|daemon|container|volume|network|image|registry',
            query, 
            re.IGNORECASE
        )
        keywords.extend(docker_keywords)
        
        # 提取配置参数
        config_params = re.findall(r'DOCKER_\w+|[A-Z_]{3,}', query)
        keywords.extend(config_params)
        
        # 如果没有提取到关键词，使用原始查询
        if not keywords:
            keywords = [query]
        
        return keywords


class VectorRetriever:
    """
    向量检索器
    
    简化版本，只支持向量检索。
    """
    
    def __init__(self, embedding_model: Optional[EmbeddingModel] = None):
        self.embedding_model = embedding_model or get_embedding_model(use_mock=True)
        self.documents = []
    
    def load_documents(self, documents: List[Dict]):
        """加载文档"""
        self.documents = documents
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        向量检索
        
        参数:
            query: 用户查询
            top_k: 返回的文档数量
        
        返回:
            检索到的文档列表
        """
        query_embedding = self.embedding_model.embed_text(query)
        
        results = []
        for doc in self.documents:
            if 'embedding' in doc:
                similarity = self._cosine_similarity(query_embedding, doc['embedding'])
                results.append({
                    **doc,
                    'similarity': similarity
                })
        
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        import numpy as np
        
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
