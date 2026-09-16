"""
Docker Support Agent API

这是 FastAPI 应用的主入口文件。
提供 RESTful API 接口供前端调用。

主要功能：
1. 健康检查接口
2. 聊天接口
3. 数据库初始化
"""

import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 创建 FastAPI 应用实例
app = FastAPI(
    title="Docker Support Agent",
    description="基于 RAG 的 Docker 技术支持 Agent",
    version="0.1.0",
    docs_url="/docs",  # Swagger UI 路径
    redoc_url="/redoc"  # ReDoc 路径
)

# 配置 CORS（跨域资源共享）
# 允许前端（Vue）访问 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制为特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """
    根路径
    
    返回欢迎信息，用于验证 API 是否正常运行。
    """
    return {
        "message": "Docker Support Agent API",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """
    健康检查接口
    
    用于监控系统状态，检查 API 服务是否正常运行。
    
    返回:
        状态信息，包含 API 状态和数据库连接状态
    """
    try:
        # 尝试连接数据库
        from src.db.session import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "database": db_status,
        "environment": os.getenv("APP_ENV", "development")
    }


@app.post("/api/chat")
async def chat(request: dict):
    """
    聊天接口
    
    接收用户消息，调用 Agent 处理，返回响应。
    
    请求体:
        {
            "message": "用户消息",
            "conversation_id": 1  # 可选，会话 ID
        }
    
    返回:
        {
            "response": "Agent 回复",
            "sources": ["来源1", "来源2"],
            "tool_calls": ["工具调用1"],
            "conversation_id": 1
        }
    """
    # TODO: 实现 Agent 逻辑
    # 1. 获取或创建会话
    # 2. 调用 Agent 处理消息
    # 3. 保存消息到数据库
    # 4. 返回响应
    
    message = request.get("message", "")
    
    return {
        "response": f"收到消息: {message}",
        "sources": [],
        "tool_calls": [],
        "conversation_id": 1
    }


# 导入路由
from apps.api.routers import chat_router, eval_router

# 注册路由
app.include_router(chat_router.router, prefix="/api", tags=["chat"])
app.include_router(eval_router.router, prefix="/api/eval", tags=["evaluation"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
