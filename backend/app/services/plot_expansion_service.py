"""大纲剧情展开服务 - 将大纲节点展开为多个章节"""
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json

from app.models.outline import Outline
from app.models.project import Project
from app.models.character import Character
from app.models.chapter import Chapter
from app.services.ai_service import AIService
from app.logger import get_logger

logger = get_logger(__name__)


class PlotExpansionService:
    """大纲剧情展开服务"""
    
    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service
    
    async def analyze_outline_for_chapters(
        self,
        outline: Outline,
        project: Project,
        db: AsyncSession,
        target_chapter_count: int = 3,
        expansion_strategy: str = "balanced",
        enable_scene_analysis: bool = True,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: int = 5,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        分析单个大纲,生成多章节规划（支持分批生成）
        
        Args:
            outline: 大纲对象
            project: 项目对象
            db: 数据库会话
            target_chapter_count: 目标生成章节数
            expansion_strategy: 展开策略(balanced/climax/detail)
            enable_scene_analysis: 是否启用场景级分析
            provider: AI提供商
            model: AI模型
            batch_size: 每批生成的章节数（默认5章）
            progress_callback: 进度回调函数(可选)
            
        Returns:
            章节规划列表
        """
        logger.info(f"开始分析大纲 {outline.id}，目标生成 {target_chapter_count} 章")
        
        # 如果章节数较少，直接生成
        if target_chapter_count <= batch_size:
            return await self._generate_chapters_single_batch(
                outline=outline,
                project=project,
                db=db,
                target_chapter_count=target_chapter_count,
                expansion_strategy=expansion_strategy,
                enable_scene_analysis=enable_scene_analysis,
                provider=provider,
                model=model
            )
        
        # 章节数较多，分批生成
        logger.info(f"章节数({target_chapter_count})超过批次大小({batch_size})，启用分批生成")
        return await self._generate_chapters_in_batches(
            outline=outline,
            project=project,
            db=db,
            target_chapter_count=target_chapter_count,
            expansion_strategy=expansion_strategy,
            enable_scene_analysis=enable_scene_analysis,
            provider=provider,
            model=model,
            batch_size=batch_size,
            progress_callback=progress_callback
        )
    
    async def _generate_chapters_single_batch(
        self,
        outline: Outline,
        project: Project,
        db: AsyncSession,
        target_chapter_count: int,
        expansion_strategy: str,
        enable_scene_analysis: bool,
        provider: Optional[str],
        model: Optional[str]
    ) -> List[Dict[str, Any]]:
        """单批次生成章节规划"""
        # 获取角色信息
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = characters_result.scalars().all()
        characters_info = "\n".join([
            f"- {char.name} ({'组织' if char.is_organization else '角色'}, {char.role_type}): "
            f"{char.personality[:100] if char.personality else '暂无描述'}"
            for char in characters
        ])
        
        # 获取大纲上下文（前后大纲）
        context_info = await self._get_outline_context(outline, project.id, db)
        
        # 构建分析提示词
        prompt = self._build_expansion_prompt(
            outline=outline,
            project=project,
            characters_info=characters_info,
            context_info=context_info,
            target_chapter_count=target_chapter_count,
            expansion_strategy=expansion_strategy,
            enable_scene_analysis=enable_scene_analysis
        )
        
        # 调用AI生成章节规划
        logger.info(f"调用AI生成章节规划...")
        ai_response = await self.ai_service.generate_text(
            prompt=prompt,
            provider=provider,
            model=model
        )
        
        # 提取内容
        ai_content = ai_response.get("content", "") if isinstance(ai_response, dict) else ai_response
        
        # 解析AI响应
        chapter_plans = self._parse_expansion_response(ai_content, outline.id)
        
        logger.info(f"成功生成 {len(chapter_plans)} 个章节规划")
        return chapter_plans
    
    async def _generate_chapters_in_batches(
        self,
        outline: Outline,
        project: Project,
        db: AsyncSession,
        target_chapter_count: int,
        expansion_strategy: str,
        enable_scene_analysis: bool,
        provider: Optional[str],
        model: Optional[str],
        batch_size: int,
        progress_callback: Optional[callable]
    ) -> List[Dict[str, Any]]:
        """分批生成章节规划"""
        # 计算批次数
        total_batches = (target_chapter_count + batch_size - 1) // batch_size
        logger.info(f"分批生成计划: 总共{target_chapter_count}章，分{total_batches}批，每批{batch_size}章")
        
        # 获取角色信息（所有批次共用）
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = characters_result.scalars().all()
        characters_info = "\n".join([
            f"- {char.name} ({'组织' if char.is_organization else '角色'}, {char.role_type}): "
            f"{char.personality[:100] if char.personality else '暂无描述'}"
            for char in characters
        ])
        
        # 获取大纲上下文
        context_info = await self._get_outline_context(outline, project.id, db)
        
        all_chapter_plans = []
        
        for batch_num in range(total_batches):
            # 计算当前批次的章节数
            remaining_chapters = target_chapter_count - len(all_chapter_plans)
            current_batch_size = min(batch_size, remaining_chapters)
            current_start_index = len(all_chapter_plans) + 1
            
            logger.info(f"开始生成第{batch_num + 1}/{total_batches}批，章节范围: {current_start_index}-{current_start_index + current_batch_size - 1}")
            
            # 回调通知进度
            if progress_callback:
                await progress_callback(batch_num + 1, total_batches, current_start_index, current_batch_size)
            
            # 构建当前批次的提示词（包含已生成章节的上下文）
            prompt = self._build_batch_expansion_prompt(
                outline=outline,
                project=project,
                characters_info=characters_info,
                context_info=context_info,
                target_chapter_count=current_batch_size,
                expansion_strategy=expansion_strategy,
                enable_scene_analysis=enable_scene_analysis,
                start_index=current_start_index,
                previous_chapters=all_chapter_plans,
                total_chapters=target_chapter_count
            )
            
            # 调用AI生成当前批次
            logger.info(f"调用AI生成第{batch_num + 1}批...")
            ai_response = await self.ai_service.generate_text(
                prompt=prompt,
                provider=provider,
                model=model
            )
            
            # 提取内容
            ai_content = ai_response.get("content", "") if isinstance(ai_response, dict) else ai_response
            
            # 解析AI响应
            batch_plans = self._parse_expansion_response(ai_content, outline.id)
            
            # 调整sub_index以保持连续性
            for i, plan in enumerate(batch_plans):
                plan["sub_index"] = current_start_index + i
            
            all_chapter_plans.extend(batch_plans)
            
            logger.info(f"第{batch_num + 1}批生成完成，本批生成{len(batch_plans)}章，累计{len(all_chapter_plans)}章")
        
        logger.info(f"分批生成完成，共生成 {len(all_chapter_plans)} 个章节规划")
        return all_chapter_plans
    
    async def batch_expand_outlines(
        self,
        project_id: str,
        db: AsyncSession,
        ai_service: AIService,
        target_chapters_per_outline: int = 3,
        expansion_strategy: str = "balanced",
        provider: Optional[str] = None,
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        批量展开所有大纲为章节
        
        Returns:
            {
                "total_outlines": 总大纲数,
                "total_chapters_planned": 规划的总章节数,
                "expansions": [每个大纲的展开结果]
            }
        """
        logger.info(f"开始批量展开项目 {project_id} 的所有大纲")
        
        # 获取项目
        project_result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise ValueError(f"项目 {project_id} 不存在")
        
        # 获取所有大纲
        outlines_result = await db.execute(
            select(Outline)
            .where(Outline.project_id == project_id)
            .order_by(Outline.order_index)
        )
        outlines = outlines_result.scalars().all()
        
        if not outlines:
            logger.warning(f"项目 {project_id} 没有大纲")
            return {
                "total_outlines": 0,
                "total_chapters_planned": 0,
                "expansions": []
            }
        
        # 逐个展开大纲
        expansions = []
        total_chapters = 0
        
        for outline in outlines:
            try:
                chapter_plans = await self.analyze_outline_for_chapters(
                    outline=outline,
                    project=project,
                    db=db,
                    target_chapter_count=target_chapters_per_outline,
                    expansion_strategy=expansion_strategy,
                    provider=provider,
                    model=model
                )
                
                expansions.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "chapter_plans": chapter_plans,
                    "chapter_count": len(chapter_plans)
                })
                
                total_chapters += len(chapter_plans)
                logger.info(f"大纲 {outline.title} 展开为 {len(chapter_plans)} 章")
                
            except Exception as e:
                logger.error(f"展开大纲 {outline.id} 失败: {str(e)}")
                expansions.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "error": str(e),
                    "chapter_count": 0
                })
        
        result = {
            "total_outlines": len(outlines),
            "total_chapters_planned": total_chapters,
            "expansions": expansions
        }
        
        logger.info(f"批量展开完成: {len(outlines)} 个大纲 → {total_chapters} 个章节规划")
        return result
    
    async def create_chapters_from_plans(
        self,
        outline_id: str,
        chapter_plans: List[Dict[str, Any]],
        project_id: str,
        db: AsyncSession,
        start_chapter_number: int = None
    ) -> List[Chapter]:
        """
        根据章节规划创建实际的章节记录
        
        Args:
            outline_id: 大纲ID
            chapter_plans: 章节规划列表
            project_id: 项目ID
            db: 数据库会话
            start_chapter_number: 起始章节号（如果为None，则自动计算）
            
        Returns:
            创建的章节列表
        """
        logger.info(f"根据规划创建 {len(chapter_plans)} 个章节记录")
        
        # 如果没有指定起始章节号，根据大纲顺序自动计算
        if start_chapter_number is None:
            # 1. 获取当前大纲信息
            outline_result = await db.execute(
                select(Outline).where(Outline.id == outline_id)
            )
            current_outline = outline_result.scalar_one_or_none()
            
            if not current_outline:
                raise ValueError(f"大纲 {outline_id} 不存在")
            
            # 2. 查询所有在当前大纲之前的大纲（按order_index排序）
            prev_outlines_result = await db.execute(
                select(Outline)
                .where(
                    Outline.project_id == project_id,
                    Outline.order_index < current_outline.order_index
                )
                .order_by(Outline.order_index)
            )
            prev_outlines = prev_outlines_result.scalars().all()
            
            # 3. 计算前面所有大纲已展开的章节总数
            total_prev_chapters = 0
            for prev_outline in prev_outlines:
                count_result = await db.execute(
                    select(func.count(Chapter.id))
                    .where(
                        Chapter.project_id == project_id,
                        Chapter.outline_id == prev_outline.id
                    )
                )
                total_prev_chapters += count_result.scalar() or 0
            
            # 4. 起始章节号 = 前面所有大纲的章节数 + 1
            start_chapter_number = total_prev_chapters + 1
            logger.info(f"自动计算起始章节号: {start_chapter_number} (基于大纲order_index={current_outline.order_index}, 前置章节数={total_prev_chapters})")
        
        chapters = []
        for idx, plan in enumerate(chapter_plans):
            # 保存完整的展开规划数据（JSON格式）
            expansion_plan_json = json.dumps({
                "key_events": plan.get("key_events", []),
                "character_focus": plan.get("character_focus", []),
                "emotional_tone": plan.get("emotional_tone", ""),
                "narrative_goal": plan.get("narrative_goal", ""),
                "conflict_type": plan.get("conflict_type", ""),
                "estimated_words": plan.get("estimated_words", 3000),
                "scenes": plan.get("scenes", []) if plan.get("scenes") else None
            }, ensure_ascii=False)
            
            chapter = Chapter(
                project_id=project_id,
                outline_id=outline_id,
                chapter_number=start_chapter_number + idx,
                sub_index=plan.get("sub_index", idx + 1),
                title=plan.get("title", f"第{start_chapter_number + idx}章"),
                summary=plan.get("plot_summary", ""),
                expansion_plan=expansion_plan_json,
                status="draft"
            )
            db.add(chapter)
            chapters.append(chapter)
        
        await db.commit()
        
        for chapter in chapters:
            await db.refresh(chapter)
        
        logger.info(f"成功创建 {len(chapters)} 个章节记录（已保存展开规划数据）")
        
        # 重新排序当前大纲之后的所有章节
        await self._renumber_subsequent_chapters(
            project_id=project_id,
            current_outline_id=outline_id,
            db=db
        )
        
        return chapters
    
    async def _get_outline_context(
        self,
        outline: Outline,
        project_id: str,
        db: AsyncSession
    ) -> str:
        """获取大纲的上下文（前后大纲）"""
        # 获取前一个大纲
        prev_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index < outline.order_index
            )
            .order_by(Outline.order_index.desc())
            .limit(1)
        )
        prev_outline = prev_result.scalar_one_or_none()
        
        # 获取后一个大纲
        next_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index > outline.order_index
            )
            .order_by(Outline.order_index)
            .limit(1)
        )
        next_outline = next_result.scalar_one_or_none()
        
        context = ""
        if prev_outline:
            context += f"【前一节】{prev_outline.title}: {prev_outline.content[:200]}...\n\n"
        if next_outline:
            context += f"【后一节】{next_outline.title}: {next_outline.content[:200]}...\n"
        
        return context if context else "（无前后文）"
    
    def _build_expansion_prompt(
        self,
        outline: Outline,
        project: Project,
        characters_info: str,
        context_info: str,
        target_chapter_count: int,
        expansion_strategy: str,
        enable_scene_analysis: bool
    ) -> str:
        """构建大纲展开提示词"""
        
        strategy_desc = {
            "balanced": "均衡展开：每章剧情量相当，节奏平稳",
            "climax": "高潮重点：重点章节剧情丰富，其他章节简洁过渡",
            "detail": "细节丰富：每章都深入描写，场景和情感细腻"
        }
        
        strategy_instruction = strategy_desc.get(expansion_strategy, strategy_desc["balanced"])
        
        # 场景字段（避免f-string中的反斜杠）
        scene_field = ',\n    "main_scenes": ["场景1", "场景2"]' if enable_scene_analysis else ''
        
        scene_instruction = ""
        if enable_scene_analysis:
            scene_instruction = """
5. 场景分析（每章需包含）：
   - 主要场景地点
   - 场景氛围
   - 关键道具/环境元素
"""
        
        prompt = f"""你是专业的小说情节架构师。请分析以下大纲节点，将其展开为 {target_chapter_count} 个章节的详细规划。

【项目信息】
小说名称：{project.title}
类型：{project.genre or '通用'}
主题：{project.theme or '未设定'}
叙事视角：{project.narrative_perspective or '第三人称'}

【世界观背景】
时间背景：{project.world_time_period or '未设定'}
地理位置：{project.world_location or '未设定'}
氛围基调：{project.world_atmosphere or '未设定'}

【角色信息】
{characters_info or '暂无角色'}

【当前大纲节点 - 展开对象】
序号：第 {outline.order_index} 节
标题：{outline.title}
内容：{outline.content}

【上下文参考】
{context_info}

【展开策略】
{strategy_instruction}

【⚠️ 重要约束 - 必须严格遵守】
1. **内容边界约束**：
   - ✅ 只能展开【当前大纲节点】中明确描述的内容
   - ❌ 绝对不能推进到后续大纲的内容（如果有【后一节】信息）
   - ❌ 不要让剧情快速推进，要深化而非跨越
   
2. **展开原则**：
   - 将当前大纲的单一事件拆解为多个细节丰富的章节
   - 深入挖掘情感、心理、环境、对话等细节
   - 放慢叙事节奏，让读者充分体验当前阶段的剧情
   - 每个章节都应该是当前大纲内容的不同侧面或阶段
   
3. **如何避免剧情越界**：
   - 如果当前大纲描述"主角遇到困境"，展开时应详写困境的发现、分析、情感冲击等
   - 不要直接写到"解决困境"，除非原大纲明确包含解决过程
   - 如果看到【后一节】的内容，那些是禁区，绝不提前展开

【任务要求】
1. 深度分析该大纲的剧情容量和叙事节奏
2. 识别关键剧情点、冲突点和情感转折点（仅限当前大纲范围内）
3. 将大纲拆解为 {target_chapter_count} 个章节，每章需包含：
   - sub_index: 子章节序号（1, 2, 3...）
   - title: 章节标题（体现该章核心冲突或情感）
   - plot_summary: 剧情摘要（200-300字，详细描述该章发生的事件，仅限当前大纲内容）
   - key_events: 关键事件列表（3-5个关键剧情点，必须在当前大纲范围内）
   - character_focus: 角色焦点（主要涉及的角色名称）
   - emotional_tone: 情感基调（如：紧张、温馨、悲伤、激动等）
   - narrative_goal: 叙事目标（该章要达成的叙事效果）
   - conflict_type: 冲突类型（如：内心挣扎、人际冲突、环境挑战等）
   - estimated_words: 预计字数（建议2000-5000字）
{scene_instruction}
4. 确保章节间：
   - 衔接自然流畅
   - 剧情递进合理（但不超出当前大纲边界）
   - 节奏张弛有度
   - 每章都有明确的叙事价值
   - 最后一章结束时，剧情发展程度应恰好完成当前大纲描述的内容，不多不少

【输出格式】
请严格按照以下JSON数组格式输出，不要添加任何其他文字：
[
  {{
    "sub_index": 1,
    "title": "章节标题",
    "plot_summary": "该章详细剧情摘要...",
    "key_events": ["关键事件1", "关键事件2", "关键事件3"],
    "character_focus": ["角色A", "角色B"],
    "emotional_tone": "情感基调",
    "narrative_goal": "叙事目标",
    "conflict_type": "冲突类型",
    "estimated_words": 3000{scene_field}
  }}
]

请开始分析并生成章节规划：
"""
        return prompt
    
    def _build_batch_expansion_prompt(
        self,
        outline: Outline,
        project: Project,
        characters_info: str,
        context_info: str,
        target_chapter_count: int,
        expansion_strategy: str,
        enable_scene_analysis: bool,
        start_index: int,
        previous_chapters: List[Dict[str, Any]],
        total_chapters: int
    ) -> str:
        """构建分批展开提示词"""
        
        strategy_desc = {
            "balanced": "均衡展开：每章剧情量相当，节奏平稳",
            "climax": "高潮重点：重点章节剧情丰富，其他章节简洁过渡",
            "detail": "细节丰富：每章都深入描写，场景和情感细腻"
        }
        
        strategy_instruction = strategy_desc.get(expansion_strategy, strategy_desc["balanced"])
        
        # 场景字段
        scene_field = ',\n    "main_scenes": ["场景1", "场景2"]' if enable_scene_analysis else ''
        
        scene_instruction = ""
        if enable_scene_analysis:
            scene_instruction = """
5. 场景分析（每章需包含）：
   - 主要场景地点
   - 场景氛围
   - 关键道具/环境元素
"""
        
        # 构建已生成章节的摘要
        previous_context = ""
        if previous_chapters:
            previous_summaries = []
            for ch in previous_chapters[-3:]:  # 只显示最近3章
                previous_summaries.append(
                    f"第{ch['sub_index']}节《{ch['title']}》: {ch['plot_summary'][:100]}..."
                )
            previous_context = f"""
【已生成章节概要】（接续生成，注意衔接）
{chr(10).join(previous_summaries)}

⚠️ 当前是第{start_index}-{start_index + target_chapter_count - 1}节（共{total_chapters}节中的一部分）
"""
        
        prompt = f"""你是专业的小说情节架构师。请继续分析以下大纲节点，将其展开为第{start_index}-{start_index + target_chapter_count - 1}节（共{target_chapter_count}个章节）的详细规划。

【项目信息】
小说名称：{project.title}
类型：{project.genre or '通用'}
主题：{project.theme or '未设定'}
叙事视角：{project.narrative_perspective or '第三人称'}

【世界观背景】
时间背景：{project.world_time_period or '未设定'}
地理位置：{project.world_location or '未设定'}
氛围基调：{project.world_atmosphere or '未设定'}

【角色信息】
{characters_info or '暂无角色'}

【当前大纲节点 - 展开对象】
序号：第 {outline.order_index} 节
标题：{outline.title}
内容：{outline.content}

【上下文参考】
{context_info}
{previous_context}

【展开策略】
{strategy_instruction}

【⚠️ 重要约束 - 必须严格遵守】
1. **内容边界约束**：
   - ✅ 只能展开【当前大纲节点】中明确描述的内容
   - ❌ 绝对不能推进到后续大纲的内容（如果有【后一节】信息）
   - ❌ 不要让剧情快速推进，要深化而非跨越
   
2. **分批连续性约束**：
   - 这是第{start_index}-{start_index + target_chapter_count - 1}节，是整个展开的一部分
   - 必须与前面已生成的章节自然衔接
   - 从第{start_index}节开始编号（sub_index从{start_index}开始）
   - 继续深化当前大纲的内容，保持叙事连贯性
   
3. **展开原则**：
   - 将当前大纲的单一事件拆解为多个细节丰富的章节
   - 深入挖掘情感、心理、环境、对话等细节
   - 放慢叙事节奏，让读者充分体验当前阶段的剧情
   - 每个章节都应该是当前大纲内容的不同侧面或阶段

【任务要求】
1. 深度分析该大纲的剧情容量和叙事节奏
2. 识别关键剧情点、冲突点和情感转折点（仅限当前大纲范围内）
3. 生成第{start_index}-{start_index + target_chapter_count - 1}节的章节规划，每章需包含：
   - sub_index: 子章节序号（从{start_index}开始）
   - title: 章节标题（体现该章核心冲突或情感）
   - plot_summary: 剧情摘要（200-300字，详细描述该章发生的事件）
   - key_events: 关键事件列表（3-5个关键剧情点）
   - character_focus: 角色焦点（主要涉及的角色名称）
   - emotional_tone: 情感基调（如：紧张、温馨、悲伤、激动等）
   - narrative_goal: 叙事目标（该章要达成的叙事效果）
   - conflict_type: 冲突类型（如：内心挣扎、人际冲突、环境挑战等）
   - estimated_words: 预计字数（建议2000-5000字）
{scene_instruction}
4. 确保章节间：
   - 与前面章节衔接自然流畅
   - 剧情递进合理（但不超出当前大纲边界）
   - 节奏张弛有度
   - 每章都有明确的叙事价值

【输出格式】
请严格按照以下JSON数组格式输出，不要添加任何其他文字：
[
  {{
    "sub_index": {start_index},
    "title": "章节标题",
    "plot_summary": "该章详细剧情摘要...",
    "key_events": ["关键事件1", "关键事件2", "关键事件3"],
    "character_focus": ["角色A", "角色B"],
    "emotional_tone": "情感基调",
    "narrative_goal": "叙事目标",
    "conflict_type": "冲突类型",
    "estimated_words": 3000{scene_field}
  }}
]

请开始分析并生成第{start_index}-{start_index + target_chapter_count - 1}节的章节规划：
"""
        return prompt
    
    def _parse_expansion_response(
        self,
        ai_response: str,
        outline_id: str
    ) -> List[Dict[str, Any]]:
        """解析AI的展开响应"""
        try:
            # 清理响应文本
            cleaned_text = ai_response.strip()
            if cleaned_text.startswith('```json'):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith('```'):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith('```'):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            # 解析JSON
            chapter_plans = json.loads(cleaned_text)
            
            # 确保是列表
            if not isinstance(chapter_plans, list):
                chapter_plans = [chapter_plans]
            
            # 为每个章节规划添加outline_id
            for plan in chapter_plans:
                plan["outline_id"] = outline_id
            
            return chapter_plans
            
        except json.JSONDecodeError as e:
            logger.error(f"解析AI响应失败: {e}, 响应内容: {ai_response[:500]}")
            # 返回一个基础规划
            return [{
                "outline_id": outline_id,
                "sub_index": 1,
                "title": "AI解析失败的默认章节",
                "plot_summary": ai_response[:500],
                "key_events": ["解析失败"],
                "character_focus": [],
                "emotional_tone": "未知",
                "narrative_goal": "需要重新生成",
                "conflict_type": "未知",
                "estimated_words": 3000
            }]


    async def _renumber_subsequent_chapters(
        self,
        project_id: str,
        current_outline_id: str,
        db: AsyncSession
    ):
        """
        重新计算当前大纲之后所有大纲的章节序号
        
        Args:
            project_id: 项目ID
            current_outline_id: 当前大纲ID
            db: 数据库会话
        """
        logger.info(f"开始重新排序大纲 {current_outline_id} 之后的所有章节")
        
        # 1. 获取当前大纲信息
        current_outline_result = await db.execute(
            select(Outline).where(Outline.id == current_outline_id)
        )
        current_outline = current_outline_result.scalar_one_or_none()
        
        if not current_outline:
            logger.warning(f"大纲 {current_outline_id} 不存在，跳过重新排序")
            return
        
        # 2. 获取当前大纲及之后的所有大纲（按order_index排序）
        subsequent_outlines_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index >= current_outline.order_index
            )
            .order_by(Outline.order_index)
        )
        subsequent_outlines = subsequent_outlines_result.scalars().all()
        
        # 3. 计算每个大纲的起始章节号
        current_chapter_number = 1
        
        # 先计算前面大纲的章节总数
        prev_outlines_result = await db.execute(
            select(Outline)
            .where(
                Outline.project_id == project_id,
                Outline.order_index < current_outline.order_index
            )
            .order_by(Outline.order_index)
        )
        prev_outlines = prev_outlines_result.scalars().all()
        
        for prev_outline in prev_outlines:
            count_result = await db.execute(
                select(func.count(Chapter.id))
                .where(
                    Chapter.project_id == project_id,
                    Chapter.outline_id == prev_outline.id
                )
            )
            current_chapter_number += count_result.scalar() or 0
        
        # 4. 逐个大纲更新章节序号
        updated_count = 0
        for outline in subsequent_outlines:
            # 获取该大纲的所有章节（按sub_index排序）
            chapters_result = await db.execute(
                select(Chapter)
                .where(
                    Chapter.project_id == project_id,
                    Chapter.outline_id == outline.id
                )
                .order_by(Chapter.sub_index)
            )
            chapters = chapters_result.scalars().all()
            
            # 更新每个章节的chapter_number
            for chapter in chapters:
                if chapter.chapter_number != current_chapter_number:
                    logger.debug(f"更新章节 {chapter.id}: {chapter.chapter_number} -> {current_chapter_number}")
                    chapter.chapter_number = current_chapter_number
                    updated_count += 1
                current_chapter_number += 1
        
        # 5. 提交更新
        await db.commit()
        logger.info(f"重新排序完成，共更新 {updated_count} 个章节的序号")


# 工厂函数
def create_plot_expansion_service(ai_service: AIService) -> PlotExpansionService:
    """创建剧情展开服务实例"""
    return PlotExpansionService(ai_service)