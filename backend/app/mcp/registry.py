"""MCP插件注册表 - 管理运行时插件实例"""
import asyncio
import time
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from datetime import datetime
from app.mcp.http_client import HTTPMCPClient, MCPError
from app.mcp.config import mcp_config
from app.models.mcp_plugin import MCPPlugin
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SessionInfo:
    """会话信息"""
    client: HTTPMCPClient
    created_at: float
    last_access: float
    request_count: int = 0
    error_count: int = 0
    status: str = "active"  # active, degraded, error


class MCPPluginRegistry:
    """MCP插件注册表 - 管理运行时插件实例（优化版）"""
    
    def __init__(
        self,
        max_clients: Optional[int] = None,
        client_ttl: Optional[int] = None
    ):
        """
        初始化注册表
        
        Args:
            max_clients: 最大缓存客户端数量（默认使用配置）
            client_ttl: 客户端过期时间（秒，默认使用配置）
        """
        # 存储格式: {plugin_id: SessionInfo}
        self._sessions: Dict[str, SessionInfo] = {}
        
        # 全局锁用于保护会话字典
        self._sessions_lock = asyncio.Lock()
        
        # 细粒度锁：每个用户一个锁
        self._user_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()  # 保护locks字典本身
        
        # 配置参数（使用配置常量）
        self._max_clients = max_clients or mcp_config.MAX_CLIENTS
        self._client_ttl = client_ttl or mcp_config.CLIENT_TTL_SECONDS
        
        # 启动后台清理任务
        self._cleanup_task = None
        self._health_check_task = None
        self._start_background_tasks()
    
    def _start_background_tasks(self):
        """启动后台任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("✅ MCP插件注册表后台清理任务已启动")
        
        if self._health_check_task is None:
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            logger.info("✅ MCP会话健康检查任务已启动")
    
    async def _cleanup_loop(self):
        """后台清理过期客户端"""
        while True:
            try:
                await asyncio.sleep(mcp_config.CLEANUP_INTERVAL_SECONDS)
                await self._cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理任务异常: {e}")
    
    async def _health_check_loop(self):
        """后台健康检查"""
        while True:
            try:
                await asyncio.sleep(mcp_config.HEALTH_CHECK_INTERVAL_SECONDS)
                await self._check_session_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查任务异常: {e}")
    
    async def _cleanup_expired_sessions(self):
        """清理过期的会话"""
        now = time.time()
        expired_ids = []
        
        async with self._sessions_lock:
            # 收集过期的plugin_id
            for plugin_id, session in list(self._sessions.items()):
                if now - session.last_access > self._client_ttl:
                    expired_ids.append(plugin_id)
        
        if expired_ids:
            logger.info(f"🧹 清理 {len(expired_ids)} 个过期的MCP会话")
            for plugin_id in expired_ids:
                # 提取user_id来获取对应的锁
                user_id = plugin_id.split(':', 1)[0]
                user_lock = await self._get_user_lock(user_id)
                
                async with user_lock:
                    async with self._sessions_lock:
                        if plugin_id in self._sessions:
                            await self._unload_plugin_unsafe(plugin_id)
    
    async def _check_session_health(self):
        """增强的会话健康检查"""
        async with self._sessions_lock:
            for plugin_id, session in list(self._sessions.items()):
                # 计算错误率
                if session.request_count > mcp_config.MIN_REQUESTS_FOR_HEALTH_CHECK:
                    error_rate = session.error_count / session.request_count
                    
                    # 动态调整状态（使用配置常量）
                    if error_rate > mcp_config.ERROR_RATE_CRITICAL:
                        if session.status != "error":
                            session.status = "error"
                            logger.error(
                                f"❌ 会话 {plugin_id} 错误率过高 "
                                f"({error_rate:.1%}), 标记为error"
                            )
                    elif error_rate > mcp_config.ERROR_RATE_WARNING:
                        if session.status == "active":
                            session.status = "degraded"
                            logger.warning(
                                f"⚠️ 会话 {plugin_id} 健康状况下降 "
                                f"(错误率: {error_rate:.1%})"
                            )
                    elif session.status == "degraded":
                        # 错误率降低，恢复正常
                        session.status = "active"
                        logger.info(f"✅ 会话 {plugin_id} 恢复正常")
                
                # 检查长时间无活动的会话
                idle_time = time.time() - session.last_access
                if idle_time > mcp_config.IDLE_TIMEOUT_SECONDS:
                    logger.info(
                        f"💤 会话 {plugin_id} 空闲 {idle_time/60:.1f} 分钟，"
                        f"准备清理"
                    )
    
    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        """
        获取用户专属的锁（细粒度锁）
        
        Args:
            user_id: 用户ID
            
        Returns:
            该用户的锁对象
        """
        async with self._locks_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]
    
    def _touch_session(self, plugin_id: str):
        """
        更新会话的最后访问时间（需要在锁内调用）
        
        Args:
            plugin_id: 插件ID
        """
        if plugin_id in self._sessions:
            session = self._sessions[plugin_id]
            session.last_access = time.time()
            session.request_count += 1
    
    async def _evict_lru_session(self):
        """驱逐最久未使用的会话（当达到max_clients限制时）"""
        if len(self._sessions) >= self._max_clients:
            # 找到最旧的会话
            oldest_id = None
            oldest_time = float('inf')
            
            for plugin_id, session in self._sessions.items():
                if session.last_access < oldest_time:
                    oldest_time = session.last_access
                    oldest_id = plugin_id
            
            if oldest_id:
                logger.info(f"📤 达到最大会话数量限制，驱逐: {oldest_id}")
                await self._unload_plugin_unsafe(oldest_id)
    
    async def load_plugin(self, plugin: MCPPlugin) -> bool:
        """
        从配置加载插件
        
        Args:
            plugin: 插件配置
            
        Returns:
            是否加载成功
        """
        # 使用细粒度锁（只锁定当前用户）
        user_lock = await self._get_user_lock(plugin.user_id)
        async with user_lock:
            try:
                plugin_id = f"{plugin.user_id}:{plugin.plugin_name}"
                
                # 如果已加载，先卸载
                async with self._sessions_lock:
                    if plugin_id in self._sessions:
                        await self._unload_plugin_unsafe(plugin_id)
                    
                    # 检查是否需要驱逐LRU会话
                    await self._evict_lru_session()
                
                # 目前只支持HTTP类型
                if plugin.plugin_type == "http":
                    if not plugin.server_url:
                        logger.error(f"HTTP插件缺少server_url: {plugin.plugin_name}")
                        return False
                    
                    # 为每个插件创建独立的HTTP客户端
                    client = HTTPMCPClient(
                        url=plugin.server_url,
                        headers=plugin.headers or {},
                        env=plugin.env or {},
                        timeout=plugin.config.get('timeout', 60.0) if plugin.config else 60.0
                    )
                    
                    # 创建会话信息
                    now = time.time()
                    session = SessionInfo(
                        client=client,
                        created_at=now,
                        last_access=now,
                        request_count=0,
                        error_count=0,
                        status="active"
                    )
                    
                    # 存储会话
                    async with self._sessions_lock:
                        self._sessions[plugin_id] = session
                    
                    logger.info(f"✅ 加载MCP插件: {plugin_id} (独立会话)")
                    return True
                else:
                    logger.warning(f"暂不支持的插件类型: {plugin.plugin_type}")
                    return False
                    
            except Exception as e:
                logger.error(f"加载插件失败 {plugin.plugin_name}: {e}")
                return False
    
    async def unload_plugin(self, user_id: str, plugin_name: str):
        """
        卸载插件
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
        """
        # 使用细粒度锁（只锁定当前用户）
        user_lock = await self._get_user_lock(user_id)
        async with user_lock:
            plugin_id = f"{user_id}:{plugin_name}"
            async with self._sessions_lock:
                await self._unload_plugin_unsafe(plugin_id)
    
    async def _unload_plugin_unsafe(self, plugin_id: str):
        """卸载插件（不加锁，内部使用，需要在sessions_lock内调用）"""
        if plugin_id in self._sessions:
            session = self._sessions[plugin_id]
            try:
                await session.client.close()
            except Exception as e:
                logger.error(f"关闭插件客户端失败 {plugin_id}: {e}")
            
            del self._sessions[plugin_id]
            logger.info(f"卸载MCP插件: {plugin_id}")
    
    async def reload_plugin(self, plugin: MCPPlugin) -> bool:
        """
        重新加载插件
        
        Args:
            plugin: 插件配置
            
        Returns:
            是否重载成功
        """
        await self.unload_plugin(plugin.user_id, plugin.plugin_name)
        return await self.load_plugin(plugin)
    
    def get_client(self, user_id: str, plugin_name: str) -> Optional[HTTPMCPClient]:
        """
        获取插件客户端（线程安全，支持访问时间更新）
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
            
        Returns:
            客户端实例或None
        """
        plugin_id = f"{user_id}:{plugin_name}"
        
        session = self._sessions.get(plugin_id)
        if session:
            # 检查会话状态
            if session.status == "error":
                logger.warning(
                    f"⚠️ 会话 {plugin_id} 处于错误状态，"
                    f"建议调用者重新加载插件"
                )
                # 不返回错误状态的客户端
                return None
            
            # ✅ 使用锁保护状态更新，避免并发问题
            # 注意：这里使用原子操作更新简单字段，不需要异步锁
            session.last_access = time.time()
            session.request_count += 1
            return session.client
        return None
    
    async def get_or_reconnect_client(
        self,
        user_id: str,
        plugin_name: str,
        plugin: MCPPlugin
    ) -> HTTPMCPClient:
        """
        获取或重连客户端（自动处理错误状态）
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
            plugin: 插件配置对象
            
        Returns:
            客户端实例
            
        Raises:
            ValueError: 插件加载失败
        """
        plugin_id = f"{user_id}:{plugin_name}"
        
        # 获取用户锁
        user_lock = await self._get_user_lock(user_id)
        async with user_lock:
            session = self._sessions.get(plugin_id)
            
            # 检查会话健康状态
            if session and session.status == "error":
                logger.warning(f"会话 {plugin_id} 处于错误状态，尝试重连")
                async with self._sessions_lock:
                    await self._unload_plugin_unsafe(plugin_id)
                session = None
            
            # 如果没有会话，加载插件
            if not session:
                success = await self.load_plugin(plugin)
                if not success:
                    raise ValueError(f"插件加载失败: {plugin_name}")
                session = self._sessions[plugin_id]
            
            return session.client
    
    async def call_tool(
        self,
        user_id: str,
        plugin_name: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """
        调用插件工具（带错误计数和状态管理）
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            工具执行结果
            
        Raises:
            ValueError: 插件不存在或未启用
            MCPError: 工具调用失败
        """
        plugin_id = f"{user_id}:{plugin_name}"
        
        # 获取会话
        session = self._sessions.get(plugin_id)
        if not session:
            raise ValueError(f"插件未加载: {plugin_name}")
        
        try:
            result = await session.client.call_tool(tool_name, arguments)
            logger.info(f"✅ 工具调用成功: {plugin_name}.{tool_name}")
            
            # 调用成功，重置状态（如果之前是degraded）
            if session.status == "degraded":
                session.status = "active"
                logger.info(f"✅ 会话 {plugin_id} 恢复正常")
            
            return result
        except Exception as e:
            # 增加错误计数
            session.error_count += 1
            
            # 根据错误率更新状态
            if session.request_count > 0:
                error_rate = session.error_count / session.request_count
                if error_rate > 0.5:
                    session.status = "error"
                elif error_rate > 0.3:
                    session.status = "degraded"
            
            logger.error(
                f"❌ 工具调用失败: {plugin_name}.{tool_name}, "
                f"错误: {e} (错误计数: {session.error_count}/{session.request_count})"
            )
            raise
    
    async def get_plugin_tools(
        self,
        user_id: str,
        plugin_name: str
    ) -> List[Dict[str, Any]]:
        """
        获取插件的工具列表
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
            
        Returns:
            工具列表
        """
        client = self.get_client(user_id, plugin_name)
        
        if not client:
            raise ValueError(f"插件未加载: {plugin_name}")
        
        try:
            tools = await client.list_tools()
            return tools
        except Exception as e:
            logger.error(f"获取工具列表失败: {plugin_name}, 错误: {e}")
            raise
    
    async def test_plugin(
        self,
        user_id: str,
        plugin_name: str
    ) -> Dict[str, Any]:
        """
        测试插件连接
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
            
        Returns:
            测试结果
        """
        client = self.get_client(user_id, plugin_name)
        
        if not client:
            raise ValueError(f"插件未加载: {plugin_name}")
        
        return await client.test_connection()
    
    async def cleanup_all(self):
        """清理所有插件和资源"""
        # 停止后台任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # 清理所有会话
        async with self._sessions_lock:
            plugin_ids = list(self._sessions.keys())
            for plugin_id in plugin_ids:
                await self._unload_plugin_unsafe(plugin_id)
        
        logger.info("✅ 已清理所有MCP插件和资源")


# 全局注册表实例
mcp_registry = MCPPluginRegistry()