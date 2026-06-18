// src/pages/Forms.tsx
import React, { useEffect, useState } from 'react';
import { api, Profile, FormTemplate } from '../api';
import { FilePlus, Layers, Search, Play, ClipboardCheck, ArrowRight, Loader } from 'lucide-react';

interface FormsProps {
  activeProfile: Profile | null;
  onSelectInstance: (instanceId: string) => void;
}

export const Forms: React.FC<FormsProps> = ({ activeProfile, onSelectInstance }) => {
  const [templates, setTemplates] = useState<FormTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchUrl, setSearchUrl] = useState('');
  const [schemeName, setSchemeName] = useState('');
  const [parsing, setParsing] = useState(false);
  const [filling, setFilling] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const res = await api.forms.list();
      setTemplates(res || []);
    } catch (err: any) {
      setError('Failed to fetch templates');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  const handleParse = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchUrl) return;
    setError('');
    setSuccess('');
    setParsing(true);

    try {
      const res = await api.forms.parse(searchUrl, schemeName || 'Custom Form');
      setSuccess(`Ingestion task triggered! Form ID: ${res.id}. Playwright is rendering in the background.`);
      setSearchUrl('');
      setSchemeName('');
      
      // Auto-refresh list
      setTimeout(() => {
        fetchTemplates();
      }, 3000);
    } catch (err: any) {
      setError(err.message || 'Scrape failed');
    } finally {
      setParsing(false);
    }
  };

  const handlePrefill = async (templateId: string) => {
    if (!activeProfile) {
      setError('Please select an active profile first');
      return;
    }
    setError('');
    setFilling(templateId);

    try {
      const res = await api.forms.createInstance(templateId, activeProfile.profile_id);
      // Prefill task runs asynchronously. Wait 2 seconds, then redirect to review screen.
      setSuccess('Mapping profile fields using pgvector embeddings and local LLM...');
      setTimeout(() => {
        onSelectInstance(res.id);
      }, 2000);
    } catch (err: any) {
      setError(err.message || 'Pre-fill task failed');
      setFilling(null);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: '2.5rem' }}>
        <h1 style={{ fontSize: '2.25rem', marginBottom: '0.5rem' }}>Form Portal</h1>
        <p style={{ color: 'var(--text-muted)' }}>
          Ingest government scholarship, entrance exam, or admissions forms, then pre-fill them instantly.
        </p>
      </div>

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

      {success && (
        <div style={{
          background: 'rgba(16, 185, 129, 0.1)',
          border: '1px solid rgba(16, 185, 129, 0.2)',
          color: 'var(--color-success)',
          padding: '1rem',
          borderRadius: '12px',
          marginBottom: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem'
        }}>
          <Loader size={16} className="animate-spin" />
          <span>{success}</span>
        </div>
      )}

      {/* Parse box */}
      <div className="glass-card" style={{ marginBottom: '2.5rem' }}>
        <h3 style={{ fontSize: '1.25rem', marginBottom: '1.2rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <FilePlus size={20} style={{ color: 'var(--accent-indigo)' }} /> Scrape New Form URL
        </h3>
        
        <form onSubmit={handleParse} style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr auto', gap: '1rem', alignItems: 'end' }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="url">Portal Form URL</label>
            <input
              id="url"
              className="input-field"
              type="url"
              required
              placeholder="https://scholarships.gov.in/application-form"
              value={searchUrl}
              onChange={(e) => setSearchUrl(e.target.value)}
            />
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="scheme">Scheme Name / Label</label>
            <input
              id="scheme"
              className="input-field"
              type="text"
              placeholder="e.g. Post-Matric Scholarship 2026"
              value={schemeName}
              onChange={(e) => setSchemeName(e.target.value)}
            />
          </div>

          <button className="btn btn-primary" type="submit" disabled={parsing || !searchUrl}>
            {parsing ? 'Parsing DOM...' : 'Scrape Schema'}
          </button>
        </form>
      </div>

      {/* Available templates */}
      <h3 style={{ fontSize: '1.25rem', marginBottom: '1.25rem' }}>Available Form Templates</h3>
      
      {loading ? (
        <div style={{ color: 'var(--text-muted)' }}>Querying templates list...</div>
      ) : templates.length === 0 ? (
        <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '4rem', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', borderRadius: '16px' }}>
          No form templates parsed yet. Use the Scrape tool above to ingest a form.
        </div>
      ) : (
        <div className="grid-2">
          {templates.map((temp) => (
            <div key={temp.id} className="glass-card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                  <div style={{
                    padding: '0.6rem',
                    background: 'var(--accent-indigo-glow)',
                    border: '1px solid rgba(99, 102, 241, 0.2)',
                    borderRadius: '10px',
                    color: 'var(--accent-indigo)'
                  }}>
                    <Layers size={18} />
                  </div>
                  <span className="badge badge-success">
                    {temp.field_count > 0 ? `${temp.field_count} Fields` : 'Parsing...'}
                  </span>
                </div>
                
                <h4 style={{ fontSize: '1.15rem', marginBottom: '0.5rem' }}>
                  {temp.scheme_name || 'Generic Web Form'}
                </h4>
                <p style={{
                  color: 'var(--text-muted)',
                  fontSize: '0.8rem',
                  wordBreak: 'break-all',
                  marginBottom: '1.5rem',
                  lineHeight: '1.4'
                }}>
                  {temp.source_url_or_hash}
                </p>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-color)', paddingTop: '1rem', marginTop: '1rem' }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                  Scraped: {new Date(temp.parsed_at).toLocaleDateString()}
                </span>
                
                <button
                  className="btn btn-secondary"
                  onClick={() => handlePrefill(temp.id)}
                  disabled={filling !== null}
                  style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}
                >
                  {filling === temp.id ? 'Mapping...' : 'Auto-fill Form'}
                  <ArrowRight size={14} style={{ marginLeft: '0.25rem' }} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
