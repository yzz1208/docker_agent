"""
文档清洗器

这个模块负责清洗 Markdown 文档。
移除不需要的内容，保留有价值的信息。

清洗规则：
1. 移除 YAML front matter
2. 移除 Hugo shortcode
3. 移除 HTML 标签
4. 移除图片链接
5. 保留代码块
6. 保留标题结构
7. 保留列表和表格
"""

import re
from typing import Dict


class MarkdownCleaner:
    """
    Markdown 清洗器类
    
    负责清洗 Markdown 文档，移除不需要的内容。
    """
    
    def __init__(self):
        """初始化清洗器"""
        # 编译正则表达式以提高性能
        self.front_matter_pattern = re.compile(r'^---\n.*?\n---\n', re.DOTALL)
        self.shortcode_pattern = re.compile(r'\{\{<.*?>\}\}|\{\{%.*?%\}\}')
        self.html_pattern = re.compile(r'<[^>]+>')
        self.image_pattern = re.compile(r'!\[.*?\]\(.*?\)')
        self.link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        self.heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        self.code_block_pattern = re.compile(r'```[\s\S]*?```')
        self.inline_code_pattern = re.compile(r'`[^`]+`')
    
    def clean(self, content: str) -> str:
        """
        清洗 Markdown 内容
        
        参数:
            content: 原始 Markdown 内容
        
        返回:
            清洗后的 Markdown 内容
        
        示例:
            cleaner = MarkdownCleaner()
            cleaned = cleaner.clean(raw_markdown)
        """
        # 1. 移除 YAML front matter
        content = self._remove_front_matter(content)
        
        # 2. 移除 Hugo shortcode
        content = self._remove_shortcodes(content)
        
        # 3. 移除 HTML 标签
        content = self._remove_html(content)
        
        # 4. 移除图片
        content = self._remove_images(content)
        
        # 5. 清理多余空行
        content = self._clean_empty_lines(content)
        
        return content
    
    def _remove_front_matter(self, content: str) -> str:
        """
        移除 YAML front matter
        
        Markdown 文件开头的 --- 包裹的 YAML 元数据
        
        参数:
            content: 文档内容
        
        返回:
            移除 front matter 后的内容
        """
        return self.front_matter_pattern.sub('', content)
    
    def _remove_shortcodes(self, content: str) -> str:
        """
        移除 Hugo shortcode
        
        Hugo 模板语法，如 {{< note >}}、{{% warning %}} 等
        
        参数:
            content: 文档内容
        
        返回:
            移除 shortcode 后的内容
        """
        return self.shortcode_pattern.sub('', content)
    
    def _remove_html(self, content: str) -> str:
        """
        移除 HTML 标签
        
        参数:
            content: 文档内容
        
        返回:
            移除 HTML 标签后的内容
        """
        return self.html_pattern.sub('', content)
    
    def _remove_images(self, content: str) -> str:
        """
        移除图片链接
        
        参数:
            content: 文档内容
        
        返回:
            移除图片后的内容
        """
        return self.image_pattern.sub('', content)
    
    def _clean_empty_lines(self, content: str) -> str:
        """
        清理多余空行
        
        将连续的空行合并为单个空行
        
        参数:
            content: 文档内容
        
        返回:
            清理后的内容
        """
        # 将连续的空行替换为单个空行
        content = re.sub(r'\n\s*\n', '\n\n', content)
        return content.strip()
    
    def extract_sections(self, content: str) -> list:
        """
        提取文档章节
        
        根据标题层级提取文档的章节结构。
        
        参数:
            content: 文档内容
        
        返回:
            章节列表，每个章节包含：
            - level: 标题层级
            - title: 标题文本
            - content: 章节内容
        """
        sections = []
        lines = content.split('\n')
        
        current_section = None
        current_content = []
        
        for line in lines:
            # 检查是否是标题
            match = self.heading_pattern.match(line)
            if match:
                # 保存上一个章节
                if current_section:
                    current_section['content'] = '\n'.join(current_content).strip()
                    sections.append(current_section)
                
                # 开始新章节
                level = len(match.group(1))
                title = match.group(2).strip()
                
                current_section = {
                    'level': level,
                    'title': title,
                    'section_path': self._build_section_path(sections, level, title),
                    'content': ''
                }
                current_content = []
            else:
                current_content.append(line)
        
        # 保存最后一个章节
        if current_section:
            current_section['content'] = '\n'.join(current_content).strip()
            sections.append(current_section)
        
        return sections
    
    def _build_section_path(self, sections: list, level: int, title: str) -> list:
        """
        构建章节路径
        
        根据标题层级构建章节的路径。
        
        参数:
            sections: 已处理的章节列表
            level: 当前标题层级
            title: 当前标题
        
        返回:
            章节路径列表
        """
        path = []
        
        # 查找父级标题
        for section in reversed(sections):
            if section['level'] < level:
                path.insert(0, section['title'])
                if section['level'] == 1:
                    break
        
        path.append(title)
        return path


def clean_document(doc: Dict) -> Dict:
    """
    清洗单个文档
    
    参数:
        doc: 原始文档字典
    
    返回:
        清洗后的文档字典
    """
    cleaner = MarkdownCleaner()
    
    # 清洗内容
    cleaned_content = cleaner.clean(doc['content'])
    
    # 提取章节
    sections = cleaner.extract_sections(cleaned_content)
    
    return {
        **doc,
        'content': cleaned_content,
        'sections': sections
    }
