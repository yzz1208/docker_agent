"""
数据库会话管理

这个模块负责管理数据库连接和会话。
使用 SQLAlchemy 的会话工厂模式。

主要功能：
1. 创建数据库引擎
2. 创建会话工厂
3. 提供获取会话的上下文管理器
"""

import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 从环境变量获取数据库连接字符串
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/docker_agent")

# 创建数据库引擎
# pool_size: 连接池大小
# max_overflow: 超出连接池大小的额外连接数
# pool_pre_ping: 在每次连接前检查连接是否有效
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=os.getenv("APP_ENV") == "development"  # 开发环境下打印 SQL 语句
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """
    获取数据库会话
    
    这是一个生成器函数，用于 FastAPI 的依赖注入。
    它会自动处理会话的创建和关闭。
    
    使用示例：
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Session:
    """
    获取数据库会话的上下文管理器
    
    用于非 FastAPI 的场景，如脚本和测试。
    
    使用示例：
        with get_db_context() as db:
            chunks = db.query(DocumentChunk).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """
    初始化数据库
    
    创建所有表结构。
    在首次运行时调用。
    """
    from .models import Base
    Base.metadata.create_all(bind=engine)
    print("数据库表创建完成")
