// src/pages/Applications.tsx
import React, { useEffect, useState } from 'react';
import { api, Application, Profile } from '../api';
import { ClipboardList, Calendar, Info, Clock, CheckSquare, Edit, RefreshCw } from 'lucide-react';

interface ApplicationsProps {
  activeProfile: Profile | null;
}

export const Applications: React.FC<ApplicationsProps> = ({ activeProfile }) => {
  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedApp, setSelectedApp] = useState<Application | null>(null);
  const [loading, setLoading] = useState(true);
  const [newStatus, setNewStatus] = useState('submitted');
  const [statusNote, setStatusNote] = useState('');
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState('');

  const fetchApps = async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const res = await api.applications.list();
      const filtered = (res.applications || []).filter(
        a => a.profile_id === activeProfile.profile_id
      );
      setApplications(filtered);
      
      // Keep selected app updated
      if (selectedApp) {
        const updated = filtered.find(a => a.id === selectedApp.id);
        if (updated) setSelectedApp(updated);
      }
    } catch (err: any) {
      setError('Failed to fetch applications');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchApps();
    setSelectedApp(null);
  }, [activeProfile]);

  const handleUpdateStatus = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedApp) return;
    setError('');
    setUpdating(true);

    try {
      await api.applications.updateStatus(selectedApp.id, newStatus, statusNote);
      setStatusNote('');
      await fetchApps();
    } catch (err: any) {
      setError(err.message || 'Status update failed');
    } finally {
      setUpdating(false);
    }
  };

  const statuses = [
    { value: 'draft', label: 'Draft' },
    { value: 'submitted', label: 'Submitted' },
    { value: 'under_process', label: 'Under Process' },
    { value: 'approved', label: 'Approved' },
    { value: 'rejected', label: 'Rejected' }
  ];

  if (!activeProfile) {
    return <div style={{ padding: '2rem', textAlign: 'center' }}>Please select or create a profile.</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: '2.5rem' }}>
        <h1 style={{ fontSize: '2.25rem', marginBottom: '0.5rem' }}>Application Tracker</h1>
        <p style={{ color: 'var(--text-muted)' }}>
          Track the lifecycle and verification steps of your submitted scholarship and government scheme forms.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: selectedApp ? '1.2fr 1.8fr' : '1fr', gap: '2rem' }}>
        
        {/* Left Column: Applications List */}
        <div className="glass-card">
          <h3 style={{ fontSize: '1.25rem', marginBottom: '1.2rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <ClipboardList size={20} style={{ color: 'var(--accent-indigo)' }} /> My Submissions
          </h3>

          {loading ? (
            <div style={{ color: 'var(--text-muted)' }}>Syncing timeline data...</div>
          ) : applications.length === 0 ? (
            <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '3rem' }}>
              No applications filed yet. Go to Forms to pre-fill a template.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {applications.map((app) => {
                const isSelected = selectedApp?.id === app.id;
                return (
                  <div
                    key={app.id}
                    className="list-item-row"
                    onClick={() => setSelectedApp(app)}
                    style={{
                      cursor: 'pointer',
                      borderColor: isSelected ? 'var(--accent-indigo)' : '',
                      background: isSelected ? 'rgba(99, 102, 241, 0.05)' : ''
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600 }}>{app.scheme_name || 'Government Scheme Application'}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', gap: '0.5rem', marginTop: '0.2rem' }}>
                        <span>Ref: {app.reference_number || `APP-${app.id.substring(0,6).toUpperCase()}`}</span>
                        <span>·</span>
                        <span>{new Date(app.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>

                    <span className={`badge ${
                      app.status === 'approved' ? 'badge-success' : 
                      app.status === 'rejected' ? 'badge-danger' : 'badge-warning'
                    }`}>
                      {app.status}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Tracking Details */}
        {selectedApp && (
          <div className="glass-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
              <div>
                <h3 style={{ fontSize: '1.4rem' }}>{selectedApp.scheme_name || 'Application Tracker'}</h3>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Reference Code: {selectedApp.reference_number || `APP-${selectedApp.id.substring(0,6).toUpperCase()}`}</span>
              </div>
              <span className={`badge ${
                selectedApp.status === 'approved' ? 'badge-success' : 
                selectedApp.status === 'rejected' ? 'badge-danger' : 'badge-warning'
              }`} style={{ padding: '0.4rem 0.85rem', fontSize: '0.8rem' }}>
                {selectedApp.status}
              </span>
            </div>

            {/* Visual Tracking Progress Bar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', position: 'relative', marginBottom: '3rem', padding: '0 1rem' }}>
              
              {/* Connecting line */}
              <div style={{
                position: 'absolute', top: '15px', left: '2rem', right: '2rem', height: '2px',
                background: 'rgba(255, 255, 255, 0.06)', zIndex: 1
              }} />

              {/* Steps */}
              {['draft', 'submitted', 'under_process', 'approved'].map((s, idx) => {
                const appStatusIndex = ['draft', 'submitted', 'under_process', 'approved', 'rejected'].indexOf(selectedApp.status);
                const isPassed = appStatusIndex >= idx;
                const isCurrent = selectedApp.status === s || (s === 'approved' && selectedApp.status === 'rejected');
                
                return (
                  <div key={idx} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem', zIndex: 2, position: 'relative' }}>
                    <div style={{
                      width: '32px', height: '32px', borderRadius: '50%',
                      background: isCurrent ? 'var(--accent-indigo)' : isPassed ? 'rgba(99, 102, 241, 0.2)' : 'var(--bg-dark)',
                      border: `2px solid ${isCurrent || isPassed ? 'var(--accent-indigo)' : 'var(--border-color)'}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontWeight: 600, fontSize: '0.85rem', color: isCurrent || isPassed ? 'var(--text-main)' : 'var(--text-dim)',
                      boxShadow: isCurrent ? '0 0 15px rgba(99,102,241,0.4)' : ''
                    }}>
                      {idx + 1}
                    </div>
                    <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'capitalize', color: isCurrent ? 'var(--text-main)' : 'var(--text-dim)' }}>
                      {s.replace('_', ' ')}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Manual Status Overrides (Compliance with Indian government portals without API) */}
            <div className="glass-card" style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', borderRadius: '16px', padding: '1.25rem' }}>
              <h4 style={{ fontSize: '1rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Edit size={16} style={{ color: 'var(--accent-indigo)' }} /> Manual Status Sync
              </h4>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1.25rem', lineHeight: '1.4' }}>
                Because most Indian government portals do not provide API-based status webhooks, you can manually record status changes and verification logs here to maintain central auditing.
              </p>

              {error && (
                <div style={{ color: 'var(--color-danger)', fontSize: '0.8rem', marginBottom: '1rem' }}>{error}</div>
              )}

              <form onSubmit={handleUpdateStatus} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div className="form-group">
                  <label htmlFor="newStatus">New Status</label>
                  <select
                    id="newStatus"
                    className="input-field"
                    value={newStatus}
                    onChange={(e) => setNewStatus(e.target.value)}
                    style={{ background: '#111322' }}
                  >
                    {statuses.map(s => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label htmlFor="statusNote">Verification Log / Note</label>
                  <input
                    id="statusNote"
                    className="input-field"
                    type="text"
                    required
                    placeholder="e.g. Document verification complete. Application forwarded to State nodal officer."
                    value={statusNote}
                    onChange={(e) => setStatusNote(e.target.value)}
                  />
                </div>

                <button className="btn btn-secondary" type="submit" disabled={updating || !statusNote}>
                  {updating ? 'Updating logs...' : 'Log Status Transition'}
                </button>
              </form>
            </div>
          </div>
        )}

      </div>
    </div>
  );
};
