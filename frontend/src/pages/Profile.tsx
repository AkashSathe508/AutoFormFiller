// src/pages/Profile.tsx
import React, { useEffect, useState } from 'react';
import { api, Profile as UserProfile, ProfileField } from '../api';
import { Shield, Eye, EyeOff, CheckCircle2, Download, Trash2, HelpCircle, Lock, AlertTriangle } from 'lucide-react';

interface ProfileProps {
  activeProfile: UserProfile | null;
  onProfileDeleted: () => void;
}

export const Profile: React.FC<ProfileProps> = ({ activeProfile, onProfileDeleted }) => {
  const [fields, setFields] = useState<ProfileField[]>([]);
  const [loading, setLoading] = useState(true);
  const [reveal, setReveal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [erasurePassword, setErasurePassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const fetchFields = async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const res = await api.profiles.getFields(activeProfile.profile_id, reveal);
      setFields(res.fields || []);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFields();
  }, [activeProfile, reveal]);

  const handleExport = async () => {
    if (!activeProfile) return;
    try {
      const data = await api.profiles.export(activeProfile.profile_id);
      const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(
        JSON.stringify(data, null, 2)
      )}`;
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', jsonString);
      downloadAnchor.setAttribute('download', `autoformfiller_profile_${activeProfile.display_name.toLowerCase()}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    } catch (err: any) {
      setError('Export failed: ' + err.message);
    }
  };

  const handleErasure = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeProfile) return;
    setError('');
    
    try {
      const res = await api.profiles.delete(activeProfile.profile_id);
      setSuccess(res.message);
      setShowDeleteModal(false);
      
      // Notify parent app that profile was deleted
      setTimeout(() => {
        onProfileDeleted();
      }, 2500);
    } catch (err: any) {
      setError(err.message || 'Erasure request failed');
    }
  };

  if (!activeProfile) {
    return <div style={{ padding: '2rem', textAlign: 'center' }}>Please select or create a profile.</div>;
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2.5rem' }}>
        <div>
          <h1 style={{ fontSize: '2.25rem', marginBottom: '0.5rem' }}>Unified Profile</h1>
          <p style={{ color: 'var(--text-muted)' }}>
            Your canonical extracted facts. These fields are automatically mapped to government forms.
          </p>
        </div>
        
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button className="btn btn-secondary" onClick={() => setReveal(!reveal)}>
            {reveal ? <EyeOff size={16} /> : <Eye size={16} />}
            {reveal ? 'Hide Sensitive Data' : 'Reveal Fields'}
          </button>
          
          <button className="btn btn-secondary" onClick={handleExport}>
            <Download size={16} />
            Data Portability Export
          </button>
        </div>
      </div>

      {success && (
        <div style={{
          background: 'rgba(16, 185, 129, 0.1)',
          border: '1px solid rgba(16, 185, 129, 0.2)',
          color: 'var(--color-success)',
          padding: '1rem',
          borderRadius: '12px',
          marginBottom: '1.5rem'
        }}>
          {success}
        </div>
      )}

      {error && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.2)',
          color: 'var(--color-danger)',
          padding: '1rem',
          borderRadius: '12px',
          marginBottom: '1.5rem'
        }}>
          {error}
        </div>
      )}

      {/* Profile Fields Table */}
      <div className="glass-card" style={{ padding: '1.5rem', marginBottom: '2.5rem' }}>
        {loading ? (
          <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>Syncing profile parameters...</div>
        ) : fields.length === 0 ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-dim)' }}>
            No profile fields extracted yet. Upload identity documents in the vault to populate your profile.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  <th style={{ padding: '1rem' }}>Fact Parameter</th>
                  <th style={{ padding: '1rem' }}>Value</th>
                  <th style={{ padding: '1rem' }}>Confidence</th>
                  <th style={{ padding: '1rem' }}>Source Provenance</th>
                  <th style={{ padding: '1rem' }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.field_key} style={{ borderBottom: '1px solid var(--border-color)', fontSize: '0.95rem' }}>
                    <td style={{ padding: '1.25rem 1rem', fontWeight: 600, color: 'var(--accent-indigo)' }}>
                      {f.field_key.replace(/_/g, ' ').toUpperCase()}
                    </td>
                    <td style={{ padding: '1.25rem 1rem', fontFamily: 'monospace', fontSize: '1rem' }}>
                      {f.value}
                    </td>
                    <td style={{ padding: '1.25rem 1rem' }}>
                      <span style={{
                        fontSize: '0.75rem',
                        color: f.confidence > 0.85 ? 'var(--color-success)' : 'var(--color-warning)',
                        background: f.confidence > 0.85 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
                        padding: '0.2rem 0.5rem',
                        borderRadius: '6px',
                        fontWeight: 600
                      }}>
                        {(f.confidence * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td style={{ padding: '1.25rem 1rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                      {f.source_document_id ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                          <Shield size={12} style={{ color: 'var(--accent-indigo)' }} />
                          Verified Doc Ref
                        </span>
                      ) : (
                        'Manual entry'
                      )}
                    </td>
                    <td style={{ padding: '1.25rem 1rem' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--color-success)', fontSize: '0.85rem', fontWeight: 600 }}>
                        <CheckCircle2 size={14} /> Confirmed
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* DPDP Compliance Alert area */}
      <div className="glass-card" style={{ borderColor: 'rgba(239, 68, 68, 0.15)', background: 'rgba(239, 68, 68, 0.02)' }}>
        <h3 style={{ color: 'var(--color-danger)', fontSize: '1.25rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <AlertTriangle size={20} /> Danger Zone (DPDP Right to Erasure)
        </h3>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '1.5rem', lineHeight: '1.5' }}>
          Under Section 12 of the Digital Personal Data Protection (DPDP) Act 2023, you have the right to request erasure of your personal data. 
          Clicking "Erasure Request" initiates cryptographic erasure: your profile's Data Encryption Key (DEK) is permanently destroyed, 
          rendering all encrypted documents and field records in our database instantly and irreversibly unreadable.
        </p>
        <button className="btn btn-danger" onClick={() => setShowDeleteModal(true)}>
          <Trash2 size={16} /> Request Cryptographic Erasure
        </button>
      </div>

      {/* Delete/Erasure Modal */}
      {showDeleteModal && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000, padding: '1rem'
        }}>
          <div className="glass-card" style={{ maxWidth: '500px', width: '100%', borderColor: 'var(--color-danger)' }}>
            <h3 style={{ fontSize: '1.4rem', color: 'var(--color-danger)', marginBottom: '1rem' }}>Confirm Cryptographic Erasure</h3>
            <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '1.5rem', lineHeight: '1.5' }}>
              WARNING: This action is absolute. Destroying the DEK makes all vault files permanently unreadable. 
              Neither you nor system administrators can recover this data.
            </p>
            <form onSubmit={handleErasure} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div className="form-group">
                <label htmlFor="confirmText">To confirm, type your active profile display name (<strong>{activeProfile.display_name}</strong>):</label>
                <input
                  id="confirmText"
                  className="input-field"
                  type="text"
                  required
                  placeholder={activeProfile.display_name}
                  value={erasurePassword}
                  onChange={(e) => setErasurePassword(e.target.value)}
                />
              </div>
              <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                <button className="btn btn-secondary" type="button" onClick={() => setShowDeleteModal(false)}>
                  Cancel
                </button>
                <button
                  className="btn btn-danger"
                  type="submit"
                  disabled={erasurePassword !== activeProfile.display_name}
                >
                  Permanently Purge Data
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
