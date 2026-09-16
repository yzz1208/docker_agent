# LLM 配置指南

本项目支持多种 LLM 提供商，优先推荐使用免费的本地模型。

## 方案 1：Ollama（推荐，完全免费）

### 安装 Ollama

1. 访问 https://ollama.com 下载安装包
2. 安装完成后，Ollama 会自动启动

### 下载模型

```bash
# 下载 Llama 3 8B 模型（推荐，性能好且免费）
ollama pull llama3:8b

# 或者下载更小的模型（适合资源有限的环境）
ollama pull phi3:mini
ollama pull gemma:2b
```

### 配置项目

在 `.env` 文件中添加：

```env
# 使用 Ollama 本地模型
MODEL_PROVIDER=ollama
MODEL_NAME=llama3:8b
MODEL_BASE_URL=http://localhost:11434
MODEL_API_KEY=  # Ollama 不需要 API Key
```

### 测试 Ollama

```bash
# 测试模型是否正常工作
curl http://localhost:11434/api/generate -d '{
  "model": "llama3:8b",
  "prompt": "Hello, how are you?"
}'
```

---

## 方案 2：LM Studio（图形界面，免费）

### 安装 LM Studio

1. 访问 https://lmstudio.ai 下载安装包
2. 安装并启动 LM Studio

### 下载模型

1. 在 LM Studio 中搜索模型（推荐：Llama 3, Phi-3, Gemma）
2. 下载模型到本地

### 启动本地服务器

1. 在 LM Studio 中点击 "Local Server" 标签
2. 选择已下载的模型
3. 点击 "Start Server"
4. 默认地址：http://localhost:1234

### 配置项目

在 `.env` 文件中添加：

```env
# 使用 LM Studio 本地模型
MODEL_PROVIDER=openai
MODEL_NAME=local-model
MODEL_BASE_URL=http://localhost:1234/v1
MODEL_API_KEY=lm-studio  # LM Studio 默认 key
```

---

## 方案 3：免费在线 API

### Groq（推荐，免费且快速）

1. 访问 https://console.groq.com 注册账号
2. 获取 API Key
3. 在 `.env` 文件中配置：

```env
MODEL_PROVIDER=groq
MODEL_NAME=llama3-8b-8192
MODEL_BASE_URL=https://api.groq.com/openai/v1
MODEL_API_KEY=your-groq-api-key
```

### Together AI（免费额度）

1. 访问 https://api.together.xyz 注册账号
2. 获取 API Key
3. 在 `.env` 文件中配置：

```env
MODEL_PROVIDER=openai
MODEL_NAME=meta-llama/Llama-3-8b-chat-hf
MODEL_BASE_URL=https://api.together.xyz/v1
MODEL_API_KEY=your-together-api-key
```

---

## 当前推荐配置

对于学习项目，我推荐使用 **Ollama + Llama 3 8B**：

1. **完全免费**：无需支付任何费用
2. **本地运行**：数据不离开你的电脑
3. **性能足够**：Llama 3 8B 性能很好
4. **易于配置**：安装简单，配置方便

### 快速开始

```bash
# 1. 安装 Ollama（访问 https://ollama.com）

# 2. 下载模型
ollama pull llama3:8b

# 3. 更新 .env 文件
# MODEL_PROVIDER=ollama
# MODEL_NAME=llama3:8b
# MODEL_BASE_URL=http://localhost:11434

# 4. 重启 API 服务
# uvicorn apps.api.main:app --reload
```

---

## 验证配置

配置完成后，可以通过以下方式验证：

1. 访问 http://localhost:8000/docs
2. 测试 POST /api/chat 接口
3. 发送消息查看 Agent 响应

如果遇到问题，请检查：
- Ollama 服务是否正在运行
- 模型是否已下载
- .env 配置是否正确

---

## 下一步

配置好 LLM 后，我们将：
1. 实现 Agent 与 LLM 的集成
2. 测试意图分类功能
3. 测试回答生成功能
4. 优化提示工程