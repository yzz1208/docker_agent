"""
嵌入模型

这个模块负责将文本转换为向量嵌入。
使用 sentence-transformers 库加载预训练模型。

支持的模型：
1. BAAI/bge-m3 - 多语言嵌入模型（推荐）
2. BAAI/bge-large-zh-v1.5 - 中文嵌入模型
3. 其他 sentence-transformers 兼容模型
"""

from typing import List, Optional
from sentence_transformers import SentenceTransformer
import numpy as np


class EmbeddingModel:
    """
    嵌入模型类
    
    负责将文本转换为向量嵌入。
    """
    
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        """
        初始化嵌入模型
        
        参数:
            model_name: 模型名称或路径
        
        示例:
            embedding = EmbeddingModel("BAAI/bge-m3")
        """
        self.model_name = model_name
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """
        加载模型
        
        首次加载会下载模型，后续从缓存加载。
        """
        print(f"正在加载嵌入模型: {self.model_name}")
        try:
            self.model = SentenceTransformer(self.model_name)
            print(f"模型加载完成: {self.model_name}")
            print(f"向量维度: {self.model.get_sentence_embedding_dimension()}")
        except Exception as e:
            print(f"模型加载失败: {e}")
            raise
    
    def embed_text(self, text: str) -> List[float]:
        """
        将单个文本转换为向量
        
        参数:
            text: 输入文本
        
        返回:
            向量嵌入（列表形式）
        
        示例:
            embedding_model = EmbeddingModel()
            vector = embedding_model.embed_text("Docker daemon troubleshooting")
        """
        if not self.model:
            raise RuntimeError("模型未加载")
        
        # 生成嵌入
        embedding = self.model.encode(text, normalize_embeddings=True)
        
        # 转换为列表
        return embedding.tolist()
    
    def embed_texts(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        批量将文本转换为向量
        
        参数:
            texts: 文本列表
            batch_size: 批处理大小
        
        返回:
            向量嵌入列表
        
        示例:
            texts = ["Docker daemon", "Container troubleshooting"]
            vectors = embedding_model.embed_texts(texts)
        """
        if not self.model:
            raise RuntimeError("模型未加载")
        
        # 批量生成嵌入
        embeddings = self.model.encode(
            texts, 
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True
        )
        
        # 转换为列表
        return embeddings.tolist()
    
    def get_dimension(self) -> int:
        """
        获取向量维度
        
        返回:
            向量维度
        """
        if not self.model:
            raise RuntimeError("模型未加载")
        
        return self.model.get_sentence_embedding_dimension()


class MockEmbeddingModel:
    """
    模拟嵌入模型
    
    用于测试环境，不需要下载真实模型。
    生成随机向量作为嵌入。
    """
    
    def __init__(self, dimension: int = 1024):
        """
        初始化模拟模型
        
        参数:
            dimension: 向量维度
        """
        self.dimension = dimension
        print(f"使用模拟嵌入模型，维度: {dimension}")
    
    def embed_text(self, text: str) -> List[float]:
        """
        生成随机向量
        
        参数:
            text: 输入文本（不使用）
        
        返回:
            随机向量
        """
        # 生成随机向量
        vector = np.random.randn(self.dimension).tolist()
        # 归一化
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector
    
    def embed_texts(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        批量生成随机向量
        
        参数:
            texts: 文本列表
            batch_size: 批处理大小（不使用）
        
        返回:
            随机向量列表
        """
        return [self.embed_text(text) for text in texts]
    
    def get_dimension(self) -> int:
        """
        获取向量维度
        
        返回:
            向量维度
        """
        return self.dimension


def get_embedding_model(model_name: Optional[str] = None, use_mock: bool = False) -> EmbeddingModel:
    """
    获取嵌入模型实例
    
    参数:
        model_name: 模型名称
        use_mock: 是否使用模拟模型
    
    返回:
        嵌入模型实例
    """
    if use_mock:
        return MockEmbeddingModel()
    
    if model_name is None:
        model_name = "BAAI/bge-m3"
    
    return EmbeddingModel(model_name)
