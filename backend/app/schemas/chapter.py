"""章节相关的Pydantic模型"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ChapterBase(BaseModel):
    """章节基础模型"""
    title: str = Field(..., description="章节标题")
    chapter_number: int = Field(..., description="章节序号")
    content: Optional[str] = Field(None, description="章节内容")
    summary: Optional[str] = Field(None, description="章节摘要")
    word_count: Optional[int] = Field(0, description="字数")
    status: Optional[str] = Field("draft", description="章节状态")
    outline_id: Optional[str] = Field(None, description="关联的大纲ID")
    sub_index: Optional[int] = Field(1, description="大纲下的子章节序号")
    expansion_plan: Optional[str] = Field(None, description="展开规划详情(JSON)")


class ChapterCreate(BaseModel):
    """创建章节的请求模型"""
    project_id: str = Field(..., description="所属项目ID")
    title: str = Field(..., description="章节标题")
    chapter_number: int = Field(..., description="章节序号")
    content: Optional[str] = Field(None, description="章节内容")
    summary: Optional[str] = Field(None, description="章节摘要")
    status: Optional[str] = Field("draft", description="章节状态")
    outline_id: Optional[str] = Field(None, description="关联的大纲ID")
    sub_index: Optional[int] = Field(1, description="大纲下的子章节序号")
    expansion_plan: Optional[str] = Field(None, description="展开规划详情(JSON)")


class ChapterUpdate(BaseModel):
    """更新章节的请求模型"""
    title: Optional[str] = None
    content: Optional[str] = None
    # chapter_number 不允许修改，只能通过大纲的重排序来调整
    summary: Optional[str] = None
    # word_count 自动计算，不允许手动修改
    status: Optional[str] = None


class ChapterResponse(BaseModel):
    """章节响应模型"""
    id: str
    project_id: str
    title: str
    chapter_number: int
    content: Optional[str] = None
    summary: Optional[str] = None
    word_count: int = 0
    status: str
    outline_id: Optional[str] = None
    sub_index: Optional[int] = 1
    expansion_plan: Optional[str] = None
    outline_title: Optional[str] = None  # 大纲标题（从Outline表联查）
    outline_order: Optional[int] = None  # 大纲排序序号（从Outline表联查）
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ChapterListResponse(BaseModel):
    """章节列表响应模型"""
    total: int
    items: list[ChapterResponse]


class ChapterGenerateRequest(BaseModel):
    """AI生成章节内容的请求模型"""
    style_id: Optional[int] = Field(None, description="写作风格ID，不提供则不使用任何风格")
    target_word_count: Optional[int] = Field(
        3000,
        description="目标字数，默认3000字",
        ge=500,   # 最小500字
        le=10000  # 最大10000字
    )
    enable_mcp: bool = Field(True, description="是否启用MCP工具增强（搜索参考资料）")


class BatchGenerateRequest(BaseModel):
    """批量生成章节的请求模型"""
    start_chapter_number: int = Field(..., description="起始章节序号")
    count: int = Field(..., description="生成章节数量", ge=1, le=20)
    style_id: Optional[int] = Field(None, description="写作风格ID")
    target_word_count: Optional[int] = Field(
        3000,
        description="目标字数，默认3000字",
        ge=500,
        le=10000
    )
    enable_analysis: bool = Field(False, description="是否启用同步分析")
    enable_mcp: bool = Field(True, description="是否启用MCP工具增强（搜索参考资料）")
    max_retries: int = Field(3, description="每个章节的最大重试次数", ge=0, le=5)


class BatchGenerateResponse(BaseModel):
    """批量生成响应模型"""
    batch_id: str = Field(..., description="批次ID")
    message: str = Field(..., description="响应消息")
    chapters_to_generate: list[dict] = Field(..., description="待生成章节列表")
    estimated_time_minutes: int = Field(..., description="预估耗时（分钟）")


class BatchGenerateStatusResponse(BaseModel):
    """批量生成状态响应模型"""
    batch_id: str
    status: str
    total: int
    completed: int
    current_chapter_id: Optional[str] = None
    current_chapter_number: Optional[int] = None
    current_retry_count: Optional[int] = None
    max_retries: Optional[int] = None
    failed_chapters: list[dict] = []
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None