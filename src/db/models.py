"""
数据库模型定义

这个模块定义了 PostgreSQL 数据库的所有表结构。
使用 SQLAlchemy ORM 来管理数据库操作。

主要表：
1. DocumentChunk - 存储文档块和向量嵌入
2. Conversation - 存储对话会话
3. Message - 存储对话消息
4. Ticket - 存储支持工单
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Float, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

# 尝试导入 pgvector，如果失败则使用 JSON 存储向量
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False

# 创建基础模型类
Base = declarative_base()


class DocumentChunk(Base):
    """
    文档块模型
    
    存储从 Docker 文档中提取的文本块及其向量嵌入。
    用于 RAG 检索。
    
    字段说明：
    - id: 主键
    - chunk_id: 唯一标识符，格式如 "docker_engine_daemon_troubleshoot__unable_connect__001"
    - document_id: 文档标识符
    - title: 文档标题
    - section_path: 章节路径，JSON 数组格式
    - content: 文本内容
    - source_url: 源文档 URL
    - file_path: 文件路径
    - token_count: token 数量
    - embedding: 向量嵌入（1024 维）
    """
    __tablename__ = "document_chunks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chunk_id = Column(String(255), unique=True, nullable=False, index=True)
    document_id = Column(String(255), nullable=False, index=True)
    title = Column(Text, nullable=False)
    section_path = Column(JSON, nullable=False)
    content = Column(Text, nullable=False)
    source_url = Column(Text)
    file_path = Column(Text)
    token_count = Column(Integer, nullable=False)
    # 如果 pgvector 可用，使用 Vector 类型；否则使用 JSON 存储
    if HAS_PGVECTOR:
        embedding = Column(Vector(1024))  # BAAI/bge-m3 输出 1024 维向量
    else:
        embedding = Column(JSON)  # 使用 JSON 存储向量
    
    def __repr__(self):
        return f"<DocumentChunk(chunk_id='{self.chunk_id}', title='{self.title[:30]}...')>"


class Conversation(Base):
    """
    对话会话模型
    
    存储用户与 Agent 的对话会话。
    
    字段说明：
    - id: 主键
    - created_at: 创建时间
    - updated_at: 更新时间
    - state: 会话状态（active, closed）
    """
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    state = Column(String(50), default="active", nullable=False)
    
    # 关系：一个会话包含多条消息
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Conversation(id={self.id}, state='{self.state}')>"


class Message(Base):
    """
    对话消息模型
    
    存储对话中的每条消息。
    
    字段说明：
    - id: 主键
    - conversation_id: 关联的会话 ID
    - role: 消息角色（user, assistant, system）
    - content: 消息内容
    - created_at: 创建时间
    """
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # 关系：消息属于某个会话
    conversation = relationship("Conversation", back_populates="messages")
    
    def __repr__(self):
        return f"<Message(id={self.id}, role='{self.role}', content='{self.content[:30]}...')>"


class Ticket(Base):
    """
    支持工单模型
    
    存储创建的支持工单。
    
    字段说明：
    - id: 主键
    - ticket_id: 工单编号（如 T-2026-0001）
    - title: 工单标题
    - problem: 问题描述
    - environment: 环境信息（JSON 格式）
    - diagnostics: 诊断信息
    - status: 工单状态（created, in_progress, resolved）
    - created_at: 创建时间
    """
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(Text, nullable=False)
    problem = Column(Text, nullable=False)
    environment = Column(JSON)
    diagnostics = Column(Text)
    status = Column(String(50), default="created", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<Ticket(ticket_id='{self.ticket_id}', status='{self.status}')>"


class EvalRun(Base):
    """
    评估运行模型
    
    存储评估测试的运行结果。
    
    字段说明：
    - id: 主键
    - run_name: 运行名称
    - eval_type: 评估类型（retrieval, tool, agent）
    - total_cases: 总用例数
    - passed_cases: 通过用例数
    - metrics: 评估指标（JSON 格式）
    - created_at: 创建时间
    """
    __tablename__ = "eval_runs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_name = Column(String(255), nullable=False)
    eval_type = Column(String(50), nullable=False)
    total_cases = Column(Integer, nullable=False)
    passed_cases = Column(Integer, nullable=False)
    metrics = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<EvalRun(run_name='{self.run_name}', eval_type='{self.eval_type}')>"
