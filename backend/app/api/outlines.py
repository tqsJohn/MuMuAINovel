"""大纲管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from typing import List, AsyncGenerator, Dict, Any
import json

from app.database import get_db
from app.models.outline import Outline
from app.models.project import Project
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.generation_history import GenerationHistory
from app.schemas.outline import (
    OutlineCreate,
    OutlineUpdate,
    OutlineResponse,
    OutlineListResponse,
    OutlineGenerateRequest,
    OutlineExpansionRequest,
    OutlineExpansionResponse,
    BatchOutlineExpansionRequest,
    BatchOutlineExpansionResponse,
    CreateChaptersFromPlansRequest,
    CreateChaptersFromPlansResponse
)
from app.services.ai_service import AIService
from app.services.prompt_service import prompt_service
from app.services.memory_service import memory_service
from app.services.plot_expansion_service import PlotExpansionService
from app.logger import get_logger
from app.api.settings import get_user_ai_service
from app.utils.sse_response import SSEResponse, create_sse_response

router = APIRouter(prefix="/outlines", tags=["大纲管理"])
logger = get_logger(__name__)


async def verify_project_access(project_id: str, user_id: str, db: AsyncSession) -> Project:
    """
    验证用户是否有权访问指定项目
    
    Args:
        project_id: 项目ID
        user_id: 用户ID
        db: 数据库会话
        
    Returns:
        Project: 项目对象
        
    Raises:
        HTTPException: 401 未登录，404 项目不存在或无权访问
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id
        )
    )
    project = result.scalar_one_or_none()
    
    if not project:
        logger.warning(f"项目访问被拒绝: project_id={project_id}, user_id={user_id}")
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    
    return project


@router.post("", response_model=OutlineResponse, summary="创建大纲")
async def create_outline(
    outline: OutlineCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """创建新的章节大纲（不自动创建章节，需通过展开功能生成章节）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(outline.project_id, user_id, db)
    
    # 创建大纲
    db_outline = Outline(**outline.model_dump())
    db.add(db_outline)
    
    await db.commit()
    await db.refresh(db_outline)
    return db_outline


@router.get("", response_model=OutlineListResponse, summary="获取大纲列表")
async def get_outlines(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的所有大纲"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 获取总数
    count_result = await db.execute(
        select(func.count(Outline.id)).where(Outline.project_id == project_id)
    )
    total = count_result.scalar_one()
    
    # 获取大纲列表
    result = await db.execute(
        select(Outline)
        .where(Outline.project_id == project_id)
        .order_by(Outline.order_index)
    )
    outlines = result.scalars().all()
    
    return OutlineListResponse(total=total, items=outlines)


@router.get("/project/{project_id}", response_model=OutlineListResponse, summary="获取项目的所有大纲")
async def get_project_outlines(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的所有大纲（路径参数版本）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 获取总数
    count_result = await db.execute(
        select(func.count(Outline.id)).where(Outline.project_id == project_id)
    )
    total = count_result.scalar_one()
    
    # 获取大纲列表
    result = await db.execute(
        select(Outline)
        .where(Outline.project_id == project_id)
        .order_by(Outline.order_index)
    )
    outlines = result.scalars().all()
    
    return OutlineListResponse(total=total, items=outlines)


@router.get("/{outline_id}", response_model=OutlineResponse, summary="获取大纲详情")
async def get_outline(
    outline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取大纲详情"""
    result = await db.execute(
        select(Outline).where(Outline.id == outline_id)
    )
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(outline.project_id, user_id, db)
    
    return outline


@router.put("/{outline_id}", response_model=OutlineResponse, summary="更新大纲")
async def update_outline(
    outline_id: str,
    outline_update: OutlineUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新大纲信息并同步更新structure字段"""
    result = await db.execute(
        select(Outline).where(Outline.id == outline_id)
    )
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(outline.project_id, user_id, db)
    
    # 更新字段
    update_data = outline_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(outline, field, value)
    
    # 如果修改了content或title，同步更新structure字段
    if 'content' in update_data or 'title' in update_data:
        try:
            # 尝试解析现有的structure
            if outline.structure:
                structure_data = json.loads(outline.structure)
            else:
                structure_data = {}
            
            # 更新structure中的对应字段
            if 'title' in update_data:
                structure_data['title'] = outline.title
            if 'content' in update_data:
                structure_data['summary'] = outline.content
                structure_data['content'] = outline.content
            
            # 保存更新后的structure
            outline.structure = json.dumps(structure_data, ensure_ascii=False)
            logger.info(f"同步更新大纲 {outline_id} 的structure字段")
        except json.JSONDecodeError:
            logger.warning(f"大纲 {outline_id} 的structure字段格式错误，跳过更新")
    
    await db.commit()
    await db.refresh(outline)
    return outline


@router.delete("/{outline_id}", summary="删除大纲")
async def delete_outline(
    outline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除大纲，同时删除该大纲对应的所有章节"""
    result = await db.execute(
        select(Outline).where(Outline.id == outline_id)
    )
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(outline.project_id, user_id, db)
    
    project_id = outline.project_id
    deleted_order = outline.order_index
    
    # 删除该大纲对应的所有章节（通过outline_id关联）
    delete_result = await db.execute(
        delete(Chapter).where(Chapter.outline_id == outline_id)
    )
    deleted_chapters_count = delete_result.rowcount
    
    logger.info(f"删除大纲 {outline_id}，同时删除了 {deleted_chapters_count} 个关联章节")
    
    # 删除大纲
    await db.delete(outline)
    
    # 重新排序后续的大纲（序号-1）
    result = await db.execute(
        select(Outline).where(
            Outline.project_id == project_id,
            Outline.order_index > deleted_order
        )
    )
    subsequent_outlines = result.scalars().all()
    
    for o in subsequent_outlines:
        o.order_index -= 1
    
    await db.commit()
    
    return {
        "message": "大纲删除成功",
        "deleted_chapters": deleted_chapters_count
    }


@router.post("/generate", response_model=OutlineListResponse, summary="AI生成/续写大纲")
async def generate_outline(
    request: OutlineGenerateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    使用AI生成或续写小说大纲 - 智能模式
    
    支持三种模式：
    - auto: 自动判断（无大纲→新建，有大纲→续写）
    - new: 强制全新生成
    - continue: 强制续写模式
    """
    # 验证用户权限
    user_id = getattr(http_request.state, 'user_id', None)
    project = await verify_project_access(request.project_id, user_id, db)
    
    try:
        # 获取现有大纲（强制从数据库获取最新数据，包括用户手动修改的内容）
        existing_result = await db.execute(
            select(Outline)
            .where(Outline.project_id == request.project_id)
            .order_by(Outline.order_index)
            .execution_options(populate_existing=True)
        )
        existing_outlines = existing_result.scalars().all()
        
        # 判断实际执行模式
        actual_mode = request.mode
        if actual_mode == "auto":
            actual_mode = "continue" if existing_outlines else "new"
            logger.info(f"自动判断模式：{'续写' if existing_outlines else '新建'}")
        
        # 模式：全新生成
        if actual_mode == "new":
            return await _generate_new_outline(
                request, project, db, user_ai_service
            )
        
        # 模式：续写
        elif actual_mode == "continue":
            if not existing_outlines:
                raise HTTPException(
                    status_code=400,
                    detail="续写模式需要已有大纲，当前项目没有大纲"
                )
            
            # 获取用户ID用于记忆检索
            user_id = getattr(http_request.state, "user_id", "system")
            return await _continue_outline(
                request, project, existing_outlines, db, user_ai_service, user_id
            )
        
        else:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的模式: {request.mode}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成大纲失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成大纲失败: {str(e)}")


async def _generate_new_outline(
    request: OutlineGenerateRequest,
    project: Project,
    db: AsyncSession,
    user_ai_service: AIService
) -> OutlineListResponse:
    """全新生成大纲（MCP增强版）"""
    logger.info(f"全新生成大纲 - 项目: {project.id}, enable_mcp: {request.enable_mcp}")
    
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
    
    # 🔍 MCP工具增强：收集情节设计参考资料
    mcp_reference_materials = ""
    if request.enable_mcp:
        try:
            logger.info(f"🔍 尝试使用MCP工具收集大纲设计参考资料...")
            
            # 构建资料收集查询
            planning_query = f"""你正在为小说《{project.title}》设计完整大纲。
项目信息：
- 主题：{request.theme or project.theme}
- 类型：{request.genre or project.genre}
- 章节数：{request.chapter_count}
- 叙事视角：{request.narrative_perspective}
- 目标字数：{request.target_words}

世界观设定：
- 时间背景：{project.world_time_period or '未设定'}
- 地理位置：{project.world_location or '未设定'}
- 氛围基调：{project.world_atmosphere or '未设定'}

角色信息：
{characters_info or '暂无角色'}

请搜索：
1. 该类型小说的经典情节结构和套路
2. 适合该主题的冲突设计思路
3. 符合世界观的情节元素和场景设计灵感

请有针对性地查询1-2个最关键的问题。"""
            
            # 调用MCP增强的AI（非流式，最多2轮工具调用）
            planning_result = await user_ai_service.generate_text_with_mcp(
                prompt=planning_query,
                user_id="system",  # 全新生成时可能没有用户上下文
                db_session=db,
                enable_mcp=True,
                max_tool_rounds=2,
                tool_choice="auto",
                provider=None,
                model=None
            )
            
            # 提取参考资料
            if planning_result.get("tool_calls_made", 0) > 0:
                mcp_reference_materials = planning_result.get("content", "")
                logger.info(f"📚 MCP工具收集参考资料：{len(mcp_reference_materials)} 字符")
            else:
                logger.info(f"ℹ️ MCP工具未进行调用，继续正常生成")
        except Exception as e:
            logger.warning(f"⚠️ MCP工具调用失败，继续使用常规模式: {str(e)}")
            mcp_reference_materials = ""
    
    # 使用完整提示词（插入MCP参考资料）
    prompt = prompt_service.get_complete_outline_prompt(
        title=project.title,
        theme=request.theme or project.theme or "未设定",
        genre=request.genre or project.genre or "通用",
        chapter_count=request.chapter_count,
        narrative_perspective=request.narrative_perspective,
        target_words=request.target_words,
        time_period=project.world_time_period or "未设定",
        location=project.world_location or "未设定",
        atmosphere=project.world_atmosphere or "未设定",
        rules=project.world_rules or "未设定",
        characters_info=characters_info or "暂无角色信息",
        requirements=request.requirements or "",
        mcp_references=mcp_reference_materials
    )
    
    # 调用AI生成大纲
    ai_response = await user_ai_service.generate_text(
        prompt=prompt,
        provider=request.provider,
        model=request.model
    )
    
    # 提取内容（generate_text返回字典）
    ai_content = ai_response.get("content", "") if isinstance(ai_response, dict) else ai_response
    
    # 解析响应
    outline_data = _parse_ai_response(ai_content)
    
    # 全新生成模式：必须删除旧大纲（章节不自动删除，由用户手动管理）
    # 注意：这是"new"模式的核心逻辑，应该始终删除旧数据
    logger.info(f"删除项目 {project.id} 的旧大纲")
    await db.execute(
        delete(Outline).where(Outline.project_id == project.id)
    )
    
    # 保存新大纲
    outlines = await _save_outlines(
        project.id, outline_data, db, start_index=1
    )
    
    # 记录历史
    history = GenerationHistory(
        project_id=project.id,
        prompt=prompt,
        generated_content=json.dumps(ai_response, ensure_ascii=False) if isinstance(ai_response, dict) else ai_response,
        model=request.model or "default"
    )
    db.add(history)
    
    await db.commit()
    
    for outline in outlines:
        await db.refresh(outline)
    
    logger.info(f"全新生成完成 - {len(outlines)} 章")
    return OutlineListResponse(total=len(outlines), items=outlines)


async def _build_smart_outline_context(
    latest_outlines: List[Outline],
    user_id: str,
    project_id: str
) -> dict:
    """
    智能构建大纲续写上下文（支持海量大纲场景）
    
    策略：
    1. 故事骨架：每50章采样1章（仅标题）
    2. 近期概要：最近20章（标题+简要）
    3. 最近详细：最近2章（完整内容）
    
    Args:
        latest_outlines: 所有已有大纲列表
        user_id: 用户ID
        project_id: 项目ID
        
    Returns:
        包含压缩后上下文的字典
    """
    total_count = len(latest_outlines)
    
    context = {
        'story_skeleton': '',      # 故事骨架（标题列表）
        'recent_summary': '',      # 近期概要（标题+内容前50字）
        'recent_detail': '',       # 最近详细（完整内容）
        'stats': {
            'total': total_count,
            'skeleton_samples': 0,
            'recent_summaries': 0,
            'recent_details': 0
        }
    }
    
    try:
        # 1. 故事骨架（每50章采样，仅标题）
        if total_count > 50:
            sample_interval = 50
            skeleton_indices = list(range(0, total_count, sample_interval))
            skeleton_titles = [
                f"第{latest_outlines[idx].order_index}章: {latest_outlines[idx].title}"
                for idx in skeleton_indices
            ]
            context['story_skeleton'] = "【故事骨架】\n" + "\n".join(skeleton_titles)
            context['stats']['skeleton_samples'] = len(skeleton_titles)
            logger.info(f"  ✅ 故事骨架：采样{len(skeleton_titles)}章标题")
        
        # 2. 近期概要（最近20章，标题+内容前50字）
        recent_summary_count = min(20, total_count)
        if recent_summary_count > 2:  # 排除最后2章（它们会完整展示）
            recent_for_summary = latest_outlines[-recent_summary_count:-2]
            recent_summaries = [
                f"第{o.order_index}章《{o.title}》: {o.content[:50]}..."
                for o in recent_for_summary
            ]
            context['recent_summary'] = "【近期大纲概要】\n" + "\n".join(recent_summaries)
            context['stats']['recent_summaries'] = len(recent_summaries)
            logger.info(f"  ✅ 近期概要：{len(recent_summaries)}章")
        
        # 3. 最近详细（最近2章，完整内容）
        recent_detail_count = min(2, total_count)
        recent_details = latest_outlines[-recent_detail_count:]
        detail_texts = [
            f"第{o.order_index}章《{o.title}》: {o.content}"
            for o in recent_details
        ]
        context['recent_detail'] = "【最近大纲详情】\n" + "\n".join(detail_texts)
        context['stats']['recent_details'] = len(detail_texts)
        logger.info(f"  ✅ 最近详细：{len(detail_texts)}章")
        
        # 计算总长度
        total_length = sum([
            len(context['story_skeleton']),
            len(context['recent_summary']),
            len(context['recent_detail'])
        ])
        context['stats']['total_length'] = total_length
        logger.info(f"📊 大纲上下文总长度: {total_length} 字符")
        
    except Exception as e:
        logger.error(f"❌ 构建智能大纲上下文失败: {str(e)}", exc_info=True)
    
    return context


async def _continue_outline(
    request: OutlineGenerateRequest,
    project: Project,
    existing_outlines: List[Outline],
    db: AsyncSession,
    user_ai_service: AIService,
    user_id: str = "system"
) -> OutlineListResponse:
    """续写大纲 - 分批生成，每批5章（记忆+MCP增强版）"""
    logger.info(f"续写大纲 - 项目: {project.id}, 已有: {len(existing_outlines)} 章, enable_mcp: {request.enable_mcp}")
    
    # 分析已有大纲
    current_chapter_count = len(existing_outlines)
    last_chapter_number = existing_outlines[-1].order_index
    
    # 计算需要生成的总章数和批次
    total_chapters_to_generate = request.chapter_count
    batch_size = 5  # 每批生成5章
    total_batches = (total_chapters_to_generate + batch_size - 1) // batch_size
    
    logger.info(f"分批生成计划: 总共{total_chapters_to_generate}章，分{total_batches}批，每批{batch_size}章")
    
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
    
    # 情节阶段指导
    stage_instructions = {
        "development": "继续展开情节，深化角色关系，推进主线冲突",
        "climax": "进入故事高潮，矛盾激化，关键冲突爆发",
        "ending": "解决主要冲突，收束伏笔，给出结局"
    }
    stage_instruction = stage_instructions.get(request.plot_stage, "")
    
    # 批量生成
    all_new_outlines = []
    current_start_chapter = last_chapter_number + 1
    
    for batch_num in range(total_batches):
        # 计算当前批次的章节数
        remaining_chapters = total_chapters_to_generate - len(all_new_outlines)
        current_batch_size = min(batch_size, remaining_chapters)
        
        logger.info(f"开始生成第{batch_num + 1}/{total_batches}批，章节范围: {current_start_chapter}-{current_start_chapter + current_batch_size - 1}")
        
        # 获取最新的大纲列表（包括之前批次生成的）
        latest_result = await db.execute(
            select(Outline)
            .where(Outline.project_id == project.id)
            .order_by(Outline.order_index)
        )
        latest_outlines = latest_result.scalars().all()
        
        # 🚀 使用智能上下文构建（支持海量大纲）
        smart_context = await _build_smart_outline_context(
            latest_outlines=latest_outlines,
            user_id=user_id,
            project_id=project.id
        )
        
        # 组装上下文字符串
        all_chapters_brief = ""
        if smart_context['story_skeleton']:
            all_chapters_brief += smart_context['story_skeleton'] + "\n\n"
        if smart_context['recent_summary']:
            all_chapters_brief += smart_context['recent_summary'] + "\n\n"
        
        # 最近详细内容作为 recent_plot
        recent_plot = smart_context['recent_detail']
        
        # 日志统计
        stats = smart_context['stats']
        logger.info(f"📊 大纲上下文统计: 总数{stats['total']}, 骨架{stats['skeleton_samples']}, "
                   f"概要{stats['recent_summaries']}, 详细{stats['recent_details']}, "
                   f"长度{stats['total_length']}字符")
        
        # 🧠 构建记忆增强上下文（仅续写模式需要）
        memory_context = None
        try:
            logger.info(f"🧠 为第{batch_num + 1}批构建记忆上下文...")
            # 使用最近一章的大纲作为查询
            query_outline = latest_outlines[-1].content if latest_outlines else ""
            memory_context = await memory_service.build_context_for_generation(
                user_id=user_id,
                project_id=project.id,
                current_chapter=current_start_chapter,
                chapter_outline=query_outline,
                character_names=[c.name for c in characters] if characters else None
            )
            logger.info(f"✅ 记忆上下文构建完成: {memory_context['stats']}")
        except Exception as e:
            logger.warning(f"⚠️ 记忆上下文构建失败，继续不使用记忆: {str(e)}")
            memory_context = None
        
        # 🔍 MCP工具增强：收集续写参考资料
        mcp_reference_materials = ""
        if request.enable_mcp:
            try:
                logger.info(f"🔍 第{batch_num + 1}批：尝试使用MCP工具收集续写参考资料...")
                
                # 构建资料收集查询
                latest_summary = latest_outlines[-1].content if latest_outlines else ""
                planning_query = f"""你正在为小说《{project.title}》续写大纲。
当前进度：已有{len(latest_outlines)}章，即将续写第{current_start_chapter}-{current_start_chapter + current_batch_size - 1}章

项目信息：
- 主题：{request.theme or project.theme}
- 类型：{request.genre or project.genre}
- 叙事视角：{request.narrative_perspective}
- 情节阶段：{request.plot_stage}
- 故事发展方向：{request.story_direction or '自然延续'}

最近章节概要：
{latest_summary[:200]}

请搜索：
1. 该情节阶段的经典处理手法和技巧
2. 适合该发展方向的情节转折和冲突设计
3. 符合类型特点的场景设计和剧情元素

请有针对性地查询1-2个最关键的问题。"""
                
                # 调用MCP增强的AI（非流式，最多2轮工具调用）
                planning_result = await user_ai_service.generate_text_with_mcp(
                    prompt=planning_query,
                    user_id=user_id,
                    db_session=db,
                    enable_mcp=True,
                    max_tool_rounds=2,
                    tool_choice="auto",
                    provider=None,
                    model=None
                )
                
                # 提取参考资料
                if planning_result.get("tool_calls_made", 0) > 0:
                    mcp_reference_materials = planning_result.get("content", "")
                    logger.info(f"📚 第{batch_num + 1}批MCP工具收集参考资料：{len(mcp_reference_materials)} 字符")
                else:
                    logger.info(f"ℹ️ 第{batch_num + 1}批MCP工具未进行调用，继续正常生成")
            except Exception as e:
                logger.warning(f"⚠️ 第{batch_num + 1}批MCP工具调用失败，继续使用常规模式: {str(e)}")
                mcp_reference_materials = ""
        
        # 使用标准续写提示词模板（支持记忆+MCP增强）
        prompt = prompt_service.get_outline_continue_prompt(
            title=project.title,
            theme=request.theme or project.theme or "未设定",
            genre=request.genre or project.genre or "通用",
            narrative_perspective=request.narrative_perspective,
            chapter_count=current_batch_size,  # 当前批次的章节数
            time_period=project.world_time_period or "未设定",
            location=project.world_location or "未设定",
            atmosphere=project.world_atmosphere or "未设定",
            rules=project.world_rules or "未设定",
            characters_info=characters_info or "暂无角色信息",
            current_chapter_count=len(latest_outlines),
            all_chapters_brief=all_chapters_brief,
            recent_plot=recent_plot,
            plot_stage_instruction=stage_instruction,
            start_chapter=current_start_chapter,
            story_direction=request.story_direction or "自然延续",
            requirements=request.requirements or "",
            memory_context=memory_context,
            mcp_references=mcp_reference_materials
        )
        
        # 调用AI生成当前批次
        logger.info(f"正在调用AI生成第{batch_num + 1}批...")
        ai_response = await user_ai_service.generate_text(
            prompt=prompt,
            provider=request.provider,
            model=request.model
        )
        
        # 提取内容（generate_text返回字典）
        ai_content = ai_response.get("content", "") if isinstance(ai_response, dict) else ai_response
        
        # 解析响应
        outline_data = _parse_ai_response(ai_content)
        
        # 保存当前批次的大纲
        batch_outlines = await _save_outlines(
            project.id, outline_data, db, start_index=current_start_chapter
        )
        
        # 记录历史
        history = GenerationHistory(
            project_id=project.id,
            prompt=f"[批次{batch_num + 1}/{total_batches}] {str(prompt)[:500]}",
            generated_content=json.dumps(ai_response, ensure_ascii=False) if isinstance(ai_response, dict) else ai_response,
            model=request.model or "default"
        )
        db.add(history)
        
        # 提交当前批次
        await db.commit()
        
        for outline in batch_outlines:
            await db.refresh(outline)
        
        all_new_outlines.extend(batch_outlines)
        current_start_chapter += current_batch_size
        
        logger.info(f"第{batch_num + 1}批生成完成，本批生成{len(batch_outlines)}章")
    
    # 返回所有大纲（包括旧的和新的）
    final_result = await db.execute(
        select(Outline)
        .where(Outline.project_id == project.id)
        .order_by(Outline.order_index)
    )
    all_outlines = final_result.scalars().all()
    
    logger.info(f"续写完成 - 共{total_batches}批，新增 {len(all_new_outlines)} 章，总计 {len(all_outlines)} 章")
    return OutlineListResponse(total=len(all_outlines), items=all_outlines)


def _parse_ai_response(ai_response: str) -> list:
    """解析AI响应为章节数据列表"""
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
        
        outline_data = json.loads(cleaned_text)
        
        # 确保是列表格式
        if not isinstance(outline_data, list):
            # 如果是对象，尝试提取chapters字段
            if isinstance(outline_data, dict):
                outline_data = outline_data.get("chapters", [outline_data])
            else:
                outline_data = [outline_data]
        
        return outline_data
        
    except json.JSONDecodeError as e:
        logger.error(f"AI响应解析失败: {e}")
        # 返回一个包含原始内容的章节
        return [{
            "title": "AI生成的大纲",
            "content": ai_response[:1000],
            "summary": ai_response[:1000]
        }]


async def _save_outlines(
    project_id: str,
    outline_data: list,
    db: AsyncSession,
    start_index: int = 1
) -> List[Outline]:
    """保存大纲到数据库（不自动创建章节）"""
    outlines = []
    
    for idx, chapter_data in enumerate(outline_data):
        order_idx = chapter_data.get("chapter_number", start_index + idx)
        title = chapter_data.get("title", f"第{order_idx}章")
        
        # 优先使用summary，其次content
        content = chapter_data.get("summary") or chapter_data.get("content", "")
        
        # 如果有额外信息，添加到内容中
        if "key_events" in chapter_data:
            content += f"\n\n关键事件：" + "、".join(chapter_data["key_events"])
        if "characters_involved" in chapter_data:
            content += f"\n涉及角色：" + "、".join(chapter_data["characters_involved"])
        
        # 创建大纲
        outline = Outline(
            project_id=project_id,
            title=title,
            content=content,
            structure=json.dumps(chapter_data, ensure_ascii=False),
            order_index=order_idx
        )
        db.add(outline)
        outlines.append(outline)
    
    return outlines


async def new_outline_generator(
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService
) -> AsyncGenerator[str, None]:
    """全新生成大纲SSE生成器（MCP增强版）"""
    db_committed = False
    try:
        yield await SSEResponse.send_progress("开始生成大纲...", 5)
        
        project_id = data.get("project_id")
        # 确保chapter_count是整数（前端可能传字符串）
        chapter_count = int(data.get("chapter_count", 10))
        enable_mcp = data.get("enable_mcp", True)
        
        # 验证项目
        yield await SSEResponse.send_progress("加载项目信息...", 10)
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        
        yield await SSEResponse.send_progress(f"准备生成{chapter_count}章大纲...", 15)
        
        # 获取角色信息
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = characters_result.scalars().all()
        characters_info = "\n".join([
            f"- {char.name} ({'组织' if char.is_organization else '角色'}, {char.role_type}): "
            f"{char.personality[:100] if char.personality else '暂无描述'}"
            for char in characters
        ])
        
        # 🔍 MCP工具增强：收集情节设计参考资料
        mcp_reference_materials = ""
        if enable_mcp:
            try:
                yield await SSEResponse.send_progress("🔍 使用MCP工具收集参考资料...", 18)
                logger.info(f"🔍 尝试使用MCP工具收集大纲设计参考资料...")
                
                # 构建资料收集查询
                planning_query = f"""你正在为小说《{project.title}》设计完整大纲。
项目信息：
- 主题：{data.get('theme') or project.theme}
- 类型：{data.get('genre') or project.genre}
- 章节数：{chapter_count}
- 叙事视角：{data.get('narrative_perspective') or '第三人称'}
- 目标字数：{data.get('target_words') or project.target_words or 100000}

世界观设定：
- 时间背景：{project.world_time_period or '未设定'}
- 地理位置：{project.world_location or '未设定'}
- 氛围基调：{project.world_atmosphere or '未设定'}

角色信息：
{characters_info or '暂无角色'}

请搜索：
1. 该类型小说的经典情节结构和套路
2. 适合该主题的冲突设计思路
3. 符合世界观的情节元素和场景设计灵感

请有针对性地查询1-2个最关键的问题。"""
                
                # 调用MCP增强的AI（非流式，最多2轮工具调用）
                planning_result = await user_ai_service.generate_text_with_mcp(
                    prompt=planning_query,
                    user_id="system",
                    db_session=db,
                    enable_mcp=True,
                    max_tool_rounds=2,
                    tool_choice="auto",
                    provider=None,
                    model=None
                )
                
                # 提取参考资料
                if planning_result.get("tool_calls_made", 0) > 0:
                    mcp_reference_materials = planning_result.get("content", "")
                    logger.info(f"📚 MCP工具收集参考资料：{len(mcp_reference_materials)} 字符")
                    yield await SSEResponse.send_progress(f"📚 MCP收集到参考资料 ({len(mcp_reference_materials)}字符)", 19)
                else:
                    logger.info(f"ℹ️ MCP工具未进行调用，继续正常生成")
            except Exception as e:
                logger.warning(f"⚠️ MCP工具调用失败，继续使用常规模式: {str(e)}")
                mcp_reference_materials = ""
        
        # 使用完整提示词（插入MCP参考资料）
        yield await SSEResponse.send_progress("准备AI提示词...", 20)
        prompt = prompt_service.get_complete_outline_prompt(
            title=project.title,
            theme=data.get("theme") or project.theme or "未设定",
            genre=data.get("genre") or project.genre or "通用",
            chapter_count=chapter_count,
            narrative_perspective=data.get("narrative_perspective") or "第三人称",
            target_words=data.get("target_words") or project.target_words or 100000,
            time_period=project.world_time_period or "未设定",
            location=project.world_location or "未设定",
            atmosphere=project.world_atmosphere or "未设定",
            rules=project.world_rules or "未设定",
            characters_info=characters_info or "暂无角色信息",
            requirements=data.get("requirements") or "",
            mcp_references=mcp_reference_materials
        )
        
        # 调用AI
        yield await SSEResponse.send_progress("🤖 正在调用AI生成...", 30)
        ai_response = await user_ai_service.generate_text(
            prompt=prompt,
            provider=data.get("provider"),
            model=data.get("model")
        )
        
        yield await SSEResponse.send_progress("✅ AI生成完成，正在解析...", 70)
        
        # 提取内容（generate_text返回字典）
        ai_content = ai_response.get("content", "") if isinstance(ai_response, dict) else ai_response
        
        # 解析响应
        outline_data = _parse_ai_response(ai_content)
        
        # 删除旧大纲（章节不自动删除，由用户手动管理）
        yield await SSEResponse.send_progress("清理旧大纲...", 75)
        logger.info(f"删除项目 {project_id} 的旧大纲")
        await db.execute(
            delete(Outline).where(Outline.project_id == project_id)
        )
        
        # 保存新大纲
        yield await SSEResponse.send_progress("💾 保存大纲到数据库...", 80)
        outlines = await _save_outlines(
            project_id, outline_data, db, start_index=1
        )
        
        # 记录历史
        history = GenerationHistory(
            project_id=project_id,
            prompt=prompt,
            generated_content=json.dumps(ai_response, ensure_ascii=False) if isinstance(ai_response, dict) else ai_response,
            model=data.get("model") or "default"
        )
        db.add(history)
        
        await db.commit()
        db_committed = True
        
        for outline in outlines:
            await db.refresh(outline)
        
        yield await SSEResponse.send_progress("整理结果数据...", 95)
        
        logger.info(f"全新生成完成 - {len(outlines)} 章")
        
        # 发送最终结果
        yield await SSEResponse.send_result({
            "message": f"成功生成{len(outlines)}章大纲",
            "total_chapters": len(outlines),
            "outlines": [
                {
                    "id": outline.id,
                    "project_id": outline.project_id,
                    "title": outline.title,
                    "content": outline.content,
                    "order_index": outline.order_index,
                    "structure": outline.structure,
                    "created_at": outline.created_at.isoformat() if outline.created_at else None,
                    "updated_at": outline.updated_at.isoformat() if outline.updated_at else None
                } for outline in outlines
            ]
        })
        
        yield await SSEResponse.send_progress("🎉 生成完成!", 100, "success")
        yield await SSEResponse.send_done()
        
    except GeneratorExit:
        logger.warning("大纲生成器被提前关闭")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("大纲生成事务已回滚（GeneratorExit）")
    except Exception as e:
        logger.error(f"大纲生成失败: {str(e)}")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("大纲生成事务已回滚（异常）")
        yield await SSEResponse.send_error(f"生成失败: {str(e)}")


async def continue_outline_generator(
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService,
    user_id: str = "system"
) -> AsyncGenerator[str, None]:
    """大纲续写SSE生成器 - 分批生成，推送进度（记忆+MCP增强版）"""
    db_committed = False
    try:
        yield await SSEResponse.send_progress("开始续写大纲...", 5)
        
        project_id = data.get("project_id")
        # 确保chapter_count是整数（前端可能传字符串）
        total_chapters_to_generate = int(data.get("chapter_count", 5))
        
        # 验证项目
        yield await SSEResponse.send_progress("加载项目信息...", 10)
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        
        # 获取现有大纲
        yield await SSEResponse.send_progress("分析已有大纲...", 15)
        existing_result = await db.execute(
            select(Outline)
            .where(Outline.project_id == project_id)
            .order_by(Outline.order_index)
        )
        existing_outlines = existing_result.scalars().all()
        
        if not existing_outlines:
            yield await SSEResponse.send_error("续写模式需要已有大纲，当前项目没有大纲", 400)
            return
        
        current_chapter_count = len(existing_outlines)
        last_chapter_number = existing_outlines[-1].order_index
        
        yield await SSEResponse.send_progress(
            f"当前已有{str(current_chapter_count)}章，将续写{str(total_chapters_to_generate)}章",
            20
        )
        
        # 获取角色信息
        characters_result = await db.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = characters_result.scalars().all()
        characters_info = "\n".join([
            f"- {char.name} ({'组织' if char.is_organization else '角色'}, {char.role_type}): "
            f"{char.personality[:100] if char.personality else '暂无描述'}"
            for char in characters
        ])

        # 分批配置
        batch_size = 5
        total_batches = (total_chapters_to_generate + batch_size - 1) // batch_size
        yield await SSEResponse.send_progress(
            f"分批生成计划: 总共{str(total_chapters_to_generate)}章，分{str(total_batches)}批，每批{str(batch_size)}章",
            25
        )
        
        # 情节阶段指导
        stage_instructions = {
            "development": "继续展开情节，深化角色关系，推进主线冲突",
            "climax": "进入故事高潮，矛盾激化，关键冲突爆发",
            "ending": "解决主要冲突，收束伏笔，给出结局"
        }
        stage_instruction = stage_instructions.get(data.get("plot_stage", "development"), "")
        
        # 批量生成
        all_new_outlines = []
        current_start_chapter = last_chapter_number + 1

        for batch_num in range(total_batches):
            # 计算当前批次的章节数
            remaining_chapters = int(total_chapters_to_generate) - len(all_new_outlines)
            current_batch_size = min(batch_size, remaining_chapters)
            
            batch_progress = 25 + (batch_num * 60 // total_batches)
            
            yield await SSEResponse.send_progress(
                f"📝 第{str(batch_num + 1)}/{str(total_batches)}批: 生成第{str(current_start_chapter)}-{str(current_start_chapter + current_batch_size - 1)}章",
                batch_progress
            )
            
            # 获取最新的大纲列表（包括之前批次生成的）
            latest_result = await db.execute(
                select(Outline)
                .where(Outline.project_id == project_id)
                .order_by(Outline.order_index)
            )
            latest_outlines = latest_result.scalars().all()
            
            # 🚀 使用智能上下文构建（支持海量大纲）
            smart_context = await _build_smart_outline_context(
                latest_outlines=latest_outlines,
                user_id=user_id,
                project_id=project_id
            )
            
            # 组装上下文字符串
            all_chapters_brief = ""
            if smart_context['story_skeleton']:
                all_chapters_brief += smart_context['story_skeleton'] + "\n\n"
            if smart_context['recent_summary']:
                all_chapters_brief += smart_context['recent_summary'] + "\n\n"
            
            # 最近详细内容作为 recent_plot
            recent_plot = smart_context['recent_detail']
            
            # 日志统计
            stats = smart_context['stats']
            logger.info(f"📊 批次{batch_num + 1}大纲上下文: 总数{stats['total']}, "
                       f"骨架{stats['skeleton_samples']}, 概要{stats['recent_summaries']}, "
                       f"详细{stats['recent_details']}, 长度{stats['total_length']}字符")
            
            # 🧠 构建记忆增强上下文
            memory_context = None
            try:
                yield await SSEResponse.send_progress(
                    f"🧠 构建记忆上下文...",
                    batch_progress + 3
                )
                query_outline = latest_outlines[-1].content if latest_outlines else ""
                memory_context = await memory_service.build_context_for_generation(
                    user_id=user_id,
                    project_id=project_id,
                    current_chapter=current_start_chapter,
                    chapter_outline=query_outline,
                    character_names=[c.name for c in characters] if characters else None
                )
                logger.info(f"✅ 记忆上下文: {memory_context['stats']}")
            except Exception as e:
                logger.warning(f"⚠️ 记忆上下文构建失败: {str(e)}")
                memory_context = None
            # 🔍 MCP工具增强：收集续写参考资料
            mcp_reference_materials = ""
            enable_mcp = data.get("enable_mcp", True)
            if enable_mcp:
                try:
                    yield await SSEResponse.send_progress(
                        f"🔍 第{str(batch_num + 1)}批：使用MCP工具收集参考资料...",
                        batch_progress + 4
                    )
                    logger.info(f"🔍 第{batch_num + 1}批：尝试使用MCP工具收集续写参考资料...")
                    
                    # 构建资料收集查询
                    latest_summary = latest_outlines[-1].content if latest_outlines else ""
                    planning_query = f"""你正在为小说《{project.title}》续写大纲。
当前进度：已有{len(latest_outlines)}章，即将续写第{current_start_chapter}-{current_start_chapter + current_batch_size - 1}章

项目信息：
- 主题：{data.get('theme') or project.theme}
- 类型：{data.get('genre') or project.genre}
- 叙事视角：{data.get('narrative_perspective') or project.narrative_perspective or '第三人称'}
- 情节阶段：{data.get('plot_stage', 'development')}
- 故事发展方向：{data.get('story_direction', '自然延续')}

最近章节概要：
{latest_summary[:200]}

请搜索：
1. 该情节阶段的经典处理手法和技巧
2. 适合该发展方向的情节转折和冲突设计
3. 符合类型特点的场景设计和剧情元素

请有针对性地查询1-2个最关键的问题。"""
                    
                    # 调用MCP增强的AI（非流式，最多2轮工具调用）
                    planning_result = await user_ai_service.generate_text_with_mcp(
                        prompt=planning_query,
                        user_id=user_id,
                        db_session=db,
                        enable_mcp=True,
                        max_tool_rounds=2,
                        tool_choice="auto",
                        provider=None,
                        model=None
                    )
                    
                    # 提取参考资料
                    if planning_result.get("tool_calls_made", 0) > 0:
                        mcp_reference_materials = planning_result.get("content", "")
                        logger.info(f"📚 第{batch_num + 1}批MCP工具收集参考资料：{len(mcp_reference_materials)} 字符")
                        yield await SSEResponse.send_progress(
                            f"📚 第{str(batch_num + 1)}批收集到参考资料 ({len(mcp_reference_materials)}字符)",
                            batch_progress + 4.5
                        )
                    else:
                        logger.info(f"ℹ️ 第{batch_num + 1}批MCP工具未进行调用，继续正常生成")
                except Exception as e:
                    logger.warning(f"⚠️ 第{batch_num + 1}批MCP工具调用失败，继续使用常规模式: {str(e)}")
                    mcp_reference_materials = ""
            
            
            yield await SSEResponse.send_progress(
                f" 调用AI生成第{str(batch_num + 1)}批...",
                batch_progress + 5
            )
            
            # 使用标准续写提示词模板（支持记忆+MCP增强）
            prompt = prompt_service.get_outline_continue_prompt(
                title=project.title,
                theme=data.get("theme") or project.theme or "未设定",
                genre=data.get("genre") or project.genre or "通用",
                narrative_perspective=data.get("narrative_perspective") or project.narrative_perspective or "第三人称",
                chapter_count=current_batch_size,
                time_period=project.world_time_period or "未设定",
                location=project.world_location or "未设定",
                atmosphere=project.world_atmosphere or "未设定",
                rules=project.world_rules or "未设定",
                characters_info=characters_info or "暂无角色信息",
                current_chapter_count=len(latest_outlines),
                all_chapters_brief=all_chapters_brief,
                recent_plot=recent_plot,
                plot_stage_instruction=stage_instruction,
                start_chapter=current_start_chapter,
                story_direction=data.get("story_direction", "自然延续"),
                requirements=data.get("requirements", ""),
                memory_context=memory_context,
                mcp_references=mcp_reference_materials
            )
            
            # 调用AI生成当前批次
            ai_response = await user_ai_service.generate_text(
                prompt=prompt,
                provider=data.get("provider"),
                model=data.get("model")
            )
            
            yield await SSEResponse.send_progress(
                f"✅ 第{str(batch_num + 1)}批AI生成完成，正在解析...",
                batch_progress + 10
            )
            
            # 提取内容（generate_text返回字典）
            ai_content = ai_response.get("content", "") if isinstance(ai_response, dict) else ai_response
            
            # 解析响应
            outline_data = _parse_ai_response(ai_content)
            
            # 保存当前批次的大纲
            batch_outlines = await _save_outlines(
                project_id, outline_data, db, start_index=current_start_chapter
            )
            
            # 记录历史
            history = GenerationHistory(
                project_id=project_id,
                prompt=f"[续写批次{batch_num + 1}/{total_batches}] {str(prompt)[:500]}",
                generated_content=json.dumps(ai_response, ensure_ascii=False) if isinstance(ai_response, dict) else ai_response,
                model=data.get("model") or "default"
            )
            db.add(history)
            
            # 提交当前批次
            await db.commit()
            
            for outline in batch_outlines:
                await db.refresh(outline)
            
            all_new_outlines.extend(batch_outlines)
            current_start_chapter += current_batch_size
            
            yield await SSEResponse.send_progress(
                f"💾 第{str(batch_num + 1)}批保存成功！本批生成{str(len(batch_outlines))}章，累计新增{str(len(all_new_outlines))}章",
                batch_progress + 15
            )
            
            logger.info(f"第{str(batch_num + 1)}批生成完成，本批生成{str(len(batch_outlines))}章")
        
        db_committed = True
        
        # 返回所有大纲（包括旧的和新的）
        final_result = await db.execute(
            select(Outline)
            .where(Outline.project_id == project_id)
            .order_by(Outline.order_index)
        )
        all_outlines = final_result.scalars().all()
        
        yield await SSEResponse.send_progress("整理结果数据...", 95)
        
        # 发送最终结果
        yield await SSEResponse.send_result({
            "message": f"续写完成！共{str(total_batches)}批，新增{str(len(all_new_outlines))}章，总计{str(len(all_outlines))}章",
            "total_batches": total_batches,
            "new_chapters": len(all_new_outlines),
            "total_chapters": len(all_outlines),
            "outlines": [
                {
                    "id": outline.id,
                    "project_id": outline.project_id,
                    "title": outline.title,
                    "content": outline.content,
                    "order_index": outline.order_index,
                    "structure": outline.structure,
                    "created_at": outline.created_at.isoformat() if outline.created_at else None,
                    "updated_at": outline.updated_at.isoformat() if outline.updated_at else None
                } for outline in all_outlines
            ]
        })
        
        yield await SSEResponse.send_progress("🎉 续写完成!", 100, "success")
        yield await SSEResponse.send_done()
        
    except GeneratorExit:
        logger.warning("大纲续写生成器被提前关闭")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("大纲续写事务已回滚（GeneratorExit）")
    except Exception as e:
        logger.error(f"大纲续写失败: {str(e)}")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("大纲续写事务已回滚（异常）")
        yield await SSEResponse.send_error(f"续写失败: {str(e)}")


@router.post("/generate-stream", summary="AI生成/续写大纲(SSE流式)")
async def generate_outline_stream(
    data: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    使用SSE流式生成或续写小说大纲，实时推送批次进度
    
    支持模式：
    - auto: 自动判断（无大纲→新建，有大纲→续写）
    - new: 全新生成
    - continue: 续写模式
    
    请求体示例：
    {
        "project_id": "项目ID",
        "chapter_count": 5,  // 章节数
        "mode": "auto",  // auto/new/continue
        "theme": "故事主题",  // new模式必需
        "story_direction": "故事发展方向",  // continue模式可选
        "plot_stage": "development",  // continue模式：development/climax/ending
        "narrative_perspective": "第三人称",
        "requirements": "其他要求",
        "provider": "openai",  // 可选
        "model": "gpt-4"  // 可选
    }
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    project = await verify_project_access(data.get("project_id"), user_id, db)
    
    # 判断模式
    mode = data.get("mode", "auto")
    
    # 获取现有大纲
    existing_result = await db.execute(
        select(Outline)
        .where(Outline.project_id == data.get("project_id"))
        .order_by(Outline.order_index)
    )
    existing_outlines = existing_result.scalars().all()
    
    # 自动判断模式
    if mode == "auto":
        mode = "continue" if existing_outlines else "new"
        logger.info(f"自动判断模式：{'续写' if existing_outlines else '新建'}")
    
    # 获取用户ID
    user_id = getattr(request.state, "user_id", "system")
    
    # 根据模式选择生成器
    if mode == "new":
        return create_sse_response(new_outline_generator(data, db, user_ai_service))
    elif mode == "continue":
        if not existing_outlines:
            raise HTTPException(
                status_code=400,
                detail="续写模式需要已有大纲，当前项目没有大纲"
            )
        return create_sse_response(continue_outline_generator(data, db, user_ai_service, user_id))
    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的模式: {mode}"
        )


async def expand_outline_generator(
    outline_id: str,
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService
) -> AsyncGenerator[str, None]:
    """单个大纲展开SSE生成器 - 实时推送进度（支持分批生成）"""
    db_committed = False
    try:
        yield await SSEResponse.send_progress("开始展开大纲...", 5)
        
        target_chapter_count = int(data.get("target_chapter_count", 3))
        expansion_strategy = data.get("expansion_strategy", "balanced")
        enable_scene_analysis = data.get("enable_scene_analysis", True)
        auto_create_chapters = data.get("auto_create_chapters", False)
        batch_size = int(data.get("batch_size", 5))  # 支持自定义批次大小
        
        # 获取大纲
        yield await SSEResponse.send_progress("加载大纲信息...", 10)
        result = await db.execute(
            select(Outline).where(Outline.id == outline_id)
        )
        outline = result.scalar_one_or_none()
        
        if not outline:
            yield await SSEResponse.send_error("大纲不存在", 404)
            return
        
        # 获取项目信息
        yield await SSEResponse.send_progress("加载项目信息...", 15)
        project_result = await db.execute(
            select(Project).where(Project.id == outline.project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        
        yield await SSEResponse.send_progress(
            f"准备展开《{outline.title}》为 {target_chapter_count} 章...",
            20
        )
        
        # 创建展开服务实例
        expansion_service = PlotExpansionService(user_ai_service)
        
        # 定义进度回调函数
        async def progress_callback(batch_num: int, total_batches: int, start_idx: int, batch_size: int):
            progress = 30 + int((batch_num - 1) / total_batches * 40)
            yield await SSEResponse.send_progress(
                f"📝 生成第{batch_num}/{total_batches}批（第{start_idx}-{start_idx + batch_size - 1}节）...",
                progress
            )
        
        # 分析大纲并生成章节规划（支持分批）
        if target_chapter_count > batch_size:
            yield await SSEResponse.send_progress(
                f"🤖 AI分批生成章节规划（每批{batch_size}章）...",
                30
            )
        else:
            yield await SSEResponse.send_progress("🤖 AI分析大纲，生成章节规划...", 30)
        
        chapter_plans = await expansion_service.analyze_outline_for_chapters(
            outline=outline,
            project=project,
            db=db,
            target_chapter_count=target_chapter_count,
            expansion_strategy=expansion_strategy,
            enable_scene_analysis=enable_scene_analysis,
            provider=data.get("provider"),
            model=data.get("model"),
            batch_size=batch_size,
            progress_callback=None  # SSE中暂不支持嵌套回调
        )
        
        if not chapter_plans:
            yield await SSEResponse.send_error("AI分析失败，未能生成章节规划", 500)
            return
        
        yield await SSEResponse.send_progress(
            f"✅ 规划生成完成！共 {len(chapter_plans)} 个章节",
            70
        )
        
        # 根据配置决定是否创建章节记录
        created_chapters = None
        if auto_create_chapters:
            yield await SSEResponse.send_progress("💾 创建章节记录...", 80)
            
            created_chapters = await expansion_service.create_chapters_from_plans(
                outline_id=outline_id,
                chapter_plans=chapter_plans,
                project_id=outline.project_id,
                db=db,
                start_chapter_number=None  # 自动计算章节序号
            )
            
            await db.commit()
            db_committed = True
            
            # 刷新章节数据
            for chapter in created_chapters:
                await db.refresh(chapter)
            
            yield await SSEResponse.send_progress(
                f"✅ 成功创建 {len(created_chapters)} 个章节记录",
                90
            )
        
        yield await SSEResponse.send_progress("整理结果数据...", 95)
        
        # 构建响应数据
        result_data = {
            "outline_id": outline_id,
            "outline_title": outline.title,
            "target_chapter_count": target_chapter_count,
            "actual_chapter_count": len(chapter_plans),
            "expansion_strategy": expansion_strategy,
            "chapter_plans": chapter_plans,
            "created_chapters": [
                {
                    "id": ch.id,
                    "chapter_number": ch.chapter_number,
                    "title": ch.title,
                    "summary": ch.summary,
                    "outline_id": ch.outline_id,
                    "sub_index": ch.sub_index,
                    "status": ch.status
                }
                for ch in created_chapters
            ] if created_chapters else None
        }
        
        yield await SSEResponse.send_result(result_data)
        yield await SSEResponse.send_progress("🎉 展开完成!", 100, "success")
        yield await SSEResponse.send_done()
        
    except GeneratorExit:
        logger.warning("大纲展开生成器被提前关闭")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("大纲展开事务已回滚（GeneratorExit）")
    except Exception as e:
        logger.error(f"大纲展开失败: {str(e)}")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("大纲展开事务已回滚（异常）")
        yield await SSEResponse.send_error(f"展开失败: {str(e)}")


@router.post("/{outline_id}/expand", response_model=OutlineExpansionResponse, summary="展开单个大纲为多章")
async def expand_outline_to_chapters(
    outline_id: str,
    expansion_request: OutlineExpansionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    根据单个大纲摘要，通过AI分析生成多个章节规划
    
    流程：
    1. 获取大纲信息和上下文（前后大纲）
    2. 调用AI分析大纲，生成多章节规划
    3. 根据规划创建章节记录（outline_id关联到原大纲）
    
    参数：
    - outline_id: 要展开的大纲ID
    - expansion_request: 展开配置（章节数量、展开策略等）
    
    返回：
    - 展开后的章节列表和规划详情
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    
    # 获取大纲
    result = await db.execute(
        select(Outline).where(Outline.id == outline_id)
    )
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    
    # 验证项目权限
    await verify_project_access(outline.project_id, user_id, db)
    
    try:
        # 创建展开服务实例
        expansion_service = PlotExpansionService(user_ai_service)
        
        # 获取项目信息
        project_result = await db.execute(
            select(Project).where(Project.id == outline.project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 分析大纲并生成章节规划
        logger.info(f"开始展开大纲 {outline_id}，目标章节数: {expansion_request.target_chapter_count}")
        
        chapter_plans = await expansion_service.analyze_outline_for_chapters(
            outline=outline,
            project=project,
            db=db,
            target_chapter_count=expansion_request.target_chapter_count,
            expansion_strategy=expansion_request.expansion_strategy,
            enable_scene_analysis=expansion_request.enable_scene_analysis,
            provider=expansion_request.provider,
            model=expansion_request.model
        )
        
        if not chapter_plans:
            raise HTTPException(status_code=500, detail="AI分析失败，未能生成章节规划")
        
        logger.info(f"AI分析完成，生成了 {len(chapter_plans)} 个章节规划")
        
        # 根据规划创建章节记录
        if expansion_request.auto_create_chapters:
            created_chapters = await expansion_service.create_chapters_from_plans(
                outline_id=outline_id,
                chapter_plans=chapter_plans,
                project_id=outline.project_id,
                db=db,
                start_chapter_number=None  # 自动计算章节序号
            )
            
            await db.commit()
            
            # 刷新章节数据
            for chapter in created_chapters:
                await db.refresh(chapter)
            
            logger.info(f"成功创建 {len(created_chapters)} 个章节记录")
            
            # 构建响应
            return OutlineExpansionResponse(
                outline_id=outline_id,
                outline_title=outline.title,
                target_chapter_count=expansion_request.target_chapter_count,
                actual_chapter_count=len(chapter_plans),
                expansion_strategy=expansion_request.expansion_strategy,
                chapter_plans=chapter_plans,
                created_chapters=[
                    {
                        "id": ch.id,
                        "chapter_number": ch.chapter_number,
                        "title": ch.title,
                        "summary": ch.summary,
                        "outline_id": ch.outline_id,
                        "sub_index": ch.sub_index,
                        "status": ch.status
                    }
                    for ch in created_chapters
                ]
            )
        else:
            # 仅返回章节规划，不创建记录
            logger.info(f"仅生成规划，未创建章节记录")
            return OutlineExpansionResponse(
                outline_id=outline_id,
                outline_title=outline.title,
                target_chapter_count=expansion_request.target_chapter_count,
                actual_chapter_count=len(chapter_plans),
                expansion_strategy=expansion_request.expansion_strategy,
                chapter_plans=chapter_plans,
                created_chapters=None
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"大纲展开失败: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"大纲展开失败: {str(e)}")


@router.post("/{outline_id}/expand-stream", summary="展开单个大纲为多章(SSE流式)")
async def expand_outline_to_chapters_stream(
    outline_id: str,
    data: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    使用SSE流式展开单个大纲，实时推送进度
    
    请求体示例：
    {
        "target_chapter_count": 3,  // 目标章节数
        "expansion_strategy": "balanced",  // balanced/climax/detail
        "auto_create_chapters": false,  // 是否自动创建章节
        "enable_scene_analysis": true,  // 是否启用场景分析
        "provider": "openai",  // 可选
        "model": "gpt-4"  // 可选
    }
    
    进度阶段：
    - 5% - 开始展开
    - 10% - 加载大纲信息
    - 15% - 加载项目信息
    - 20% - 准备展开参数
    - 30% - AI分析大纲（耗时）
    - 70% - 规划生成完成
    - 80% - 创建章节记录（如果auto_create_chapters=True）
    - 90% - 创建完成
    - 95% - 整理结果数据
    - 100% - 全部完成
    """
    # 获取大纲并验证权限
    result = await db.execute(
        select(Outline).where(Outline.id == outline_id)
    )
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(outline.project_id, user_id, db)
    
    return create_sse_response(expand_outline_generator(outline_id, data, db, user_ai_service))


@router.get("/{outline_id}/chapters", summary="获取大纲关联的章节")
async def get_outline_chapters(
    outline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取指定大纲已展开的章节列表
    
    用于检查大纲是否已经展开过,如果有则返回章节信息
    """
    # 获取大纲
    result = await db.execute(
        select(Outline).where(Outline.id == outline_id)
    )
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(outline.project_id, user_id, db)
    
    # 查询该大纲关联的章节
    chapters_result = await db.execute(
        select(Chapter)
        .where(Chapter.outline_id == outline_id)
        .order_by(Chapter.sub_index)
    )
    chapters = chapters_result.scalars().all()
    
    # 如果有章节,解析展开规划
    expansion_plans = []
    if chapters:
        for chapter in chapters:
            plan_data = None
            if chapter.expansion_plan:
                try:
                    plan_data = json.loads(chapter.expansion_plan)
                except json.JSONDecodeError:
                    logger.warning(f"章节 {chapter.id} 的expansion_plan解析失败")
                    plan_data = None
            
            expansion_plans.append({
                "sub_index": chapter.sub_index,
                "title": chapter.title,
                "plot_summary": chapter.summary or "",
                "key_events": plan_data.get("key_events", []) if plan_data else [],
                "character_focus": plan_data.get("character_focus", []) if plan_data else [],
                "emotional_tone": plan_data.get("emotional_tone", "") if plan_data else "",
                "narrative_goal": plan_data.get("narrative_goal", "") if plan_data else "",
                "conflict_type": plan_data.get("conflict_type", "") if plan_data else "",
                "estimated_words": plan_data.get("estimated_words", 0) if plan_data else 0,
                "scenes": plan_data.get("scenes") if plan_data else None
            })
    
    return {
        "has_chapters": len(chapters) > 0,
        "outline_id": outline_id,
        "outline_title": outline.title,
        "chapter_count": len(chapters),
        "chapters": [
            {
                "id": ch.id,
                "chapter_number": ch.chapter_number,
                "title": ch.title,
                "summary": ch.summary,
                "sub_index": ch.sub_index,
                "status": ch.status,
                "word_count": ch.word_count
            }
            for ch in chapters
        ],
        "expansion_plans": expansion_plans if expansion_plans else None
    }


@router.post("/batch-expand", response_model=BatchOutlineExpansionResponse, summary="批量展开大纲为多章")
async def batch_expand_outlines(
    batch_request: BatchOutlineExpansionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    批量展开项目中的所有大纲或指定大纲列表
    
    流程：
    1. 获取项目中的所有大纲（或指定大纲列表）
    2. 逐个分析大纲，生成多章节规划
    3. 根据规划批量创建章节记录
    
    参数：
    - batch_request: 批量展开配置
    
    返回：
    - 所有展开的大纲和章节信息
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(batch_request.project_id, user_id, db)
    
    try:
        # 创建展开服务实例
        expansion_service = PlotExpansionService(user_ai_service)
        
        # 获取项目信息
        project_result = await db.execute(
            select(Project).where(Project.id == batch_request.project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 获取要展开的大纲列表
        if batch_request.outline_ids:
            # 展开指定的大纲
            outlines_result = await db.execute(
                select(Outline)
                .where(
                    Outline.project_id == batch_request.project_id,
                    Outline.id.in_(batch_request.outline_ids)
                )
                .order_by(Outline.order_index)
            )
        else:
            # 展开所有大纲
            outlines_result = await db.execute(
                select(Outline)
                .where(Outline.project_id == batch_request.project_id)
                .order_by(Outline.order_index)
            )
        
        outlines = outlines_result.scalars().all()
        
        if not outlines:
            raise HTTPException(status_code=404, detail="没有找到要展开的大纲")
        
        # 批量展开大纲
        logger.info(f"开始批量展开 {len(outlines)} 个大纲")
        
        expansion_results = []
        total_chapters_created = 0
        skipped_outlines = []
        
        for outline in outlines:
            try:
                # 检查大纲是否已经展开过
                existing_chapters_result = await db.execute(
                    select(Chapter)
                    .where(Chapter.outline_id == outline.id)
                    .limit(1)
                )
                existing_chapter = existing_chapters_result.scalar_one_or_none()
                
                if existing_chapter:
                    logger.info(f"大纲 {outline.title} (ID: {outline.id}) 已经展开过，跳过")
                    skipped_outlines.append({
                        "outline_id": outline.id,
                        "outline_title": outline.title,
                        "reason": "已展开"
                    })
                    continue
                
                # 分析大纲生成章节规划
                chapter_plans = await expansion_service.analyze_outline_for_chapters(
                    outline=outline,
                    project=project,
                    db=db,
                    target_chapter_count=batch_request.chapters_per_outline,
                    expansion_strategy=batch_request.expansion_strategy,
                    enable_scene_analysis=batch_request.enable_scene_analysis,
                    provider=batch_request.provider,
                    model=batch_request.model
                )
                
                created_chapters = None
                if batch_request.auto_create_chapters:
                    # 创建章节记录
                    chapters = await expansion_service.create_chapters_from_plans(
                        outline_id=outline.id,
                        chapter_plans=chapter_plans,
                        project_id=outline.project_id,
                        db=db,
                        start_chapter_number=None  # 自动计算章节序号
                    )
                    created_chapters = [
                        {
                            "id": ch.id,
                            "chapter_number": ch.chapter_number,
                            "title": ch.title,
                            "summary": ch.summary,
                            "outline_id": ch.outline_id,
                            "sub_index": ch.sub_index,
                            "status": ch.status
                        }
                        for ch in chapters
                    ]
                    total_chapters_created += len(chapters)
                
                expansion_results.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "target_chapter_count": batch_request.chapters_per_outline,
                    "actual_chapter_count": len(chapter_plans),
                    "expansion_strategy": batch_request.expansion_strategy,
                    "chapter_plans": chapter_plans,
                    "created_chapters": created_chapters
                })
                
                logger.info(f"大纲 {outline.title} 展开完成，生成 {len(chapter_plans)} 个章节规划")
                
            except Exception as e:
                logger.error(f"展开大纲 {outline.id} 失败: {str(e)}", exc_info=True)
                expansion_results.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "target_chapter_count": batch_request.chapters_per_outline,
                    "actual_chapter_count": 0,
                    "expansion_strategy": batch_request.expansion_strategy,
                    "chapter_plans": [],
                    "created_chapters": None,
                    "error": str(e)
                })
        
        logger.info(f"批量展开完成: {len(expansion_results)} 个大纲，共生成 {total_chapters_created} 个章节")
        
        # 构建响应
        return BatchOutlineExpansionResponse(
            project_id=batch_request.project_id,
            total_outlines_expanded=len(expansion_results),
            total_chapters_created=total_chapters_created,
            expansion_results=[
                OutlineExpansionResponse(
                    outline_id=result["outline_id"],
                    outline_title=result["outline_title"],
                    target_chapter_count=result["target_chapter_count"],
                    actual_chapter_count=result["actual_chapter_count"],
                    expansion_strategy=result["expansion_strategy"],
                    chapter_plans=result["chapter_plans"],
                    created_chapters=result.get("created_chapters")
                )
                for result in expansion_results
            ]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量大纲展开失败: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"批量大纲展开失败: {str(e)}")


async def batch_expand_outlines_generator(
    data: Dict[str, Any],
    db: AsyncSession,
    user_ai_service: AIService
) -> AsyncGenerator[str, None]:
    """批量展开大纲SSE生成器 - 实时推送进度"""
    db_committed = False
    try:
        yield await SSEResponse.send_progress("开始批量展开大纲...", 5)
        
        project_id = data.get("project_id")
        chapters_per_outline = int(data.get("chapters_per_outline", 3))
        expansion_strategy = data.get("expansion_strategy", "balanced")
        auto_create_chapters = data.get("auto_create_chapters", False)
        outline_ids = data.get("outline_ids")
        
        # 获取项目信息
        yield await SSEResponse.send_progress("加载项目信息...", 10)
        project_result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            yield await SSEResponse.send_error("项目不存在", 404)
            return
        
        # 获取要展开的大纲列表
        yield await SSEResponse.send_progress("获取大纲列表...", 15)
        if outline_ids:
            outlines_result = await db.execute(
                select(Outline)
                .where(
                    Outline.project_id == project_id,
                    Outline.id.in_(outline_ids)
                )
                .order_by(Outline.order_index)
            )
        else:
            outlines_result = await db.execute(
                select(Outline)
                .where(Outline.project_id == project_id)
                .order_by(Outline.order_index)
            )
        
        outlines = outlines_result.scalars().all()
        
        if not outlines:
            yield await SSEResponse.send_error("没有找到要展开的大纲", 404)
            return
        
        total_outlines = len(outlines)
        yield await SSEResponse.send_progress(
            f"共找到 {total_outlines} 个大纲，开始批量展开...",
            20
        )
        
        # 创建展开服务实例
        expansion_service = PlotExpansionService(user_ai_service)
        
        expansion_results = []
        total_chapters_created = 0
        skipped_outlines = []
        
        for idx, outline in enumerate(outlines):
            try:
                # 计算当前进度 (20% - 90%)
                progress = 20 + int((idx / total_outlines) * 70)
                
                yield await SSEResponse.send_progress(
                    f"📝 处理第 {idx + 1}/{total_outlines} 个大纲: {outline.title}",
                    progress
                )
                
                # 检查大纲是否已经展开过
                existing_chapters_result = await db.execute(
                    select(Chapter)
                    .where(Chapter.outline_id == outline.id)
                    .limit(1)
                )
                existing_chapter = existing_chapters_result.scalar_one_or_none()
                
                if existing_chapter:
                    logger.info(f"大纲 {outline.title} (ID: {outline.id}) 已经展开过，跳过")
                    skipped_outlines.append({
                        "outline_id": outline.id,
                        "outline_title": outline.title,
                        "reason": "已展开"
                    })
                    yield await SSEResponse.send_progress(
                        f"⏭️ {outline.title} 已展开过，跳过",
                        progress + 1
                    )
                    continue
                
                # 分析大纲生成章节规划
                yield await SSEResponse.send_progress(
                    f"🤖 AI分析大纲: {outline.title}",
                    progress + 2
                )
                
                chapter_plans = await expansion_service.analyze_outline_for_chapters(
                    outline=outline,
                    project=project,
                    db=db,
                    target_chapter_count=chapters_per_outline,
                    expansion_strategy=expansion_strategy,
                    enable_scene_analysis=data.get("enable_scene_analysis", True),
                    provider=data.get("provider"),
                    model=data.get("model")
                )
                
                yield await SSEResponse.send_progress(
                    f"✅ {outline.title} 规划生成完成 ({len(chapter_plans)} 章)",
                    progress + 3
                )
                
                created_chapters = None
                if auto_create_chapters:
                    # 创建章节记录
                    chapters = await expansion_service.create_chapters_from_plans(
                        outline_id=outline.id,
                        chapter_plans=chapter_plans,
                        project_id=outline.project_id,
                        db=db,
                        start_chapter_number=None  # 自动计算章节序号
                    )
                    created_chapters = [
                        {
                            "id": ch.id,
                            "chapter_number": ch.chapter_number,
                            "title": ch.title,
                            "summary": ch.summary,
                            "outline_id": ch.outline_id,
                            "sub_index": ch.sub_index,
                            "status": ch.status
                        }
                        for ch in chapters
                    ]
                    total_chapters_created += len(chapters)
                    
                    yield await SSEResponse.send_progress(
                        f"💾 {outline.title} 章节创建完成 ({len(chapters)} 章)",
                        progress + 4
                    )
                
                expansion_results.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "target_chapter_count": chapters_per_outline,
                    "actual_chapter_count": len(chapter_plans),
                    "expansion_strategy": expansion_strategy,
                    "chapter_plans": chapter_plans,
                    "created_chapters": created_chapters
                })
                
                logger.info(f"大纲 {outline.title} 展开完成，生成 {len(chapter_plans)} 个章节规划")
                
            except Exception as e:
                logger.error(f"展开大纲 {outline.id} 失败: {str(e)}", exc_info=True)
                yield await SSEResponse.send_progress(
                    f"❌ {outline.title} 展开失败: {str(e)}",
                    progress
                )
                expansion_results.append({
                    "outline_id": outline.id,
                    "outline_title": outline.title,
                    "target_chapter_count": chapters_per_outline,
                    "actual_chapter_count": 0,
                    "expansion_strategy": expansion_strategy,
                    "chapter_plans": [],
                    "created_chapters": None,
                    "error": str(e)
                })
        
        yield await SSEResponse.send_progress("整理结果数据...", 95)
        
        db_committed = True
        
        logger.info(f"批量展开完成: {len(expansion_results)} 个大纲，跳过 {len(skipped_outlines)} 个，共生成 {total_chapters_created} 个章节")
        
        # 发送最终结果
        result_data = {
            "project_id": project_id,
            "total_outlines_expanded": len(expansion_results),
            "total_chapters_created": total_chapters_created,
            "skipped_count": len(skipped_outlines),
            "skipped_outlines": skipped_outlines,
            "expansion_results": [
                {
                    "outline_id": result["outline_id"],
                    "outline_title": result["outline_title"],
                    "target_chapter_count": result["target_chapter_count"],
                    "actual_chapter_count": result["actual_chapter_count"],
                    "expansion_strategy": result["expansion_strategy"],
                    "chapter_plans": result["chapter_plans"],
                    "created_chapters": result.get("created_chapters")
                }
                for result in expansion_results
            ]
        }
        
        yield await SSEResponse.send_result(result_data)
        yield await SSEResponse.send_progress("🎉 批量展开完成!", 100, "success")
        yield await SSEResponse.send_done()
        
    except GeneratorExit:
        logger.warning("批量展开生成器被提前关闭")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("批量展开事务已回滚（GeneratorExit）")
    except Exception as e:
        logger.error(f"批量展开失败: {str(e)}")
        if not db_committed and db.in_transaction():
            await db.rollback()
            logger.info("批量展开事务已回滚（异常）")
        yield await SSEResponse.send_error(f"批量展开失败: {str(e)}")


@router.post("/batch-expand-stream", summary="批量展开大纲为多章(SSE流式)")
async def batch_expand_outlines_stream(
    data: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    使用SSE流式批量展开大纲，实时推送每个大纲的处理进度
    
    请求体示例：
    {
        "project_id": "项目ID",
        "outline_ids": ["大纲ID1", "大纲ID2"],  // 可选，不传则展开所有大纲
        "chapters_per_outline": 3,  // 每个大纲展开几章
        "expansion_strategy": "balanced",  // balanced/climax/detail
        "auto_create_chapters": false,  // 是否自动创建章节
        "enable_scene_analysis": true,  // 是否启用场景分析
        "provider": "openai",  // 可选
        "model": "gpt-4"  // 可选
    }
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(data.get("project_id"), user_id, db)
    
    return create_sse_response(batch_expand_outlines_generator(data, db, user_ai_service))


@router.post("/{outline_id}/create-chapters-from-plans", response_model=CreateChaptersFromPlansResponse, summary="根据已有规划创建章节")
async def create_chapters_from_existing_plans(
    outline_id: str,
    plans_request: CreateChaptersFromPlansRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    根据前端缓存的章节规划直接创建章节记录，避免重复调用AI
    
    使用场景：
    1. 用户第一次调用 /outlines/{outline_id}/expand?auto_create_chapters=false 获取规划预览
    2. 前端展示规划给用户确认
    3. 用户确认后，前端调用此接口，传递缓存的规划数据，直接创建章节
    
    优势：
    - 避免重复的AI调用，节省Token和时间
    - 确保用户看到的预览和实际创建的章节完全一致
    - 提升用户体验
    
    参数：
    - outline_id: 要展开的大纲ID
    - plans_request: 包含之前AI生成的章节规划列表
    
    返回：
    - 创建的章节列表和统计信息
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    
    # 获取大纲
    result = await db.execute(
        select(Outline).where(Outline.id == outline_id)
    )
    outline = result.scalar_one_or_none()
    
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")
    
    # 验证项目权限
    await verify_project_access(outline.project_id, user_id, db)
    
    try:
        # 验证规划数据
        if not plans_request.chapter_plans:
            raise HTTPException(status_code=400, detail="章节规划列表不能为空")
        
        logger.info(f"根据已有规划为大纲 {outline_id} 创建 {len(plans_request.chapter_plans)} 个章节")
        
        # 创建展开服务实例
        expansion_service = PlotExpansionService(user_ai_service)
        
        # 将Pydantic模型转换为字典列表
        chapter_plans_dict = [plan.model_dump() for plan in plans_request.chapter_plans]
        
        # 直接使用传入的规划创建章节记录（不调用AI）
        created_chapters = await expansion_service.create_chapters_from_plans(
            outline_id=outline_id,
            chapter_plans=chapter_plans_dict,
            project_id=outline.project_id,
            db=db,
            start_chapter_number=None  # 自动计算章节序号
        )
        
        await db.commit()
        
        # 刷新章节数据
        for chapter in created_chapters:
            await db.refresh(chapter)
        
        logger.info(f"成功根据已有规划创建 {len(created_chapters)} 个章节记录")
        
        # 构建响应
        return CreateChaptersFromPlansResponse(
            outline_id=outline_id,
            outline_title=outline.title,
            chapters_created=len(created_chapters),
            created_chapters=[
                {
                    "id": ch.id,
                    "chapter_number": ch.chapter_number,
                    "title": ch.title,
                    "summary": ch.summary,
                    "outline_id": ch.outline_id,
                    "sub_index": ch.sub_index,
                    "status": ch.status
                }
                for ch in created_chapters
            ]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"根据已有规划创建章节失败: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"创建章节失败: {str(e)}")