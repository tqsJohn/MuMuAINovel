-- 为Chapter表添加与Outline的关联关系
-- 实现大纲到章节的一对多关系

-- 添加outline_id外键字段
ALTER TABLE chapters 
ADD COLUMN outline_id VARCHAR(36) NULL;

-- 添加sub_index字段，表示在该大纲下的子章节序号
ALTER TABLE chapters 
ADD COLUMN sub_index INTEGER DEFAULT 1;

-- 添加字段注释（PostgreSQL语法）
COMMENT ON COLUMN chapters.outline_id IS '关联的大纲ID';
COMMENT ON COLUMN chapters.sub_index IS '大纲下的子章节序号';

-- 添加外键约束
ALTER TABLE chapters 
ADD CONSTRAINT fk_chapter_outline 
    FOREIGN KEY (outline_id) 
    REFERENCES outlines(id) 
    ON DELETE SET NULL;

-- 创建索引优化查询性能
CREATE INDEX idx_chapters_outline_id ON chapters(outline_id);
CREATE INDEX idx_chapters_outline_sub ON chapters(outline_id, sub_index);

-- 说明：
-- outline_id为NULL表示旧数据或独立章节
-- outline_id有值表示该章节由某个大纲展开生成
-- sub_index表示在该大纲下的第几个子章节（从1开始）

-- 为 chapters 表添加 expansion_plan 字段
-- 用于存储大纲展开规划的详细数据（JSON格式）

-- 添加字段
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS expansion_plan TEXT;

-- 添加注释
COMMENT ON COLUMN chapters.expansion_plan IS '展开规划详情(JSON): 包含key_events, character_focus, emotional_tone等';

-- 查看修改结果
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns 
WHERE table_name = 'chapters' 
ORDER BY ordinal_position;