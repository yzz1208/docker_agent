# Docker Support Agent

> 基于 RAG 的 Docker 技术支持 Agent

## 项目概述

这是一个基于 RAG (Retrieval-Augmented Generation) 技术的 Docker 技术支持 Agent，专门用于解决 Docker 环境中的各种技术问题。

### 核心价值

**解决传统运维中的痛点：**
- 用户不知道去哪里找文档
- 文档太多，找不到相关信息
- 需要结合环境信息进行诊断
- 需要执行命令获取实时信息

**解决方案：** 使用 RAG + Agent 技术，让 AI 自动检索文档、调用工具、生成回答。

### 技术栈

```
Python 3.12
├── FastAPI          # Web 框架
├── LangGraph        # Agent 框架
├── PostgreSQL       # 数据库
├── pgvector         # 向量检索
└── sentence-transformers  # 嵌入模型
```

## 项目结构

```
docker_agent/
├── apps/                  # 应用层
│   ├── api/               # FastAPI API
│   └── web/               # Web 前端
├── src/                   # 核心源代码
│   ├── agent/             # Agent 逻辑
│   ├── rag/               # RAG 相关
│   ├── tools/             # 工具函数
│   ├── llm/               # LLM 客户端
│   └── db/                # 数据库
├── scripts/               # 脚本
├── eval/                  # 评估
├── data/                  # 数据
├── tests/                 # 测试
└── doc/                   # 开发文档
```

## 快速开始

### 1. 环境准备

确保已安装：
- Python 3.12+
- Docker (可选，用于真实模式)
- Git

### 2. 安装依赖

```bash
# 进入项目目录
cd docker_agent

# 使用 pip 安装依赖
pip install -r pyproject.toml
```

### 3. 配置环境

```bash
# 复制环境配置文件
cp .env.example .env

# 编辑 .env 文件，配置数据库和 API 密钥
```

### 4. 下载 Docker 文档

```bash
# 下载 Docker 官方文档
git clone --depth 1 https://github.com/docker/docs.git data/raw/docker-docs
```

### 5. 构建文档

```bash
# 构建文档（清洗、分割）
python scripts/build_documents.py

# 构建索引（生成向量嵌入）
python scripts/build_index.py --use-mock
```

### 6. 启动 API 服务

```bash
# 启动 FastAPI 服务
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 7. 访问应用

- **API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

## 开发计划

详细的开发计划请参考 `doc/Docker_Support_Agent_开发文档.md`

## 学习路径

1. **阅读开发文档** - 理解项目目标和架构
2. **理解 RAG 系统** - 学习文档处理和检索
3. **理解 Agent 架构** - 学习工作流设计
4. **运行和测试** - 动手实践

## 许可证

MIT License
