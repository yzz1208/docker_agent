"""
数据库初始化脚本

这个脚本负责初始化数据库，创建表结构。
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.session import init_db


def main():
    """
    初始化数据库
    """
    print("开始初始化数据库...")
    
    try:
        init_db()
        print("数据库初始化完成！")
        print("\n表结构已创建：")
        print("  - document_chunks (文档块)")
        print("  - conversations (对话会话)")
        print("  - messages (对话消息)")
        print("  - tickets (支持工单)")
        print("  - eval_runs (评估运行)")
        
        print("\n下一步：")
        print("  1. 确保 PostgreSQL 服务正在运行")
        print("  2. 运行 python scripts/build_index.py --use-mock 构建索引")
        print("  3. 运行 uvicorn apps.api.main:app --reload 启动 API")
        
    except Exception as e:
        print(f"数据库初始化失败: {e}")
        print("\n请检查：")
        print("  1. PostgreSQL 服务是否正在运行")
        print("  2. 数据库连接配置是否正确")
        print("  3. 数据库用户是否有权限创建表")
        sys.exit(1)


if __name__ == "__main__":
    main()
