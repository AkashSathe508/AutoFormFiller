// src/App.tsx
import React, { useEffect, useState } from 'react';
import { api, getAccessToken, clearTokens, Profile as UserProfile } from './api';
import { Auth } from './pages/Auth';
import { Dashboard } from './pages/Dashboard';
import { Vault } from './pages/Vault';
import { Profile } from './pages/Profile';
import { Forms } from './pages/Forms';
import { FormInstanceReview } from './pages/FormInstanceReview';
import { Applications } from './pages/Applications';
import { 
  Shield, 
  LayoutDashboard, 
  FolderLock, 
  Database, 
  Layers, 
  CheckSquare, 
  LogOut, 
  UserPlus, 
  ChevronDown,
  ChevronRight
} from 'lucide-react';

export const App: React.FC = () => {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(!!getAccessToken());
  const [profiles, setProfiles] = useState<UserProfile[]>([]);
  const [activeProfile, setActiveProfile] = useState<UserProfile | null>(null);
  const [activePage, setActivePage] = useState<string>('dashboard');
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [showProfileModal, setShowProfileModal] = useState(false);
  
  // Create profile form states
  const [newProfileName, setNewProfileName] = useState('');
  const [newProfileRelation, setNewProfileRelation] = useState('dependent');
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false);

  const fetchProfiles = async () => {
    try {
      const res = await api.profiles.list();
      setProfiles(res.profiles || []);
      
      // Auto-select 'self' or the first profile
      if (res.profiles && res.profiles.length > 0) {
        const selfProfile = res.profiles.find(p => p.relation_to_account === 'self');
        setActiveProfile(selfProfile || res.profiles[0]);
      }
    } catch (err) {
      console.error('Failed to load profiles:', err);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      fetchProfiles();
    }
  }, [isAuthenticated]);

  const handleLoginSuccess = () => {
    setIsAuthenticated(true);
    setActivePage('dashboard');
  };

  const handleLogout = async () => {
    await api.auth.logout();
    clearTokens();
    setIsAuthenticated(false);
    setActiveProfile(null);
    setProfiles([]);
  };

  const handleCreateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProfileName) return;

    try {
      const res = await api.profiles.create(newProfileName, newProfileRelation);
      setNewProfileName('');
      setShowProfileModal(false);
      
      // Re-fetch profiles and select the new one
      const listRes = await api.profiles.list();
      const list = listRes.profiles || [];
      setProfiles(list);
      const newlyCreated = list.find(p => p.profile_id === res.profile_id);
      if (newlyCreated) setActiveProfile(newlyCreated);
    } catch (err) {
      console.error('Failed to create family profile:', err);
    }
  };

  const selectPrefillInstance = (instanceId: string) => {
    setSelectedInstanceId(instanceId);
    setActivePage('prefill-review');
  };

  if (!isAuthenticated) {
    return <Auth onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <div className="app-container">
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <Shield size={22} style={{ color: 'var(--accent-indigo)' }} />
          <span>AutoFormFiller</span>
        </div>

        <nav className="sidebar-nav">
          <div 
            className={`nav-link ${activePage === 'dashboard' ? 'active' : ''}`}
            onClick={() => { setActivePage('dashboard'); setSelectedInstanceId(null); }}
          >
            <LayoutDashboard size={18} />
            <span>Dashboard</span>
          </div>

          <div 
            className={`nav-link ${activePage === 'vault' ? 'active' : ''}`}
            onClick={() => { setActivePage('vault'); setSelectedInstanceId(null); }}
          >
            <FolderLock size={18} />
            <span>Document Vault</span>
          </div>

          <div 
            className={`nav-link ${activePage === 'profile' ? 'active' : ''}`}
            onClick={() => { setActivePage('profile'); setSelectedInstanceId(null); }}
          >
            <Database size={18} />
            <span>Unified Profile</span>
          </div>

          <div 
            className={`nav-link ${activePage === 'forms' ? 'active' : ''}`}
            onClick={() => { setActivePage('forms'); setSelectedInstanceId(null); }}
          >
            <Layers size={18} />
            <span>Form Portal</span>
          </div>

          <div 
            className={`nav-link ${activePage === 'applications' ? 'active' : ''}`}
            onClick={() => { setActivePage('applications'); setSelectedInstanceId(null); }}
          >
            <CheckSquare size={18} />
            <span>Application Tracker</span>
          </div>
        </nav>

        <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1.5rem', marginTop: 'auto' }}>
          <div className="nav-link" onClick={handleLogout} style={{ color: 'var(--color-danger)' }}>
            <LogOut size={18} />
            <span>Logout</span>
          </div>
        </div>
      </aside>

      {/* Main Panel Content Area */}
      <main className="main-content">
        
        {/* Top Header Bar */}
        <header className="header-bar">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            <span>AutoFormFiller</span>
            <ChevronRight size={12} />
            <span style={{ textTransform: 'capitalize', color: 'var(--text-main)', fontWeight: 600 }}>{activePage.replace('-', ' ')}</span>
          </div>

          {/* Profile Switcher dropdown */}
          {activeProfile && (
            <div style={{ position: 'relative' }}>
              <div 
                className="profile-selector" 
                onClick={() => setProfileDropdownOpen(!profileDropdownOpen)}
              >
                <div className="profile-avatar">
                  {activeProfile.display_name.substring(0, 1).toUpperCase()}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', textAlign: 'left' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-main)' }}>{activeProfile.display_name}</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'capitalize' }}>
                    {activeProfile.relation_to_account === 'self' ? 'Primary Account' : activeProfile.relation_to_account}
                  </span>
                </div>
                <ChevronDown size={14} style={{ marginLeft: '0.25rem', color: 'var(--text-dim)' }} />
              </div>

              {profileDropdownOpen && (
                <div style={{
                  position: 'absolute', right: 0, top: '110%', width: '220px',
                  background: '#0d101d', border: '1px solid var(--border-color)',
                  borderRadius: '12px', boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                  zIndex: 200, padding: '0.5rem'
                }}>
                  {profiles.map(p => (
                    <div 
                      key={p.profile_id} 
                      onClick={() => {
                        setActiveProfile(p);
                        setProfileDropdownOpen(false);
                      }}
                      style={{
                        padding: '0.65rem 0.75rem', borderRadius: '8px', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', gap: '0.75rem',
                        background: activeProfile.profile_id === p.profile_id ? 'var(--accent-indigo-glow)' : 'transparent',
                        color: activeProfile.profile_id === p.profile_id ? '#c7d2fe' : 'var(--text-muted)'
                      }}
                    >
                      <div className="profile-avatar" style={{ width: '24px', height: '24px', fontSize: '0.75rem' }}>
                        {p.display_name.substring(0, 1).toUpperCase()}
                      </div>
                      <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>{p.display_name}</span>
                    </div>
                  ))}
                  <div style={{ borderTop: '1px solid var(--border-color)', margin: '0.5rem 0' }} />
                  <div 
                    onClick={() => {
                      setShowProfileModal(true);
                      setProfileDropdownOpen(false);
                    }}
                    style={{
                      padding: '0.65rem 0.75rem', borderRadius: '8px', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'var(--accent-indigo)'
                    }}
                  >
                    <UserPlus size={16} />
                    <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Add Family Profile</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </header>

        {/* Dynamic Route Container */}
        {activePage === 'dashboard' && (
          <Dashboard activeProfile={activeProfile} onNavigate={setActivePage} />
        )}
        {activePage === 'vault' && (
          <Vault activeProfile={activeProfile} />
        )}
        {activePage === 'profile' && (
          <Profile activeProfile={activeProfile} onProfileDeleted={fetchProfiles} />
        )}
        {activePage === 'forms' && (
          <Forms activeProfile={activeProfile} onSelectInstance={selectPrefillInstance} />
        )}
        {activePage === 'prefill-review' && selectedInstanceId && (
          <FormInstanceReview 
            instanceId={selectedInstanceId} 
            activeProfile={activeProfile} 
            onBack={() => setActivePage('forms')}
            onSubmitSuccess={() => setActivePage('applications')}
          />
        )}
        {activePage === 'applications' && (
          <Applications activeProfile={activeProfile} />
        )}
      </main>

      {/* Add Family Profile Modal */}
      {showProfileModal && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000, padding: '1rem'
        }}>
          <div className="glass-card" style={{ maxWidth: '440px', width: '100%' }}>
            <h3 style={{ fontSize: '1.4rem', marginBottom: '1.25rem' }}>Create Profile</h3>
            
            <form onSubmit={handleCreateProfile} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div className="form-group">
                <label htmlFor="pname">Family Member Name</label>
                <input
                  id="pname"
                  className="input-field"
                  type="text"
                  required
                  placeholder="e.g. Ramesh Kumar"
                  value={newProfileName}
                  onChange={(e) => setNewProfileName(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label htmlFor="prel">Relationship</label>
                <select
                  id="prel"
                  className="input-field"
                  value={newProfileRelation}
                  onChange={(e) => setNewProfileRelation(e.target.value)}
                  style={{ background: '#111322' }}
                >
                  <option value="father">Father</option>
                  <option value="mother">Mother</option>
                  <option value="spouse">Spouse</option>
                  <option value="child">Child</option>
                  <option value="dependent">Dependent</option>
                  <option value="other">Other</option>
                </select>
              </div>

              <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                <button className="btn btn-secondary" type="button" onClick={() => setShowProfileModal(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" type="submit" disabled={!newProfileName}>
                  Create Profile
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
