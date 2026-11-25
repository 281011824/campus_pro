"""
班主任工作台 Redis 异步客户端初始化。

Web 进程只持有一个到工作台队列的客户端；后台 worker 使用同一 URL 独立连接。
"""

from typing import Optional

import redis.asyncio as redis


_head_teacher_workbench_redis_client: Optional[redis.Redis] = None


async def init_head_teacher_workbench_redis(redis_url: str) -> redis.Redis:
    """按独立 URL 初始化班主任工作台连接。"""
    global _head_teacher_workbench_redis_client
    _head_teacher_workbench_redis_client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        encoding="utf-8",
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=False,
    )
    return _head_teacher_workbench_redis_client


def get_head_teacher_workbench_redis() -> redis.Redis:
    if _head_teacher_workbench_redis_client is None:
        raise RuntimeError("Head teacher workbench Redis client not initialized")
    return _head_teacher_workbench_redis_client


async def close_head_teacher_workbench_redis():
    global _head_teacher_workbench_redis_client
    if _head_teacher_workbench_redis_client:
        await _head_teacher_workbench_redis_client.close()
        _head_teacher_workbench_redis_client = None
