// src/pages/Dashboard.tsx
import React, { useEffect, useState } from 'react';
import { api, Profile, Document, Application } from '../api';
import { FileText, Database, Layers, CheckSquare, Plus, FilePlus, UserPlus } from 'lucide-react';

interface DashboardProps {
  activeProfile: Profile | null;
  onNavigate: (page: string) => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ activeProfile, onNavigate }) => {
  const [stats, setStats] = useState({
    docsCount: 0,
    fieldsCount: 0,
    templatesCount: 0,
    appsCount: 0,
  });
  const [recentDocs, setRecentDocs] = useState<Document[]>([]);
  const [recentApps, setRecentApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDashboardData = async () => {
      if (!activeProfile) return;
      setLoading(true);
      try {
        const [docsRes, fieldsRes, templatesRes, appsRes] = await Promise.all([
          api.documents.list(activeProfile.profile_id),
          api.profiles.getFields(activeProfile.profile_id),
          api.forms.list(),
          api.applications.list(),
        ]);

        const docs = docsRes.documents || [];
        const fields = fieldsRes.fields || [];
        const templates = templatesRes || [];
        const apps = appsRes.applications || [];

        setStats({
          docsCount: docs.length,
          fieldsCount: fields.length,
          templatesCount: templates.length,
          appsCount: apps.filter(a => a.profile_id === activeProfile.profile_id).length,
        });

        setRecentDocs(docs.slice(0, 5));
        setRecentApps(apps.filter(a => a.profile_id === activeProfile.profile_id).slice(0, 5));
      } catch (err) {
        console.error('Error fetching dashboard data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, [activeProfile]);

  if (!activeProfile) {
    return <div style={{ padding: '2rem', textAlign: 'center' }}>Please select or create a profile.</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: '2.5rem' }}>
        <h1 style={{ fontSize: '2.25rem', fontWeight: 700, marginBottom: '0.5rem' }}>
          Welcome back, <span style={{ color: 'var(--accent-indigo)' }}>{activeProfile.display_name}</span>
        </h1>
        <p style={{ color: 'var(--text-muted)' }}>
          Manage your document vault, review canonical profile facts, and fill government forms.
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid-3" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: '2.5rem' }}>
        <div className="glass-card stat-card">
          <div className="stat-icon">
            <FileText size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{stats.docsCount}</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Documents Vault</div>
          </div>
        </div>

        <div className="glass-card stat-card">
          <div className="stat-icon" style={{ color: 'var(--accent-purple)' }}>
            <Database size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{stats.fieldsCount}</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Extracted Profile Fields</div>
          </div>
        </div>

        <div className="glass-card stat-card">
          <div className="stat-icon" style={{ color: 'var(--accent-cyan)' }}>
            <Layers size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{stats.templatesCount}</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Forms Templates</div>
          </div>
        </div>

        <div className="glass-card stat-card">
          <div className="stat-icon" style={{ color: 'var(--color-success)' }}>
            <CheckSquare size={24} />
          </div>
          <div>
            <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{stats.appsCount}</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Submitted Applications</div>
          </div>
        </div>
      </div>

      {/* Quick Action Controls */}
      <div style={{ marginBottom: '2.5rem' }}>
        <h3 style={{ fontSize: '1.25rem', marginBottom: '1.25rem' }}>Quick Actions</h3>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <button className="btn btn-primary" onClick={() => onNavigate('vault')}>
            <Plus size={18} /> Upload Document
          </button>
          <button className="btn btn-secondary" onClick={() => onNavigate('forms')}>
            <FilePlus size={18} /> Parse & Fill Form
          </button>
          <button className="btn btn-secondary" onClick={() => onNavigate('profile')}>
            <UserPlus size={18} /> View Profile Data
          </button>
        </div>
      </div>

      {/* Two Columns: Recent Documents & Recent Applications */}
      <div className="grid-2">
        <div className="glass-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
            <h3 style={{ fontSize: '1.25rem' }}>Recent Documents</h3>
            <span 
              onClick={() => onNavigate('vault')}
              style={{ fontSize: '0.85rem', color: 'var(--accent-indigo)', cursor: 'pointer', fontWeight: 600 }}
            >
              View All
            </span>
          </div>

          {loading ? (
            <div style={{ color: 'var(--text-muted)' }}>Loading...</div>
          ) : recentDocs.length === 0 ? (
            <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '2rem' }}>
              No documents in vault yet.
            </div>
          ) : (
            <div>
              {recentDocs.map((doc) => (
                <div key={doc.id} className="list-item-row">
                  <div>
                    <div style={{ fontWeight: 600 }}>{doc.doc_type}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Version {doc.version} · {new Date(doc.uploaded_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div>
                    <span className={`badge ${
                      doc.verification_status === 'suspicious' ? 'badge-danger' : 
                      doc.verification_status === 'review' ? 'badge-warning' : 'badge-success'
                    }`}>
                      {doc.verification_status || 'Verified'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="glass-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
            <h3 style={{ fontSize: '1.25rem' }}>Recent Applications</h3>
            <span 
              onClick={() => onNavigate('applications')}
              style={{ fontSize: '0.85rem', color: 'var(--accent-indigo)', cursor: 'pointer', fontWeight: 600 }}
            >
              View All
            </span>
          </div>

          {loading ? (
            <div style={{ color: 'var(--text-muted)' }}>Loading...</div>
          ) : recentApps.length === 0 ? (
            <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '2rem' }}>
              No forms auto-filled yet.
            </div>
          ) : (
            <div>
              {recentApps.map((app) => (
                <div key={app.id} className="list-item-row">
                  <div>
                    <div style={{ fontWeight: 600 }}>
                      {app.scheme_name || `Form Instance #${app.id.substring(0, 8)}`}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Created: {new Date(app.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div>
                    <span className={`badge ${
                      app.status === 'submitted' ? 'badge-success' : 
                      app.status === 'needs_review' ? 'badge-warning' : 'badge-warning'
                    }`}>
                      {app.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
