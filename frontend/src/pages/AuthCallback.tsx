import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Spin, Result, Button } from 'antd';
import { authApi } from '../services/api';
import AnnouncementModal from '../components/AnnouncementModal';

export default function AuthCallback() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [showAnnouncement, setShowAnnouncement] = useState(false);

  useEffect(() => {
    const handleCallback = async () => {
      try {
        // 后端会通过 Cookie 自动设置认证信息
        // 这里只需要验证登录状态
        await authApi.getCurrentUser();
        
        setStatus('success');
        
        // 从 sessionStorage 获取重定向地址
        const redirect = sessionStorage.getItem('login_redirect') || '/';
        sessionStorage.removeItem('login_redirect');
        
        // 检查今天是否已经显示过公告
        const doNotShowUntil = localStorage.getItem('announcement_do_not_show_until');
        const now = new Date().getTime();
        
        if (!doNotShowUntil || now > parseInt(doNotShowUntil)) {
          // 延迟一下再显示公告，让用户看到成功提示
          setTimeout(() => {
            setShowAnnouncement(true);
          }, 1000);
        } else {
          // 延迟一下再跳转，让用户看到成功提示
          setTimeout(() => {
            navigate(redirect);
          }, 1000);
        }
      } catch (error) {
        console.error('登录失败:', error);
        setStatus('error');
        setErrorMessage('登录失败，请重试');
      }
    };

    handleCallback();
  }, [navigate]);

  if (status === 'loading') {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}>
        <div style={{ textAlign: 'center' }}>
          <Spin size="large" />
          <div style={{ marginTop: 20, color: 'white', fontSize: 16 }}>
            正在处理登录...
          </div>
        </div>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}>
        <Result
          status="error"
          title="登录失败"
          subTitle={errorMessage}
          extra={
            <Button type="primary" onClick={() => navigate('/login')}>
              返回登录
            </Button>
          }
          style={{ background: 'white', padding: 40, borderRadius: 8 }}
        />
      </div>
    );
  }

  const handleAnnouncementClose = () => {
    setShowAnnouncement(false);
    const redirect = sessionStorage.getItem('login_redirect') || '/';
    sessionStorage.removeItem('login_redirect');
    navigate(redirect);
  };

  const handleDoNotShowToday = () => {
    // 设置到今天23:59:59不再显示
    const tomorrow = new Date();
    tomorrow.setHours(23, 59, 59, 999);
    localStorage.setItem('announcement_do_not_show_until', tomorrow.getTime().toString());
  };

  return (
    <>
      <AnnouncementModal
        visible={showAnnouncement}
        onClose={handleAnnouncementClose}
        onDoNotShowToday={handleDoNotShowToday}
      />
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}>
        <Result
          status="success"
          title="登录成功"
          subTitle={showAnnouncement ? "欢迎使用..." : "正在跳转..."}
          style={{ background: 'white', padding: 40, borderRadius: 8 }}
        />
      </div>
    </>
  );
}