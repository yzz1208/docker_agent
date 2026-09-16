"""
重排序器

这个模块负责对检索结果进行重排序。
使用交叉编码器（Cross-Encoder）对查询-文档对进行更精确的相关性评分。

支持的模型：
1. BAAI/bge-reranker-v2-m3 - 多语言重排序模型（推荐）
2. BAAI/bge-reranker-large - 中文重排序模型
3. 其他 sentence-transformers 兼容模型
"""

from typing import List, Dict, Optional
from sentence_transformers import CrossEncoder
import numpy as np


class Reranker:
    """
    重排序器类
    
    使用交叉编码器对检索结果进行重排序。
    交叉编码器比双编码器更准确，但速度较慢。
    """
    
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        """
        初始化重排序器
        
        参数:
            model_name: 模型名称或路径
        """
        self.model_name = model_name
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """
        加载模型
        """
        print(f"正在加载重排序模型: {self.model_name}")
        try:
            self.model = CrossEncoder(self.model_name, max_length=512)
            print(f"重排序模型加载完成: {self.model_name}")
        except Exception as e:
            print(f"重排序模型加载失败: {e}")
            raise
    
    def rerank(
        self, 
        query: str, 
        documents: List[Dict], 
        top_k: int = 5
    ) -> List[Dict]:
        """
        对文档进行重排序
        
        参数:
            query: 用户查询
            documents: 文档列表，每个文档包含 'content' 字段
            top_k: 返回的文档数量
        
        返回:
            重排序后的文档列表
        
        示例:
            reranker = Reranker()
            reranked = reranker.rerank("Docker daemon", docs, top_k=5)
        """
        if not documents:
            return []
        
        if not self.model:
            raise RuntimeError("模型未加载")
        
        # 准备查询-文档对
        pairs = [(query, doc['content']) for doc in documents]
        
        # 计算相关性分数
        scores = self.model.predict(pairs)
        
        # 将分数添加到文档中
        for i, doc in enumerate(documents):
            doc['rerank_score'] = float(scores[i])
        
        # 按分数降序排序
        reranked = sorted(documents, key=lambda x: x['rerank_score'], reverse=True)
        
        # 返回 top_k
        return reranked[:top_k]


class MockReranker:
    """
    模拟重排序器
    
    用于测试环境，不需要下载真实模型。
    """
    
    def __init__(self):
        """初始化模拟重排序器"""
        print("使用模拟重排序器")
    
    def rerank(
        self, 
        query: str, 
        documents: List[Dict], 
        top_k: int = 5
    ) -> List[Dict]:
        """
        模拟重排序
        
        随机打乱文档顺序。
        
        参数:
            query: 用户查询
            documents: 文档列表
            top_k: 返回的文档数量
        
        返回:
            "重排序"后的文档列表
        """
        if not documents:
            return []
        
        # 为每个文档分配随机分数
        for doc in documents:
            doc['rerank_score'] = np.random.random()
        
        # 按分数排序
        reranked = sorted(documents, key=lambda x: x['rerank_score'], reverse=True)
        
        return reranked[:top_k]


def get_reranker(model_name: Optional[str] = None, use_mock: bool = False) -> Reranker:
    """
    获取重排序器实例
    
    参数:
        model_name: 模型名称
        use_mock: 是否使用模拟模型
    
    返回:
        重排序器实例
    """
    if use_mock:
        return MockReranker()
    
    if model_name is None:
        model_name = "BAAI/bge-reranker-v2-m3"
    
    return Reranker(model_name)
