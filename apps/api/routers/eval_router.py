"""
评估路由

这个模块定义了评估相关的 API 接口。
用于运行和查看评估结果。

主要接口：
1. POST /api/eval/run - 运行评估
2. GET /api/eval/results - 获取评估结果
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.db.session import get_db
from src.db.models import EvalRun

# 创建路由器
router = APIRouter()


# 请求模型
class EvalRunRequest(BaseModel):
    """评估运行请求模型"""
    eval_type: str  # 评估类型：retrieval, tool, agent
    run_name: Optional[str] = None  # 运行名称


# 响应模型
class EvalRunResponse(BaseModel):
    """评估运行响应模型"""
    id: int
    run_name: str
    eval_type: str
    total_cases: int
    passed_cases: int
    pass_rate: float
    created_at: str


@router.post("/run", response_model=EvalRunResponse)
async def run_evaluation(request: EvalRunRequest, db: Session = Depends(get_db)):
    """
    运行评估
    
    根据评估类型运行相应的评估测试。
    
    参数:
        request: 评估运行请求
        db: 数据库会话
    
    返回:
        评估运行结果
    """
    # TODO: 实现评估逻辑
    # 1. 加载评估数据集
    # 2. 运行评估
    # 3. 计算指标
    # 4. 保存结果
    
    # 模拟评估结果
    eval_run = EvalRun(
        run_name=request.run_name or f"{request.eval_type}_eval",
        eval_type=request.eval_type,
        total_cases=100,
        passed_cases=85,
        metrics={
            "recall_at_1": 0.75,
            "recall_at_3": 0.85,
            "recall_at_5": 0.90,
            "mrr": 0.82
        }
    )
    
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)
    
    return EvalRunResponse(
        id=eval_run.id,
        run_name=eval_run.run_name,
        eval_type=eval_run.eval_type,
        total_cases=eval_run.total_cases,
        passed_cases=eval_run.passed_cases,
        pass_rate=eval_run.passed_cases / eval_run.total_cases,
        created_at=eval_run.created_at.isoformat()
    )


@router.get("/results", response_model=List[EvalRunResponse])
async def get_eval_results(
    eval_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """
    获取评估结果
    
    参数:
        eval_type: 评估类型过滤
        skip: 跳过的记录数
        limit: 返回的记录数
        db: 数据库会话
    
    返回:
        评估结果列表
    """
    query = db.query(EvalRun)
    
    if eval_type:
        query = query.filter(EvalRun.eval_type == eval_type)
    
    eval_runs = query.order_by(
        EvalRun.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return [
        EvalRunResponse(
            id=run.id,
            run_name=run.run_name,
            eval_type=run.eval_type,
            total_cases=run.total_cases,
            passed_cases=run.passed_cases,
            pass_rate=run.passed_cases / run.total_cases if run.total_cases > 0 else 0,
            created_at=run.created_at.isoformat()
        )
        for run in eval_runs
    ]
