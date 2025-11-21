"""导入导出相关的Pydantic模型"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ExportOptions(BaseModel):
    """导出选项"""
    include_generation_history: bool = Field(False, description="是否包含生成历史")
    include_writing_styles: bool = Field(True, description="是否包含写作风格")


class ChapterExportData(BaseModel):
    """章节导出数据"""
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    chapter_number: int
    word_count: int = 0
    status: str = "draft"
    created_at: Optional[str] = None
    
    # 大纲细化功能新增字段
    outline_title: Optional[str] = None  # 关联的大纲标题（用于导入时重建关联）
    sub_index: Optional[int] = None  # 大纲下的子章节序号
    expansion_plan: Optional[Dict[str, Any]] = None  # 展开规划详情（JSON对象）


class CharacterExportData(BaseModel):
    """角色导出数据"""
    name: str
    age: Optional[str] = None
    gender: Optional[str] = None
    is_organization: bool = False
    role_type: Optional[str] = None
    personality: Optional[str] = None
    background: Optional[str] = None
    appearance: Optional[str] = None
    traits: Optional[List[str]] = None
    organization_type: Optional[str] = None
    organization_purpose: Optional[str] = None
    created_at: Optional[str] = None


class OutlineExportData(BaseModel):
    """大纲导出数据"""
    title: str
    content: Optional[str] = None
    structure: Optional[str] = None
    order_index: Optional[int] = None
    created_at: Optional[str] = None


class RelationshipExportData(BaseModel):
    """关系导出数据"""
    source_name: str
    target_name: str
    relationship_name: Optional[str] = None
    intimacy_level: int = 50
    status: str = "active"
    description: Optional[str] = None
    started_at: Optional[str] = None


class OrganizationExportData(BaseModel):
    """组织详情导出数据"""
    character_name: str
    parent_org_name: Optional[str] = None
    power_level: int = 50
    member_count: int = 0
    location: Optional[str] = None
    motto: Optional[str] = None
    color: Optional[str] = None


class OrganizationMemberExportData(BaseModel):
    """组织成员导出数据"""
    organization_name: str
    character_name: str
    position: str
    rank: int = 0
    status: str = "active"
    joined_at: Optional[str] = None
    loyalty: int = 50
    contribution: int = 0
    notes: Optional[str] = None


class WritingStyleExportData(BaseModel):
    """写作风格导出数据"""
    name: str
    style_type: str
    preset_id: Optional[str] = None
    description: Optional[str] = None
    prompt_content: str
    order_index: int = 0


class GenerationHistoryExportData(BaseModel):
    """生成历史导出数据"""
    chapter_title: Optional[str] = None
    prompt: Optional[str] = None
    generated_content: Optional[str] = None
    model: Optional[str] = None
    tokens_used: Optional[int] = None
    generation_time: Optional[float] = None
    created_at: Optional[str] = None


class ProjectExportData(BaseModel):
    """项目完整导出数据"""
    version: str = "1.0.0"
    export_time: str
    project: Dict[str, Any]
    chapters: List[ChapterExportData] = []
    characters: List[CharacterExportData] = []
    outlines: List[OutlineExportData] = []
    relationships: List[RelationshipExportData] = []
    organizations: List[OrganizationExportData] = []
    organization_members: List[OrganizationMemberExportData] = []
    writing_styles: List[WritingStyleExportData] = []
    generation_history: List[GenerationHistoryExportData] = []


class ImportValidationResult(BaseModel):
    """导入验证结果"""
    valid: bool
    version: str
    project_name: Optional[str] = None
    statistics: Dict[str, int] = {}
    errors: List[str] = []
    warnings: List[str] = []


class ImportResult(BaseModel):
    """导入结果"""
    success: bool
    project_id: Optional[str] = None
    message: str
    statistics: Dict[str, int] = {}
    warnings: List[str] = []