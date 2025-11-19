"""章节重新生成服务"""
from typing import Dict, Any, AsyncGenerator, Optional, List
from app.services.ai_service import AIService
from app.services.prompt_service import prompt_service
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis
from app.schemas.regeneration import ChapterRegenerateRequest, PreserveElementsConfig
from app.logger import get_logger
import difflib

logger = get_logger(__name__)


class ChapterRegenerator:
    """章节重新生成服务"""
    
    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service
        logger.info("✅ ChapterRegenerator初始化成功")
    
    async def regenerate_with_feedback(
        self,
        chapter: Chapter,
        analysis: Optional[PlotAnalysis],
        regenerate_request: ChapterRegenerateRequest,
        project_context: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        根据反馈重新生成章节（流式）
        
        Args:
            chapter: 原始章节对象
            analysis: 分析结果（可选）
            regenerate_request: 重新生成请求参数
            project_context: 项目上下文（项目信息、角色、大纲等）
        
        Yields:
            包含类型和数据的字典: {'type': 'progress'/'chunk', 'data': ...}
        """
        try:
            logger.info(f"🔄 开始重新生成章节: 第{chapter.chapter_number}章")
            
            # 1. 构建修改指令
            yield {'type': 'progress', 'progress': 5, 'message': '正在构建修改指令...'}
            modification_instructions = self._build_modification_instructions(
                analysis=analysis,
                regenerate_request=regenerate_request
            )
            
            logger.info(f"📝 修改指令构建完成，长度: {len(modification_instructions)}字符")
            
            # 2. 构建完整提示词
            yield {'type': 'progress', 'progress': 10, 'message': '正在构建生成提示词...'}
            full_prompt = self._build_regeneration_prompt(
                chapter=chapter,
                modification_instructions=modification_instructions,
                project_context=project_context,
                regenerate_request=regenerate_request
            )
            
            logger.info(f"🎯 提示词构建完成，开始AI生成")
            yield {'type': 'progress', 'progress': 15, 'message': '开始AI生成内容...'}
            
            # 3. 流式生成新内容，同时跟踪进度
            target_word_count = regenerate_request.target_word_count
            accumulated_length = 0
            
            async for chunk in self.ai_service.generate_text_stream(
                prompt=full_prompt,
                temperature=0.7
            ):
                # 发送内容块
                yield {'type': 'chunk', 'content': chunk}
                
                # 更新累积字数并计算进度（15%-95%）
                accumulated_length += len(chunk)
                # 进度从15%开始，到95%结束，为后处理预留5%
                generation_progress = min(15 + (accumulated_length / target_word_count) * 80, 95)
                yield {'type': 'progress', 'progress': int(generation_progress), 'word_count': accumulated_length}
            
            logger.info(f"✅ 章节重新生成完成，共生成 {accumulated_length} 字")
            yield {'type': 'progress', 'progress': 100, 'message': '生成完成'}
            
        except Exception as e:
            logger.error(f"❌ 重新生成失败: {str(e)}", exc_info=True)
            raise
    
    def _build_modification_instructions(
        self,
        analysis: Optional[PlotAnalysis],
        regenerate_request: ChapterRegenerateRequest
    ) -> str:
        """构建修改指令"""
        
        instructions = []
        
        # 标题
        instructions.append("# 章节修改指令\n")
        
        # 1. 来自分析的建议
        if (analysis and 
            regenerate_request.selected_suggestion_indices and 
            analysis.suggestions):
            
            instructions.append("## 📋 需要改进的问题（来自AI分析）：\n")
            for idx in regenerate_request.selected_suggestion_indices:
                if 0 <= idx < len(analysis.suggestions):
                    suggestion = analysis.suggestions[idx]
                    instructions.append(f"{idx + 1}. {suggestion}")
            instructions.append("")
        
        # 2. 用户自定义指令
        if regenerate_request.custom_instructions:
            instructions.append("## ✍️ 用户自定义修改要求：\n")
            instructions.append(regenerate_request.custom_instructions)
            instructions.append("")
        
        # 3. 重点优化方向
        if regenerate_request.focus_areas:
            instructions.append("## 🎯 重点优化方向：\n")
            focus_map = {
                "pacing": "节奏把控 - 调整叙事速度，避免拖沓或过快",
                "emotion": "情感渲染 - 深化人物情感表达，增强感染力",
                "description": "场景描写 - 丰富环境细节，增强画面感",
                "dialogue": "对话质量 - 让对话更自然真实，推动剧情",
                "conflict": "冲突强度 - 强化矛盾冲突，提升戏剧张力"
            }
            
            for area in regenerate_request.focus_areas:
                if area in focus_map:
                    instructions.append(f"- {focus_map[area]}")
            instructions.append("")
        
        # 4. 保留要求
        if regenerate_request.preserve_elements:
            preserve = regenerate_request.preserve_elements
            instructions.append("## 🔒 必须保留的元素：\n")
            
            if preserve.preserve_structure:
                instructions.append("- 保持原章节的整体结构和情节框架")
            
            if preserve.preserve_dialogues:
                instructions.append("- 必须保留以下关键对话：")
                for dialogue in preserve.preserve_dialogues:
                    instructions.append(f"  * {dialogue}")
            
            if preserve.preserve_plot_points:
                instructions.append("- 必须保留以下关键情节点：")
                for plot in preserve.preserve_plot_points:
                    instructions.append(f"  * {plot}")
            
            if preserve.preserve_character_traits:
                instructions.append("- 保持所有角色的性格特征和行为模式一致")
            
            instructions.append("")
        
        return "\n".join(instructions)
    
    def _build_regeneration_prompt(
        self,
        chapter: Chapter,
        modification_instructions: str,
        project_context: Dict[str, Any],
        regenerate_request: ChapterRegenerateRequest
    ) -> str:
        """构建完整的重新生成提示词"""
        
        prompt_parts = []
        
        # 系统角色
        prompt_parts.append("""你是一位经验丰富的专业小说编辑和作家。现在需要根据反馈意见重新创作一个章节。

你的任务是：
1. 仔细理解原章节的内容和意图
2. 认真分析所有的修改要求
3. 在保持故事连贯性的前提下，创作一个改进后的新版本
4. 确保新版本在艺术性和可读性上都有明显提升

---
""")
        
        # 原始章节信息
        prompt_parts.append(f"""## 📖 原始章节信息

**章节**：第{chapter.chapter_number}章
**标题**：{chapter.title}
**字数**：{chapter.word_count}字

**原始内容**：
{chapter.content}

---
""")
        
        # 修改指令
        prompt_parts.append(modification_instructions)
        prompt_parts.append("\n---\n")
        
        # 项目背景信息
        prompt_parts.append(f"""## 🌍 项目背景信息

**小说标题**：{project_context.get('project_title', '未知')}
**题材**：{project_context.get('genre', '未设定')}
**主题**：{project_context.get('theme', '未设定')}
**叙事视角**：{project_context.get('narrative_perspective', '第三人称')}
**世界观设定**：
- 时代背景：{project_context.get('time_period', '未设定')}
- 地理位置：{project_context.get('location', '未设定')}
- 氛围基调：{project_context.get('atmosphere', '未设定')}

---
""")
        
        # 角色信息
        if project_context.get('characters_info'):
            prompt_parts.append(f"""## 👥 角色信息

{project_context['characters_info']}

---
""")
        
        # 章节大纲
        if project_context.get('chapter_outline'):
            prompt_parts.append(f"""## 📝 本章大纲

{project_context['chapter_outline']}

---
""")
        
        # 前置章节上下文
        if project_context.get('previous_context'):
            prompt_parts.append(f"""## 📚 前置章节上下文

{project_context['previous_context']}

---
""")
        
        # 创作要求
        prompt_parts.append(f"""## ✨ 创作要求

1. **解决问题**：针对上述修改指令中提到的所有问题进行改进
2. **保持连贯**：确保与前后章节的情节、人物、风格保持一致
3. **提升质量**：在节奏、情感、描写等方面明显优于原版
4. **保留精华**：保持原章节中优秀的部分和关键情节
5. **字数控制**：目标字数约{regenerate_request.target_word_count}字（可适当浮动±20%）

---

## 🎬 开始创作

请现在开始创作改进后的新版本章节内容。

**重要提示**：
- 直接输出章节正文内容，从故事内容开始写
- **不要**输出章节标题（如"第X章"、"第X章：XXX"等）
- **不要**输出任何额外的说明、注释或元数据
- 只需要纯粹的故事正文内容

现在开始：
""")
        
        return "\n".join(prompt_parts)
    
    def calculate_content_diff(
        self,
        original_content: str,
        new_content: str
    ) -> Dict[str, Any]:
        """
        计算两个版本的差异
        
        Returns:
            差异统计信息
        """
        # 基本统计
        diff_stats = {
            'original_length': len(original_content),
            'new_length': len(new_content),
            'length_change': len(new_content) - len(original_content),
            'length_change_percent': round((len(new_content) - len(original_content)) / len(original_content) * 100, 2) if len(original_content) > 0 else 0
        }
        
        # 计算相似度
        similarity = difflib.SequenceMatcher(None, original_content, new_content).ratio()
        diff_stats['similarity'] = round(similarity * 100, 2)
        diff_stats['difference'] = round((1 - similarity) * 100, 2)
        
        # 段落统计
        original_paragraphs = [p for p in original_content.split('\n\n') if p.strip()]
        new_paragraphs = [p for p in new_content.split('\n\n') if p.strip()]
        diff_stats['original_paragraph_count'] = len(original_paragraphs)
        diff_stats['new_paragraph_count'] = len(new_paragraphs)
        
        return diff_stats


# 全局实例
_regenerator_instance = None

def get_chapter_regenerator(ai_service: AIService) -> ChapterRegenerator:
    """获取章节重新生成器实例"""
    global _regenerator_instance
    if _regenerator_instance is None:
        _regenerator_instance = ChapterRegenerator(ai_service)
    return _regenerator_instance