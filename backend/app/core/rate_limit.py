"""
简单的内存频率限制器
用于防止登录/注册暴力破解
"""
import time
from collections import defaultdict
from functools import wraps
from fastapi import HTTPException, Request

# 存储: {key: [timestamp1, timestamp2, ...]}
_attempts: dict[str, list[float]] = defaultdict(list)


def rate_limit(key_prefix: str, max_attempts: int = 5, window_seconds: int = 300):
    """
    频率限制装饰器
    - key_prefix: 限制键前缀（如 "login"）
    - max_attempts: 窗口内最大尝试次数
    - window_seconds: 窗口大小（秒）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 从 kwargs 获取 request
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            ip = request.client.host if request else "unknown"
            key = f"{key_prefix}:{ip}"

            now = time.time()
            # 清理过期记录
            _attempts[key] = [t for t in _attempts[key] if now - t < window_seconds]

            if len(_attempts[key]) >= max_attempts:
                remaining = int(window_seconds - (now - _attempts[key][0]))
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁，请 {remaining} 秒后再试"
                )

            _attempts[key].append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator
