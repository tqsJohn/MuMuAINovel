"""MCP工具服务 - 统一管理MCP工具的注入和执行"""

from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import asyncio
import json
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

from app.models.mcp_plugin import MCPPlugin
from app.mcp.registry import mcp_registry
from app.mcp.config import mcp_config
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolMetrics:
    """工具调用指标"""
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    last_call_time: Optional[datetime] = None
    
    def update_success(self, duration_ms: float):
        """更新成功调用指标"""
        self.total_calls += 1
        self.success_calls += 1
        self.total_duration_ms += duration_ms
        self.avg_duration_ms = self.total_duration_ms / self.total_calls
        self.last_call_time = datetime.now()
    
    def update_failure(self, duration_ms: float):
        """更新失败调用指标"""
        self.total_calls += 1
        self.failed_calls += 1
        self.total_duration_ms += duration_ms
        self.avg_duration_ms = self.total_duration_ms / self.total_calls
        self.last_call_time = datetime.now()
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.success_calls / self.total_calls


@dataclass
class ToolCacheEntry:
    """工具缓存条目"""
    tools: List[Dict[str, Any]]
    expire_time: datetime
    hit_count: int = 0


class MCPToolServiceError(Exception):
    """MCP工具服务异常"""
    pass


class MCPToolService:
    """MCP工具服务 - 统一管理MCP工具的注入和执行（优化版）"""
    
    def __init__(
        self,
        cache_ttl_minutes: Optional[int] = None,
        max_retries: Optional[int] = None
    ):
        """
        初始化MCP工具服务
        
        Args:
            cache_ttl_minutes: 工具缓存TTL（分钟，默认使用配置）
            max_retries: 最大重试次数（默认使用配置）
        """
        # 工具定义缓存: {cache_key: ToolCacheEntry}
        self._tool_cache: Dict[str, ToolCacheEntry] = {}
        self._cache_ttl = timedelta(
            minutes=cache_ttl_minutes or mcp_config.TOOL_CACHE_TTL_MINUTES
        )
        
        # 调用指标: {tool_key: ToolMetrics}
        self._metrics: Dict[str, ToolMetrics] = defaultdict(ToolMetrics)
        
        # 重试配置（使用配置常量）
        self._max_retries = max_retries or mcp_config.MAX_RETRIES
        self._base_retry_delay = mcp_config.BASE_RETRY_DELAY_SECONDS
        self._max_retry_delay = mcp_config.MAX_RETRY_DELAY_SECONDS
        
        logger.info(
            f"✅ MCPToolService初始化完成 "
            f"(缓存TTL={self._cache_ttl.total_seconds()/60:.1f}分钟, "
            f"最大重试={self._max_retries}次)"
        )
    
    async def get_user_enabled_tools(
        self,
        user_id: str,
        db_session: AsyncSession,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取用户启用的MCP工具列表
        
        Args:
            user_id: 用户ID
            db_session: 数据库会话
            category: 工具类别筛选（search/analysis/filesystem等）
        
        Returns:
            工具定义列表，格式符合OpenAI Function Calling规范
        """
        try:
            # 1. 查询用户启用的插件（enabled=True即可，不强制要求status=active）
            # 因为新启用的插件status可能还是inactive，需要给它机会被调用
            query = select(MCPPlugin).where(
                MCPPlugin.user_id == user_id,
                MCPPlugin.enabled == True
            )
            
            if category:
                query = query.where(MCPPlugin.category == category)
            
            result = await db_session.execute(query)
            plugins = result.scalars().all()
            
            if not plugins:
                logger.info(f"用户 {user_id} 没有启用的MCP插件")
                return []
            
            # 2. 获取所有工具定义（使用缓存）
            all_tools = []
            for plugin in plugins:
                try:
                    # 确保插件已加载到注册表
                    if not mcp_registry.get_client(user_id, plugin.plugin_name):
                        logger.info(f"插件 {plugin.plugin_name} 未加载，尝试加载...")
                        success = await mcp_registry.load_plugin(plugin)
                        if not success:
                            logger.warning(f"插件 {plugin.plugin_name} 加载失败，跳过")
                            continue
                    
                    # ✅ 使用缓存获取工具列表
                    plugin_tools = await self._get_plugin_tools_cached(
                        user_id=user_id,
                        plugin_name=plugin.plugin_name
                    )
                    
                    # 格式化为Function Calling格式
                    formatted_tools = self._format_tools_for_ai(
                        plugin_tools,
                        plugin.plugin_name
                    )
                    all_tools.extend(formatted_tools)
                    
                    logger.info(
                        f"从插件 {plugin.plugin_name} 加载了 "
                        f"{len(formatted_tools)} 个工具"
                    )
                    
                except Exception as e:
                    logger.error(
                        f"获取插件 {plugin.plugin_name} 的工具失败: {e}",
                        exc_info=True
                    )
                    continue
            
            logger.info(f"用户 {user_id} 共加载 {len(all_tools)} 个MCP工具")
            return all_tools
            
        except Exception as e:
            logger.error(f"获取用户MCP工具失败: {e}", exc_info=True)
            raise MCPToolServiceError(f"获取MCP工具失败: {str(e)}")
    
    def _format_tools_for_ai(
        self,
        plugin_tools: List[Dict[str, Any]],
        plugin_name: str
    ) -> List[Dict[str, Any]]:
        """
        将MCP工具定义格式化为AI Function Calling格式
        
        Args:
            plugin_tools: MCP插件的工具列表
            plugin_name: 插件名称
        
        Returns:
            格式化后的工具列表
        """
        formatted_tools = []
        
        for tool in plugin_tools:
            formatted_tool = {
                "type": "function",
                "function": {
                    "name": f"{plugin_name}_{tool['name']}",  # 加插件前缀避免冲突
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {
                        "type": "object",
                        "properties": {},
                        "required": []
                    })
                }
            }
            formatted_tools.append(formatted_tool)
        
        return formatted_tools
    
    async def _get_plugin_tools_cached(
        self,
        user_id: str,
        plugin_name: str
    ) -> List[Dict[str, Any]]:
        """
        带缓存的工具列表获取
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
            
        Returns:
            工具列表
        """
        cache_key = f"{user_id}:{plugin_name}"
        now = datetime.now()
        
        # 检查缓存
        if cache_key in self._tool_cache:
            entry = self._tool_cache[cache_key]
            if now < entry.expire_time:
                entry.hit_count += 1
                logger.debug(
                    f"🎯 工具缓存命中: {cache_key} "
                    f"(命中次数: {entry.hit_count})"
                )
                return entry.tools
            else:
                logger.debug(f"⏰ 工具缓存过期: {cache_key}")
                del self._tool_cache[cache_key]
        
        # 缓存未命中，从MCP获取
        logger.debug(f"🔍 工具缓存未命中，从MCP获取: {cache_key}")
        tools = await mcp_registry.get_plugin_tools(user_id, plugin_name)
        
        # 更新缓存
        self._tool_cache[cache_key] = ToolCacheEntry(
            tools=tools,
            expire_time=now + self._cache_ttl,
            hit_count=0
        )
        
        return tools
    
    def clear_cache(self, user_id: Optional[str] = None, plugin_name: Optional[str] = None):
        """
        清理缓存
        
        Args:
            user_id: 用户ID（可选，清理特定用户的缓存）
            plugin_name: 插件名称（可选，清理特定插件的缓存）
        """
        if user_id is None and plugin_name is None:
            # 清理所有缓存
            self._tool_cache.clear()
            logger.info("🧹 已清理所有工具缓存")
        elif user_id and plugin_name:
            # 清理特定插件缓存
            cache_key = f"{user_id}:{plugin_name}"
            if cache_key in self._tool_cache:
                del self._tool_cache[cache_key]
                logger.info(f"🧹 已清理缓存: {cache_key}")
        elif user_id:
            # 清理用户所有缓存
            keys_to_delete = [
                key for key in self._tool_cache.keys()
                if key.startswith(f"{user_id}:")
            ]
            for key in keys_to_delete:
                del self._tool_cache[key]
            logger.info(f"🧹 已清理用户缓存: {user_id} ({len(keys_to_delete)}个)")
    
    async def execute_tool_calls(
        self,
        user_id: str,
        tool_calls: List[Dict[str, Any]],
        db_session: AsyncSession,
        timeout: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        批量执行AI请求的工具调用（并行执行）
        
        Args:
            user_id: 用户ID
            tool_calls: AI返回的工具调用列表
            db_session: 数据库会话
            timeout: 单个工具调用的超时时间（秒，默认使用配置）
        
        Returns:
            工具调用结果列表
        """
        if not tool_calls:
            return []
        
        # 使用配置的默认超时
        actual_timeout = timeout or mcp_config.TOOL_CALL_TIMEOUT_SECONDS
        
        logger.info(f"开始执行 {len(tool_calls)} 个工具调用 (超时={actual_timeout}s)")
        
        # 创建异步任务列表
        tasks = [
            self._execute_single_tool(
                user_id=user_id,
                tool_call=tool_call,
                db_session=db_session,
                timeout=actual_timeout
            )
            for tool_call in tool_calls
        ]
        
        # 并行执行所有工具调用
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        formatted_results = []
        for i, result in enumerate(results):
            tool_call = tool_calls[i]
            
            if isinstance(result, Exception):
                # 工具调用异常
                formatted_results.append({
                    "tool_call_id": tool_call.get("id", f"call_{i}"),
                    "role": "tool",
                    "name": tool_call["function"]["name"],
                    "content": f"工具调用失败: {str(result)}",
                    "success": False,
                    "error": str(result)
                })
            else:
                formatted_results.append(result)
        
        return formatted_results
    
    async def _execute_single_tool(
        self,
        user_id: str,
        tool_call: Dict[str, Any],
        db_session: AsyncSession,
        timeout: float
    ) -> Dict[str, Any]:
        """
        执行单个工具调用
        
        Args:
            user_id: 用户ID
            tool_call: 工具调用信息
            db_session: 数据库会话
            timeout: 超时时间
        
        Returns:
            工具调用结果
        """
        tool_call_id = tool_call.get("id", "unknown")
        function_name = tool_call["function"]["name"]
        
        try:
            # 解析插件名和工具名
            if "_" in function_name:
                plugin_name, tool_name = function_name.split("_", 1)
            else:
                raise ValueError(f"无效的工具名称格式: {function_name}")
            
            # 解析参数
            arguments_str = tool_call["function"]["arguments"]
            if isinstance(arguments_str, str):
                arguments = json.loads(arguments_str)
            else:
                arguments = arguments_str
            
            logger.info(
                f"执行工具: {plugin_name}.{tool_name}, "
                f"参数: {arguments}"
            )
            
            # ✅ 使用带重试的调用
            tool_key = f"{plugin_name}.{tool_name}"
            start_time = time.time()
            
            try:
                result = await self._call_tool_with_retry(
                    user_id=user_id,
                    plugin_name=plugin_name,
                    tool_name=tool_name,
                    arguments=arguments,
                    timeout=timeout
                )
                
                # 记录成功指标
                duration_ms = (time.time() - start_time) * 1000
                self._metrics[tool_key].update_success(duration_ms)
                
                logger.info(
                    f"✅ 工具调用成功: {tool_key} "
                    f"(耗时: {duration_ms:.2f}ms)"
                )
                
                # 成功返回
                return {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(result, ensure_ascii=False),
                    "success": True,
                    "error": None
                }
                
            except asyncio.TimeoutError:
                # 记录失败指标
                duration_ms = (time.time() - start_time) * 1000
                self._metrics[tool_key].update_failure(duration_ms)
                raise MCPToolServiceError(
                    f"工具调用超时（>{timeout}秒）"
                )
        
        except Exception as e:
            # 记录失败指标
            tool_key = f"{plugin_name}.{tool_name}" if 'plugin_name' in locals() else function_name
            duration_ms = (time.time() - start_time) * 1000
            self._metrics[tool_key].update_failure(duration_ms)
            
            logger.error(
                f"❌ 工具 {function_name} 调用失败: {e}",
                exc_info=True
            )
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": function_name,
                "content": f"工具调用失败: {str(e)}",
                "success": False,
                "error": str(e)
            }
    
    async def _call_tool_with_retry(
        self,
        user_id: str,
        plugin_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float
    ) -> Any:
        """
        带指数退避重试的工具调用
        
        Args:
            user_id: 用户ID
            plugin_name: 插件名称
            tool_name: 工具名称
            arguments: 工具参数
            timeout: 超时时间
            
        Returns:
            工具执行结果
            
        Raises:
            MCPToolServiceError: 工具调用失败
            asyncio.TimeoutError: 调用超时
        """
        last_exception = None
        
        for attempt in range(self._max_retries):
            try:
                # 尝试调用工具
                result = await asyncio.wait_for(
                    mcp_registry.call_tool(
                        user_id=user_id,
                        plugin_name=plugin_name,
                        tool_name=tool_name,
                        arguments=arguments
                    ),
                    timeout=timeout
                )
                
                # 成功则返回
                if attempt > 0:
                    logger.info(
                        f"✅ 重试成功: {plugin_name}.{tool_name} "
                        f"(第{attempt + 1}次尝试)"
                    )
                return result
                
            except asyncio.TimeoutError:
                # 超时不重试，直接抛出
                raise
                
            except Exception as e:
                last_exception = e
                
                # 最后一次尝试失败
                if attempt == self._max_retries - 1:
                    logger.error(
                        f"❌ 重试失败: {plugin_name}.{tool_name} "
                        f"(已尝试{self._max_retries}次): {e}"
                    )
                    raise MCPToolServiceError(
                        f"工具调用失败（已重试{self._max_retries}次）: {str(e)}"
                    )
                
                # 计算指数退避延迟
                delay = min(
                    self._base_retry_delay * (2 ** attempt),
                    self._max_retry_delay
                )
                
                logger.warning(
                    f"⚠️ 工具调用失败，{delay:.1f}秒后重试 "
                    f"(第{attempt + 1}/{self._max_retries}次): "
                    f"{plugin_name}.{tool_name} - {e}"
                )
                
                await asyncio.sleep(delay)
        
        # 理论上不会到这里，但为了类型安全
        raise MCPToolServiceError(f"工具调用失败: {last_exception}")
    
    def get_metrics(self, tool_name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        获取工具调用指标
        
        Args:
            tool_name: 工具名称（可选，获取特定工具的指标）
            
        Returns:
            指标字典
        """
        if tool_name:
            if tool_name in self._metrics:
                metric = self._metrics[tool_name]
                return {
                    tool_name: {
                        "total_calls": metric.total_calls,
                        "success_calls": metric.success_calls,
                        "failed_calls": metric.failed_calls,
                        "success_rate": metric.success_rate,
                        "avg_duration_ms": round(metric.avg_duration_ms, 2),
                        "last_call_time": metric.last_call_time.isoformat() if metric.last_call_time else None
                    }
                }
            return {}
        
        # 返回所有工具的指标
        result = {}
        for tool_key, metric in self._metrics.items():
            result[tool_key] = {
                "total_calls": metric.total_calls,
                "success_calls": metric.success_calls,
                "failed_calls": metric.failed_calls,
                "success_rate": round(metric.success_rate, 3),
                "avg_duration_ms": round(metric.avg_duration_ms, 2),
                "last_call_time": metric.last_call_time.isoformat() if metric.last_call_time else None
            }
        return result
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_entries = len(self._tool_cache)
        total_hits = sum(entry.hit_count for entry in self._tool_cache.values())
        
        return {
            "total_entries": total_entries,
            "total_hits": total_hits,
            "cache_ttl_minutes": self._cache_ttl.total_seconds() / 60,
            "entries": [
                {
                    "key": key,
                    "tools_count": len(entry.tools),
                    "hit_count": entry.hit_count,
                    "expire_time": entry.expire_time.isoformat()
                }
                for key, entry in self._tool_cache.items()
            ]
        }
    
    async def build_tool_context(
        self,
        tool_results: List[Dict[str, Any]],
        format: str = "markdown"
    ) -> str:
        """
        将工具调用结果格式化为上下文文本
        
        Args:
            tool_results: 工具调用结果列表
            format: 输出格式（markdown/json/plain）
        
        Returns:
            格式化的上下文字符串
        """
        if not tool_results:
            return ""
        
        if format == "markdown":
            return self._build_markdown_context(tool_results)
        elif format == "json":
            return json.dumps(tool_results, ensure_ascii=False, indent=2)
        else:  # plain
            return self._build_plain_context(tool_results)
    
    def _build_markdown_context(
        self,
        tool_results: List[Dict[str, Any]]
    ) -> str:
        """构建Markdown格式的工具上下文"""
        lines = ["## 🔧 工具调用结果\n"]
        
        for i, result in enumerate(tool_results, 1):
            tool_name = result.get("name", "unknown")
            success = result.get("success", False)
            content = result.get("content", "")
            
            status_emoji = "✅" if success else "❌"
            lines.append(f"### {status_emoji} {i}. {tool_name}\n")
            
            if success:
                # 尝试美化JSON内容
                try:
                    content_obj = json.loads(content)
                    content = json.dumps(content_obj, ensure_ascii=False, indent=2)
                except:
                    pass
                lines.append(f"```json\n{content}\n```\n")
            else:
                lines.append(f"**错误**: {content}\n")
        
        return "\n".join(lines)
    
    def _build_plain_context(
        self,
        tool_results: List[Dict[str, Any]]
    ) -> str:
        """构建纯文本格式的工具上下文"""
        lines = ["=== 工具调用结果 ===\n"]
        
        for i, result in enumerate(tool_results, 1):
            tool_name = result.get("name", "unknown")
            success = result.get("success", False)
            content = result.get("content", "")
            
            status = "成功" if success else "失败"
            lines.append(f"{i}. {tool_name} - {status}")
            lines.append(f"   结果: {content}\n")
        
        return "\n".join(lines)


# 全局单例
mcp_tool_service = MCPToolService()