import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Form, Input, InputNumber, Select, Button, message, Card,
  Row, Col, Typography, Space, Progress
} from 'antd';
import {
  RocketOutlined, ArrowLeftOutlined, CheckCircleOutlined,
  LoadingOutlined
} from '@ant-design/icons';
import { wizardStreamApi } from '../services/api';
import type { WizardBasicInfo, ApiError } from '../types';
import { SSELoadingOverlay } from '../components/SSELoadingOverlay';

const { TextArea } = Input;
const { Title, Paragraph, Text } = Typography;

export default function ProjectWizardNew() {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  
  // 状态管理
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState<'form' | 'generating' | 'complete'>('form');
  const [projectId, setProjectId] = useState<string>('');
  const [projectTitle, setProjectTitle] = useState<string>('');
  
  // SSE流式进度状态
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [generationSteps, setGenerationSteps] = useState<{
    worldBuilding: 'pending' | 'processing' | 'completed' | 'error';
    characters: 'pending' | 'processing' | 'completed' | 'error';
    outline: 'pending' | 'processing' | 'completed' | 'error';
  }>({
    worldBuilding: 'pending',
    characters: 'pending',
    outline: 'pending'
  });

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 自动化生成流程
  const handleAutoGenerate = async (values: WizardBasicInfo) => {
    try {
      setLoading(true);
      setCurrentStep('generating');
      setProjectTitle(values.title);
      setProgress(0);
      setProgressMessage('开始创建项目...');

      // 步骤1: 生成世界观并创建项目
      setGenerationSteps(prev => ({ ...prev, worldBuilding: 'processing' }));
      setProgressMessage('正在生成世界观...');
      
      const worldResult = await wizardStreamApi.generateWorldBuildingStream(
        {
          title: values.title,
          description: values.description,
          theme: values.theme,
          genre: Array.isArray(values.genre) ? values.genre.join('、') : values.genre,
          narrative_perspective: values.narrative_perspective,
          target_words: values.target_words,
          chapter_count: values.chapter_count || 30,
          character_count: values.character_count || 5,
        },
        {
          onProgress: (msg, prog) => {
            setProgress(Math.floor(prog / 3)); // 0-33%
            setProgressMessage(msg);
          },
          onResult: (data) => {
            setProjectId(data.project_id);
            setGenerationSteps(prev => ({ ...prev, worldBuilding: 'completed' }));
          },
          onError: (error) => {
            setGenerationSteps(prev => ({ ...prev, worldBuilding: 'error' }));
            throw new Error(error);
          },
          onComplete: () => {
            console.log('世界观生成完成');
          }
        }
      );

      if (!worldResult?.project_id) {
        throw new Error('项目创建失败');
      }

      const createdProjectId = worldResult.project_id;
      setProjectId(createdProjectId);

      // 步骤2: 生成角色
      setGenerationSteps(prev => ({ ...prev, characters: 'processing' }));
      setProgressMessage('正在生成角色...');
      
      await wizardStreamApi.generateCharactersStream(
        {
          project_id: createdProjectId,
          count: values.character_count || 5,
          world_context: {
            time_period: worldResult.time_period || '',
            location: worldResult.location || '',
            atmosphere: worldResult.atmosphere || '',
            rules: worldResult.rules || '',
          },
          theme: values.theme,
          genre: Array.isArray(values.genre) ? values.genre.join('、') : values.genre,
        },
        {
          onProgress: (msg, prog) => {
            setProgress(33 + Math.floor(prog / 3)); // 33-66%
            setProgressMessage(msg);
          },
          onResult: (data) => {
            console.log(`成功生成${data.characters?.length || 0}个角色`);
            setGenerationSteps(prev => ({ ...prev, characters: 'completed' }));
          },
          onError: (error) => {
            setGenerationSteps(prev => ({ ...prev, characters: 'error' }));
            throw new Error(error);
          },
          onComplete: () => {
            console.log('角色生成完成');
          }
        }
      );

      // 步骤3: 生成大纲
      setGenerationSteps(prev => ({ ...prev, outline: 'processing' }));
      setProgressMessage('正在生成大纲...');
      
      await wizardStreamApi.generateCompleteOutlineStream(
        {
          project_id: createdProjectId,
          chapter_count: 3, // 生成3个大纲节点（不展开）
          narrative_perspective: values.narrative_perspective,
          target_words: values.target_words,
        },
        {
          onProgress: (msg, prog) => {
            setProgress(66 + Math.floor(prog / 3)); // 66-99%
            setProgressMessage(msg);
          },
          onResult: () => {
            console.log('大纲生成完成');
            setGenerationSteps(prev => ({ ...prev, outline: 'completed' }));
          },
          onError: (error) => {
            setGenerationSteps(prev => ({ ...prev, outline: 'error' }));
            throw new Error(error);
          },
          onComplete: () => {
            console.log('大纲生成完成');
          }
        }
      );

      // 全部完成
      setProgress(100);
      setProgressMessage('项目创建完成！');
      setCurrentStep('complete');
      message.success('项目创建成功！');
      
    } catch (error) {
      const apiError = error as ApiError;
      message.error('创建项目失败：' + (apiError.response?.data?.detail || apiError.message || '未知错误'));
      setCurrentStep('form');
      setGenerationSteps({
        worldBuilding: 'pending',
        characters: 'pending',
        outline: 'pending'
      });
    } finally {
      setLoading(false);
    }
  };

  // 渲染表单页面
  const renderForm = () => (
    <Card>
      <Title level={isMobile ? 4 : 3} style={{ marginBottom: 24 }}>
        创建新项目
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 32 }}>
        填写基本信息后，AI将自动为您生成世界观、角色和大纲节点（大纲可在项目内手动展开为章节）
      </Paragraph>

      <Form
        form={form}
        layout="vertical"
        onFinish={handleAutoGenerate}
        initialValues={{
          genre: ['玄幻'],
          chapter_count: 30,
          narrative_perspective: '第三人称',
          character_count: 5,
          target_words: 100000,
        }}
      >
        <Form.Item
          label="书名"
          name="title"
          rules={[{ required: true, message: '请输入书名' }]}
        >
          <Input placeholder="输入你的小说标题" size="large" />
        </Form.Item>

        <Form.Item
          label="小说简介"
          name="description"
          rules={[{ required: true, message: '请输入小说简介' }]}
        >
          <TextArea
            rows={3}
            placeholder="用一段话介绍你的小说..."
            showCount
            maxLength={300}
          />
        </Form.Item>

        <Form.Item
          label="主题"
          name="theme"
          rules={[{ required: true, message: '请输入主题' }]}
        >
          <TextArea
            rows={4}
            placeholder="描述你的小说主题..."
            showCount
            maxLength={500}
          />
        </Form.Item>

        <Form.Item
          label="类型"
          name="genre"
          rules={[{ required: true, message: '请选择小说类型' }]}
        >
          <Select
            mode="tags"
            placeholder="选择或输入类型标签（如：玄幻、都市、修仙）"
            size="large"
            tokenSeparators={[',']}
            maxTagCount={5}
          >
            <Select.Option value="玄幻">玄幻</Select.Option>
            <Select.Option value="都市">都市</Select.Option>
            <Select.Option value="历史">历史</Select.Option>
            <Select.Option value="科幻">科幻</Select.Option>
            <Select.Option value="武侠">武侠</Select.Option>
            <Select.Option value="仙侠">仙侠</Select.Option>
            <Select.Option value="奇幻">奇幻</Select.Option>
            <Select.Option value="悬疑">悬疑</Select.Option>
            <Select.Option value="言情">言情</Select.Option>
            <Select.Option value="修仙">修仙</Select.Option>
          </Select>
        </Form.Item>

        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item
              label="叙事视角"
              name="narrative_perspective"
              rules={[{ required: true, message: '请选择叙事视角' }]}
            >
              <Select size="large" placeholder="选择小说的叙事视角">
                <Select.Option value="第一人称">第一人称</Select.Option>
                <Select.Option value="第三人称">第三人称</Select.Option>
                <Select.Option value="全知视角">全知视角</Select.Option>
              </Select>
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item
              label="角色数量"
              name="character_count"
              rules={[{ required: true, message: '请输入角色数量' }]}
            >
              <InputNumber
                min={3}
                max={20}
                style={{ width: '100%' }}
                size="large"
                addonAfter="个"
                placeholder="AI生成的角色数量"
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          label="目标字数"
          name="target_words"
          rules={[{ required: true, message: '请输入目标字数' }]}
        >
          <InputNumber
            min={10000}
            style={{ width: '100%' }}
            size="large"
            addonAfter="字"
            placeholder="整部小说的目标字数"
          />
        </Form.Item>

        <Form.Item>
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={loading}
              icon={<RocketOutlined />}
            >
              开始创建项目
            </Button>
            <Button
              size="large"
              block
              onClick={() => navigate('/')}
            >
              返回首页
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );

  // 渲染生成进度页面
  const renderGenerating = () => {
    const getStepStatus = (step: 'pending' | 'processing' | 'completed' | 'error') => {
      if (step === 'completed') return { icon: <CheckCircleOutlined />, color: '#52c41a' };
      if (step === 'processing') return { icon: <LoadingOutlined />, color: '#1890ff' };
      if (step === 'error') return { icon: '✗', color: '#ff4d4f' };
      return { icon: '○', color: '#d9d9d9' };
    };

    return (
      <Card>
        <div style={{ textAlign: 'center', padding: isMobile ? '32px 16px' : '40px 0' }}>
          <Title level={isMobile ? 4 : 3} style={{ marginBottom: 32 }}>
            正在为《{projectTitle}》生成内容
          </Title>

          <Progress
            percent={progress}
            status={progress === 100 ? 'success' : 'active'}
            strokeColor={{
              '0%': '#667eea',
              '100%': '#764ba2',
            }}
            style={{ marginBottom: 32 }}
          />

          <Paragraph style={{ fontSize: 16, marginBottom: 48, color: '#666' }}>
            {progressMessage}
          </Paragraph>

          <Space direction="vertical" size={24} style={{ width: '100%', maxWidth: 400, margin: '0 auto' }}>
            {[
              { key: 'worldBuilding', label: '生成世界观', step: generationSteps.worldBuilding },
              { key: 'characters', label: '生成角色', step: generationSteps.characters },
              { key: 'outline', label: '生成大纲', step: generationSteps.outline },
            ].map(({ key, label, step }) => {
              const status = getStepStatus(step);
              return (
                <div
                  key={key}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 20px',
                    background: step === 'processing' ? '#f0f5ff' : '#fafafa',
                    borderRadius: 8,
                    border: `1px solid ${step === 'processing' ? '#d6e4ff' : '#f0f0f0'}`,
                  }}
                >
                  <Text style={{ fontSize: 16, fontWeight: step === 'processing' ? 600 : 400 }}>
                    {label}
                  </Text>
                  <span style={{ fontSize: 20, color: status.color }}>
                    {status.icon}
                  </span>
                </div>
              );
            })}
          </Space>

          <Paragraph type="secondary" style={{ marginTop: 48 }}>
            请耐心等待，AI正在为您精心创作...
          </Paragraph>
        </div>
      </Card>
    );
  };

  // 渲染完成页面
  const renderComplete = () => (
    <Card>
      <div style={{
        textAlign: 'center',
        padding: isMobile ? '32px 16px' : '40px 0'
      }}>
        <div style={{
          fontSize: isMobile ? 56 : 72,
          color: '#52c41a',
          marginBottom: isMobile ? 16 : 24
        }}>
          ✓
        </div>
        <Title
          level={isMobile ? 3 : 2}
          style={{
            color: '#52c41a',
            marginBottom: isMobile ? 8 : 16
          }}
        >
          项目创建完成！
        </Title>
        <Paragraph style={{
          fontSize: isMobile ? 14 : 16,
          marginTop: isMobile ? 16 : 24,
          marginBottom: isMobile ? 32 : 48,
        }}>
          《{projectTitle}》已成功创建，包含完整的世界观、角色和大纲节点
        </Paragraph>
        <Paragraph type="secondary" style={{
          fontSize: isMobile ? 12 : 14,
          marginTop: 8,
        }}>
          💡 提示：进入项目后，可在"大纲"页面将大纲节点展开为详细章节
        </Paragraph>
        
        <Space
          size={isMobile ? 12 : 16}
          direction={isMobile ? 'vertical' : 'horizontal'}
          style={{ width: isMobile ? '100%' : 'auto' }}
        >
          <Button
            size="large"
            onClick={() => navigate('/')}
            block={isMobile}
            style={{
              minWidth: 120,
              height: isMobile ? 44 : 40
            }}
          >
            返回首页
          </Button>
          <Button
            type="primary"
            size="large"
            icon={<RocketOutlined />}
            onClick={() => navigate(`/project/${projectId}`)}
            block={isMobile}
            style={{
              minWidth: 120,
              height: isMobile ? 44 : 40
            }}
          >
            进入项目
          </Button>
        </Space>
      </div>
    </Card>
  );

  return (
    <div style={{
      minHeight: '100vh',
      background: '#f5f7fa',
    }}>
      {/* 顶部标题栏 - 固定不滚动 */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      }}>
        <div style={{
          maxWidth: 1200,
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: isMobile ? '12px 16px' : '16px 24px',
        }}>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
            size={isMobile ? 'middle' : 'large'}
            disabled={currentStep === 'generating'}
            style={{
              background: 'rgba(255,255,255,0.2)',
              borderColor: 'rgba(255,255,255,0.3)',
              color: '#fff',
            }}
          >
            {isMobile ? '返回' : '返回首页'}
          </Button>
          
          <Title level={isMobile ? 4 : 2} style={{
            margin: 0,
            color: '#fff',
            textShadow: '0 2px 4px rgba(0,0,0,0.1)',
          }}>
            项目创建向导
          </Title>
          
          <div style={{ width: isMobile ? 60 : 120 }}></div>
        </div>
      </div>

      {/* 内容区域 */}
      <div style={{
        maxWidth: 800,
        margin: '0 auto',
        padding: isMobile ? '16px 12px' : '24px 24px',
      }}>
        {currentStep === 'form' && renderForm()}
        {currentStep === 'generating' && renderGenerating()}
        {currentStep === 'complete' && renderComplete()}
      </div>

      {/* SSE加载覆盖层 */}
      <SSELoadingOverlay
        loading={loading}
        progress={progress}
        message={progressMessage}
      />
    </div>
  );
}