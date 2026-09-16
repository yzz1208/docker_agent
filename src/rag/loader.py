"""
文档加载器

这个模块负责加载 Docker 官方文档。
支持从本地文件系统加载 Markdown 文档。

主要功能：
1. 加载单个 Markdown 文件
2. 加载目录下的所有 Markdown 文件
3. 提取文档元数据
"""

import os
from typing import List, Dict, Optional
from pathlib import Path


class DocumentLoader:
    """
    文档加载器类
    
    负责从文件系统加载 Docker 文档。
    """
    
    def __init__(self, docs_dir: str = "data/raw/docker-docs"):
        """
        初始化文档加载器
        
        参数:
            docs_dir: 文档目录路径
        """
        self.docs_dir = Path(docs_dir)
        if not self.docs_dir.exists():
            raise FileNotFoundError(f"文档目录不存在: {docs_dir}")
    
    def load_single_file(self, file_path: str) -> Dict:
        """
        加载单个 Markdown 文件
        
        参数:
            file_path: 文件路径
        
        返回:
            文档字典，包含：
            - document_id: 文档标识符
            - source: 文档来源
            - file_path: 文件路径
            - title: 文档标题
            - url: 文档 URL
            - language: 语言
            - content: 文档内容
        
        示例:
            loader = DocumentLoader()
            doc = loader.load_single_file("content/manuals/engine/daemon/troubleshoot.md")
        """
        path = Path(file_path)
        
        # 确保文件存在
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 读取文件内容
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 生成文档标识符
        # 格式：目录结构转换为下划线连接的标识符
        relative_path = path.relative_to(self.docs_dir)
        doc_id = str(relative_path).replace('/', '_').replace('.md', '').replace('-', '_')
        
        # 提取标题（从文件名或内容中的第一个标题）
        title = self._extract_title(content, path)
        
        # 生成 URL
        url = self._generate_url(relative_path)
        
        return {
            "document_id": doc_id,
            "source": "docker_docs",
            "file_path": str(relative_path),
            "title": title,
            "url": url,
            "language": "en",
            "content": content,
            "updated_at": None
        }
    
    def load_directory(self, directory: Optional[str] = None) -> List[Dict]:
        """
        加载目录下的所有 Markdown 文件
        
        参数:
            directory: 目录路径，如果为 None 则使用默认目录
        
        返回:
            文档列表
        
        示例:
            loader = DocumentLoader()
            docs = loader.load_directory("content/manuals/engine")
        """
        target_dir = Path(directory) if directory else self.docs_dir
        
        if not target_dir.exists():
            raise FileNotFoundError(f"目录不存在: {target_dir}")
        
        documents = []
        
        # 递归遍历目录
        for md_file in target_dir.rglob("*.md"):
            try:
                doc = self.load_single_file(str(md_file))
                documents.append(doc)
            except Exception as e:
                print(f"加载文件失败 {md_file}: {e}")
        
        return documents
    
    def _extract_title(self, content: str, path: Path) -> str:
        """
        从内容中提取标题
        
        优先从内容中的第一个 H1 标题提取，
        如果没有则使用文件名。
        
        参数:
            content: 文件内容
            path: 文件路径
        
        返回:
            文档标题
        """
        # 尝试从内容中提取 H1 标题
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('# ') and not line.startswith('## '):
                # 找到 H1 标题
                return line[2:].strip()
        
        # 如果没有找到标题，使用文件名
        return path.stem.replace('-', ' ').replace('_', ' ').title()
    
    def _generate_url(self, relative_path: Path) -> str:
        """
        生成文档 URL
        
        参数:
            relative_path: 相对路径
        
        返回:
            文档 URL
        """
        # Docker Docs 的 URL 格式
        base_url = "https://docs.docker.com"
        path_str = str(relative_path).replace('.md', '').replace('_', '-')
        return f"{base_url}/{path_str}/"


def download_docker_docs(output_dir: str = "data/raw/docker-docs"):
    """
    下载 Docker 官方文档
    
    从 GitHub 仓库克隆 Docker 文档。
    
    参数:
        output_dir: 输出目录
    """
    import subprocess
    
    output_path = Path(output_dir)
    
    # 如果目录已存在，跳过下载
    if output_path.exists():
        print(f"文档目录已存在: {output_dir}")
        return
    
    # 创建输出目录
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 克隆仓库
    repo_url = "https://github.com/docker/docs.git"
    print(f"正在克隆 Docker 文档: {repo_url}")
    
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(output_path)],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"文档下载完成: {output_dir}")
    except subprocess.CalledProcessError as e:
        print(f"下载失败: {e.stderr}")
        raise


if __name__ == "__main__":
    # 测试文档加载器
    loader = DocumentLoader()
    
    # 加载所有文档
    docs = loader.load_directory()
    print(f"加载了 {len(docs)} 个文档")
    
    # 打印第一个文档的信息
    if docs:
        doc = docs[0]
        print(f"文档ID: {doc['document_id']}")
        print(f"标题: {doc['title']}")
        print(f"URL: {doc['url']}")
        print(f"内容长度: {len(doc['content'])} 字符")
