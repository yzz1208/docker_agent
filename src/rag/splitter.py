"""
文档分割器

这个模块负责将文档分割成小块（chunks）。
用于后续的向量化和检索。

分割策略：
1. 基于标题分割
2. 控制每个 chunk 的大小（token 数量）
3. 保持上下文的连贯性
"""

from typing import List, Dict
import re


class DocumentSplitter:
    """
    文档分割器类
    
    负责将文档分割成适合向量化的小块。
    """
    
    def __init__(
        self, 
        max_tokens: int = 512, 
        min_tokens: int = 100,
        overlap_tokens: int = 50
    ):
        """
        初始化分割器
        
        参数:
            max_tokens: 每个 chunk 的最大 token 数
            min_tokens: 每个 chunk 的最小 token 数
            overlap_tokens: 重叠的 token 数（用于保持上下文）
        """
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.overlap_tokens = overlap_tokens
    
    def split_document(self, doc: Dict) -> List[Dict]:
        """
        分割单个文档
        
        参数:
            doc: 文档字典，包含：
                - document_id: 文档 ID
                - title: 文档标题
                - content: 文档内容
                - sections: 章节列表（可选）
        
        返回:
            chunk 列表
        """
        chunks = []
        
        # 如果有章节信息，按章节分割
        if 'sections' in doc and doc['sections']:
            chunks = self._split_by_sections(doc)
        else:
            # 否则按段落分割
            chunks = self._split_by_paragraphs(doc)
        
        # 为每个 chunk 添加元数据
        for i, chunk in enumerate(chunks):
            chunk['chunk_id'] = f"{doc['document_id']}__{i:03d}"
            chunk['document_id'] = doc['document_id']
            chunk['source_url'] = doc.get('url', '')
            chunk['file_path'] = doc.get('file_path', '')
        
        return chunks
    
    def _split_by_sections(self, doc: Dict) -> List[Dict]:
        """
        按章节分割文档
        
        参数:
            doc: 包含章节信息的文档
        
        返回:
            chunk 列表
        """
        chunks = []
        
        for section in doc['sections']:
            content = section['content']
            
            # 如果章节内容为空，跳过
            if not content.strip():
                continue
            
            # 计算 token 数量
            token_count = self._count_tokens(content)
            
            # 如果章节太小，合并到下一个
            if token_count < self.min_tokens:
                # 标记为需要合并
                section['_needs_merge'] = True
                continue
            
            # 如果章节太大，需要进一步分割
            if token_count > self.max_tokens:
                sub_chunks = self._split_large_section(section)
                chunks.extend(sub_chunks)
            else:
                chunks.append({
                    'title': doc['title'],
                    'section_path': section.get('section_path', []),
                    'content': content,
                    'token_count': token_count
                })
        
        # 合并太小的章节
        chunks = self._merge_small_chunks(chunks, doc)
        
        return chunks
    
    def _split_by_paragraphs(self, doc: Dict) -> List[Dict]:
        """
        按段落分割文档
        
        参数:
            doc: 文档字典
        
        返回:
            chunk 列表
        """
        content = doc['content']
        paragraphs = content.split('\n\n')
        
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            paragraph_tokens = self._count_tokens(paragraph)
            
            # 如果当前 chunk 加上新段落会超过最大限制
            if current_tokens + paragraph_tokens > self.max_tokens:
                # 保存当前 chunk
                if current_chunk:
                    chunk_content = '\n\n'.join(current_chunk)
                    chunks.append({
                        'title': doc['title'],
                        'section_path': [],
                        'content': chunk_content,
                        'token_count': current_tokens
                    })
                
                # 开始新 chunk
                current_chunk = [paragraph]
                current_tokens = paragraph_tokens
            else:
                current_chunk.append(paragraph)
                current_tokens += paragraph_tokens
        
        # 保存最后一个 chunk
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            chunks.append({
                'title': doc['title'],
                'section_path': [],
                'content': chunk_content,
                'token_count': current_tokens
            })
        
        return chunks
    
    def _split_large_section(self, section: Dict) -> List[Dict]:
        """
        分割过大的章节
        
        参数:
            section: 章节信息
        
        返回:
            分割后的 chunk 列表
        """
        content = section['content']
        paragraphs = content.split('\n\n')
        
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            paragraph_tokens = self._count_tokens(paragraph)
            
            if current_tokens + paragraph_tokens > self.max_tokens:
                # 保存当前 chunk
                if current_chunk:
                    chunk_content = '\n\n'.join(current_chunk)
                    chunks.append({
                        'title': section.get('title', ''),
                        'section_path': section.get('section_path', []),
                        'content': chunk_content,
                        'token_count': current_tokens
                    })
                
                # 开始新 chunk（带重叠）
                if self.overlap_tokens > 0 and current_chunk:
                    # 保留最后一个段落作为重叠
                    overlap_content = current_chunk[-1]
                    current_chunk = [overlap_content, paragraph]
                    current_tokens = self._count_tokens(overlap_content) + paragraph_tokens
                else:
                    current_chunk = [paragraph]
                    current_tokens = paragraph_tokens
            else:
                current_chunk.append(paragraph)
                current_tokens += paragraph_tokens
        
        # 保存最后一个 chunk
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            chunks.append({
                'title': section.get('title', ''),
                'section_path': section.get('section_path', []),
                'content': chunk_content,
                'token_count': current_tokens
            })
        
        return chunks
    
    def _merge_small_chunks(self, chunks: List[Dict], doc: Dict) -> List[Dict]:
        """
        合并太小的 chunks
        
        参数:
            chunks: chunk 列表
            doc: 原始文档
        
        返回:
            合并后的 chunk 列表
        """
        if not chunks:
            return chunks
        
        merged = []
        current_chunk = chunks[0]
        
        for i in range(1, len(chunks)):
            next_chunk = chunks[i]
            
            # 如果当前 chunk 太小，尝试合并
            if current_chunk['token_count'] < self.min_tokens:
                # 合并内容
                merged_content = current_chunk['content'] + '\n\n' + next_chunk['content']
                merged_tokens = current_chunk['token_count'] + next_chunk['token_count']
                
                # 如果合并后不超过最大限制
                if merged_tokens <= self.max_tokens:
                    current_chunk = {
                        'title': current_chunk['title'],
                        'section_path': current_chunk['section_path'],
                        'content': merged_content,
                        'token_count': merged_tokens
                    }
                    continue
            
            # 保存当前 chunk
            merged.append(current_chunk)
            current_chunk = next_chunk
        
        # 保存最后一个 chunk
        merged.append(current_chunk)
        
        return merged
    
    def _count_tokens(self, text: str) -> int:
        """
        估算 token 数量
        
        简单的 token 计数方法：
        - 英文：按空格分词
        - 中文：按字符计数
        
        参数:
            text: 文本内容
        
        返回:
            估算的 token 数量
        """
        # 简单的估算方法
        # 实际项目中应该使用 tiktoken 等库
        words = text.split()
        # 中文字符每个算一个 token
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        return len(words) + chinese_chars


def split_documents(documents: List[Dict]) -> List[Dict]:
    """
    批量分割文档
    
    参数:
        documents: 文档列表
    
    返回:
        chunk 列表
    """
    splitter = DocumentSplitter()
    all_chunks = []
    
    for doc in documents:
        chunks = splitter.split_document(doc)
        all_chunks.extend(chunks)
    
    return all_chunks
