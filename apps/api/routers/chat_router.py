"""
聊天路由

这个模块定义了聊天相关的 API 接口。
处理用户与 Agent 的对话交互。

主要接口：
1. POST /api/chat - 发送消息并获取回复
2. GET /api/conversations - 获取会话列表
3. GET /api/conversations/{id}/messages - 获取会话消息
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.db.session import get_db
from src.db.models import Conversation, Message

# 创建路由器
router = APIRouter()


# 请求模型
class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str  # 用户消息
    conversation_id: Optional[int] = None  # 会话 ID，为空则创建新会话


# 响应模型
class ChatResponse(BaseModel):
    """聊天响应模型"""
    response: str  # Agent 回复
    sources: List[str] = []  # 参考来源
    tool_calls: List[str] = []  # 工具调用
    conversation_id: int  # 会话 ID


class ConversationResponse(BaseModel):
    """会话响应模型"""
    id: int
    state: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    """消息响应模型"""
    id: int
    role: str
    content: str
    created_at: str


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """
    处理聊天请求
    
    接收用户消息，调用 Agent 处理，返回响应。
    
    参数:
        request: 聊天请求，包含消息内容和可选的会话 ID
        db: 数据库会话
    
    返回:
        ChatResponse: 包含 Agent 回复、来源和工具调用的响应
    
    处理流程：
    1. 获取或创建会话
    2. 保存用户消息
    3. 调用 Agent 处理（TODO: 实现）
    4. 保存 Agent 回复
    5. 返回响应
    """
    # 获取或创建会话
    if request.conversation_id:
        conversation = db.query(Conversation).filter(
            Conversation.id == request.conversation_id
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        # 创建新会话
        conversation = Conversation(state="active")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    
    # 保存用户消息
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=request.message
    )
    db.add(user_message)
    db.commit()
    
    # 调用 Agent 处理消息
    try:
        from src.agent.graph import run_agent
        print(f"[API] 调用 Agent 处理消息: {request.message}")
        agent_result = await run_agent(request.message)
        
        agent_response = agent_result.get("response", "抱歉，我无法处理您的请求。")
        sources = agent_result.get("sources", [])
        tool_calls = agent_result.get("tool_calls", [])
        print(f"[API] Agent 响应成功")
    except Exception as e:
        # 如果 Agent 调用失败，使用模拟响应
        import traceback
        print(f"[API] Agent 调用失败: {e}")
        traceback.print_exc()
        agent_response = f"收到消息: {request.message}"
        sources = ["Docker Docs: Troubleshooting the Docker daemon"]
        tool_calls = []
    
    # 保存 Agent 回复
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=agent_response
    )
    db.add(assistant_message)
    db.commit()
    
    return ChatResponse(
        response=agent_response,
        sources=sources,
        tool_calls=tool_calls,
        conversation_id=conversation.id
    )


@router.get("/conversations", response_model=List[ConversationResponse])
async def get_conversations(
    skip: int = 0, 
    limit: int = 20, 
    db: Session = Depends(get_db)
):
    """
    获取会话列表
    
    参数:
        skip: 跳过的记录数
        limit: 返回的记录数
        db: 数据库会话
    
    返回:
        会话列表
    """
    conversations = db.query(Conversation).order_by(
        Conversation.updated_at.desc()
    ).offset(skip).limit(limit).all()
    
    return [
        ConversationResponse(
            id=conv.id,
            state=conv.state,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat()
        )
        for conv in conversations
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_conversation_messages(
    conversation_id: int, 
    db: Session = Depends(get_db)
):
    """
    获取会话消息
    
    参数:
        conversation_id: 会话 ID
        db: 数据库会话
    
    返回:
        消息列表
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.asc()).all()
    
    return [
        MessageResponse(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at.isoformat()
        )
        for msg in messages
    ]
