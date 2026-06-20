"""LLM 服务 - 调用 DeepSeek API 进行 AI 分析"""
import httpx
import json
import logging
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# DeepSeek 推理模型需要更大的 max_tokens（推理 tokens + 输出 tokens）
DEFAULT_MAX_TOKENS = 4000
REQUEST_TIMEOUT = 120.0  # 推理模型响应较慢，给更长超时


def _extract_content(data: dict) -> str:
    """从 LLM 响应中提取内容，兼容推理模型"""
    if "choices" not in data or len(data["choices"]) == 0:
        return ""
    msg = data["choices"][0]["message"]
    content = msg.get("content", "")
    # DeepSeek 推理模型可能把内容放在 reasoning_content 中
    if not content and msg.get("reasoning_content"):
        content = msg["reasoning_content"]
    return content


async def call_llm(prompt: str, system_prompt: str = "", max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """异步调用 LLM API"""
    if not settings.LLM_API_KEY:
        return "⚠️ 未配置 LLM API Key，请在 .env 文件中设置 LLM_API_KEY"

    url = f"{settings.LLM_API_URL}/chat/completions"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            content = _extract_content(data)
            if content:
                return content
            else:
                logger.error(f"LLM API 返回空内容: {json.dumps(data, ensure_ascii=False)[:300]}")
                return f"⚠️ LLM 返回内容为空，可能需要增加 max_tokens（当前: {max_tokens}）"

    except httpx.TimeoutException:
        logger.error("LLM API 请求超时")
        return "⚠️ LLM API 请求超时（推理模型响应较慢），请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"LLM API HTTP 错误: {e.response.status_code} - {e.response.text}")
        return f"⚠️ LLM API 错误 ({e.response.status_code}): {e.response.text[:200]}"
    except Exception as e:
        logger.error(f"LLM API 调用失败: {e}")
        return f"⚠️ LLM API 调用失败: {str(e)}"


def call_llm_sync(prompt: str, system_prompt: str = "", max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """同步调用 LLM API（用于非异步上下文）"""
    if not settings.LLM_API_KEY:
        return "⚠️ 未配置 LLM API Key，请在 .env 文件中设置 LLM_API_KEY"

    url = f"{settings.LLM_API_URL}/chat/completions"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            content = _extract_content(data)
            if content:
                return content
            else:
                logger.error(f"LLM API 返回空内容: {json.dumps(data, ensure_ascii=False)[:300]}")
                return f"⚠️ LLM 返回内容为空，可能需要增加 max_tokens（当前: {max_tokens}）"

    except httpx.TimeoutException:
        logger.error("LLM API 请求超时")
        return "⚠️ LLM API 请求超时（推理模型响应较慢），请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"LLM API HTTP 错误: {e.response.status_code} - {e.response.text}")
        return f"⚠️ LLM API 错误 ({e.response.status_code}): {e.response.text[:200]}"
    except Exception as e:
        logger.error(f"LLM API 调用失败: {e}")
        return f"⚠️ LLM API 调用失败: {str(e)}"


# ==================== 金融分析提示词模板 ====================

SYSTEM_PROMPT_STOCK_ANALYST = """你是一位资深的 A 股和港股分析师，拥有 10 年以上的投研经验。
你的分析风格专业、客观、数据驱动，会结合基本面、技术面和市场情绪给出综合判断。
请用中文回答，格式清晰，使用 markdown 表格展示数据。"""

PROMPT_STOCK_ANALYSIS = """请对以下股票进行深度分析：

股票代码：{symbol}
股票名称：{name}
所属行业：{industry}
市场：{market}

最新行情数据：
- 收盘价：{close}
- 市盈率(PE)：{pe}
- 市净率(PB)：{pb}
- 总市值：{market_cap}

评分数据：
- 综合评分：{total_score}/100
- 质量分：{quality_score}/30
- 估值分：{valuation_score}/20
- 成长分：{growth_score}/20
- 趋势分：{trend_score}/20
- 风险分：{risk_score}/10
- 评级：{rating}

请从以下维度进行分析：
1. **基本面分析**：财务健康度、盈利能力、成长性
2. **估值分析**：当前估值是否合理，与行业对比
3. **技术面分析**：趋势判断、关键支撑/阻力位
4. **风险提示**：主要风险因素
5. **投资建议**：综合判断和操作建议

请给出明确的结论和评级。"""

PROMPT_MARKET_ANALYSIS = """请对当前 A 股和港股市场进行综合分析：

市场数据：
{market_data}

信号分布：
{signal_distribution}

请分析：
1. **市场状态判断**：当前是牛市、熊市还是震荡市
2. **板块轮动**：哪些板块值得关注
3. **风险因素**：当前市场的主要风险
4. **投资策略建议**：仓位建议和配置方向"""

PROMPT_RISK_ALERT = """请对以下持仓进行风险评估：

持仓信息：
{portfolio_data}

市场环境：
{market_context}

请重点分析：
1. **集中度风险**：持仓是否过于集中
2. **行业风险**：所处行业面临的挑战
3. **估值风险**：当前估值是否存在泡沫
4. **流动性风险**：交易活跃度是否正常
5. **风险应对建议**：具体的风险控制措施"""
