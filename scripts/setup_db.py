"""
数据库设置脚本

这个脚本负责：
1. 创建数据库（如果不存在）
2. 安装 pgvector 扩展
3. 创建表结构
"""

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys


def setup_database():
    """
    设置数据库
    """
    print("开始设置数据库...")
    
    # 数据库配置
    db_config = {
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "password": "3017",
        "database": "postgres"  # 先连接到默认数据库
    }
    
    target_db = "docker_agent"
    
    try:
        # 1. 连接到 PostgreSQL
        print("1. 连接到 PostgreSQL...")
        conn = psycopg2.connect(**db_config)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # 2. 检查数据库是否存在
        print("2. 检查数据库是否存在...")
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        exists = cursor.fetchone()
        
        if not exists:
            print(f"   创建数据库: {target_db}")
            cursor.execute(f"CREATE DATABASE {target_db}")
        else:
            print(f"   数据库已存在: {target_db}")
        
        cursor.close()
        conn.close()
        
        # 3. 连接到目标数据库
        print("3. 连接到目标数据库...")
        db_config["database"] = target_db
        conn = psycopg2.connect(**db_config)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # 4. 检查 pgvector 扩展
        print("4. 检查 pgvector 扩展...")
        try:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            has_pgvector = cursor.fetchone()
            if has_pgvector:
                print("   pgvector 扩展已安装")
            else:
                print("   pgvector 扩展未安装")
                print("   注意：向量检索功能将不可用")
                print("   如需向量检索，请安装 pgvector 扩展")
        except Exception as e:
            print(f"   检查 pgvector 扩展失败: {e}")
        
        # 5. 创建表结构
        print("5. 创建表结构...")
        
        # 检查是否有 pgvector 扩展
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        has_pgvector = cursor.fetchone()
        
        # 创建 document_chunks 表
        if has_pgvector:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL NOT NULL,
                    chunk_id VARCHAR(255) NOT NULL,
                    document_id VARCHAR(255) NOT NULL,
                    title TEXT NOT NULL,
                    section_path JSON NOT NULL,
                    content TEXT NOT NULL,
                    source_url TEXT,
                    file_path TEXT,
                    token_count INTEGER NOT NULL,
                    embedding VECTOR(1024),
                    PRIMARY KEY (id)
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL NOT NULL,
                    chunk_id VARCHAR(255) NOT NULL,
                    document_id VARCHAR(255) NOT NULL,
                    title TEXT NOT NULL,
                    section_path JSON NOT NULL,
                    content TEXT NOT NULL,
                    source_url TEXT,
                    file_path TEXT,
                    token_count INTEGER NOT NULL,
                    embedding JSON,
                    PRIMARY KEY (id)
                )
            """)
        
        # 创建 conversations 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                state VARCHAR(50) NOT NULL DEFAULT 'active',
                PRIMARY KEY (id)
            )
        """)
        
        # 创建 messages 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL NOT NULL,
                conversation_id INTEGER NOT NULL,
                role VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id),
                FOREIGN KEY (conversation_id) REFERENCES conversations (id)
            )
        """)
        
        # 创建 tickets 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL NOT NULL,
                ticket_id VARCHAR(50) NOT NULL,
                title TEXT NOT NULL,
                problem TEXT NOT NULL,
                environment JSON,
                diagnostics TEXT,
                status VARCHAR(50) NOT NULL DEFAULT 'created',
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id)
            )
        """)
        
        # 创建 eval_runs 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS eval_runs (
                id SERIAL NOT NULL,
                run_name VARCHAR(255) NOT NULL,
                eval_type VARCHAR(50) NOT NULL,
                total_cases INTEGER NOT NULL,
                passed_cases INTEGER NOT NULL,
                metrics JSON,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id)
            )
        """)
        
        print("   表结构创建完成")
        
        # 6. 创建索引
        print("6. 创建索引...")
        
        # document_chunks 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunk_id ON document_chunks (chunk_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_document_id ON document_chunks (document_id)")
        
        # conversations 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversation_state ON conversations (state)")
        
        # messages 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_conversation ON messages (conversation_id)")
        
        # tickets 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticket_id ON tickets (ticket_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticket_status ON tickets (status)")
        
        print("   索引创建完成")
        
        cursor.close()
        conn.close()
        
        print("\n数据库设置完成！")
        print("\n已创建：")
        print(f"  - 数据库: {target_db}")
        print("  - 表: document_chunks, conversations, messages, tickets, eval_runs")
        print("  - 索引: 多个性能优化索引")
        
        print("\n下一步：")
        print("  1. 运行 python scripts/build_index.py --use-mock 构建索引")
        print("  2. 运行 uvicorn apps.api.main:app --reload 启动 API")
        
    except psycopg2.Error as e:
        print(f"数据库错误: {e}")
        print("\n请检查：")
        print("  1. PostgreSQL 服务是否正在运行")
        print("  2. 用户名和密码是否正确")
        print("  3. 用户是否有权限创建数据库")
        sys.exit(1)
    except Exception as e:
        print(f"未知错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_database()
