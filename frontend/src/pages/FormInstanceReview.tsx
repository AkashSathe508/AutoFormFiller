// src/pages/FormInstanceReview.tsx
import React, { useEffect, useState } from 'react';
import { api, FormInstance, FormFieldValue, FormTemplate, Profile } from '../api';
import { AlertCircle, HelpCircle, Save, CheckCircle2, ChevronRight, ArrowLeft } from 'lucide-react';

interface FormInstanceReviewProps {
  instanceId: string;
  activeProfile: Profile | null;
  onBack: () => void;
  onSubmitSuccess: () => void;
}

export const FormInstanceReview: React.FC<FormInstanceReviewProps> = ({
  instanceId,
  activeProfile,
  onBack,
  onSubmitSuccess,
}) => {
  const [instance, setInstance] = useState<FormInstance | null>(null);
  const [template, setTemplate] = useState<FormTemplate | null>(null);
  const [fields, setFields] = useState<FormFieldValue[]>([]);
  const [fieldSchemas, setFieldSchemas] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingField, setSavingField] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const loadInstanceData = async () => {
    setLoading(true);
    try {
      const inst = await api.forms.getInstance(instanceId);
      setInstance(inst);
      setFields(inst.fields || []);

      const temp = await api.forms.getTemplate(inst.form_template_id);
      setTemplate(temp);
      // The template contains the list of fields schema (like label, type, etc.)
      const dbTemp = temp as any; // Cast for accessing custom fields
      setFieldSchemas(dbTemp.field_schema || []);
    } catch (err: any) {
      setError('Failed to load instance data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInstanceData();
  }, [instanceId]);

  const handleFieldChange = (fieldId: string, val: string) => {
    setFields(prev => prev.map(f => f.form_field_id === fieldId ? { ...f, value: val } : f));
  };

  const handleSaveField = async (fieldId: string, value: string) => {
    setSavingField(fieldId);
    setError('');
    try {
      await api.forms.updateField(instanceId, fieldId, value);
      // Mark field as reviewed and update method to human
      setFields(prev => prev.map(f => f.form_field_id === fieldId ? { ...f, human_reviewed: true, method: 'human', needs_attention: false } : f));
    } catch (err: any) {
      setError(`Failed to save field ${fieldId}: ${err.message}`);
    } finally {
      setSavingField(null);
    }
  };

  const handleSubmit = async () => {
    setError('');
    setSubmitting(true);
    try {
      // Confirm pre-fill & submit application
      await api.applications.updateStatus(instanceId, 'submitted', 'Form pre-fill confirmed and submitted to government gateway.');
      setSuccess('Form successfully filed! Generated mock tracking code.');
      setTimeout(() => {
        onSubmitSuccess();
      }, 2000);
    } catch (err: any) {
      setError(err.message || 'Submission failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (!activeProfile) return <div>Please select a profile.</div>;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <button className="btn btn-secondary" onClick={onBack} style={{ padding: '0.5rem 1rem' }}>
          <ArrowLeft size={16} /> Back
        </button>
        <div>
          <h1 style={{ fontSize: '2rem' }}>Review pre-filled fields</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Review, edit, and confirm auto-filled details for {activeProfile.display_name}.
          </p>
        </div>
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
          padding: '1.25rem',
          borderRadius: '12px',
          marginBottom: '1.5rem',
          fontWeight: 600
        }}>
          {success}
        </div>
      )}

      {loading ? (
        <div style={{ color: 'var(--text-muted)' }}>Retrieving mapped fields...</div>
      ) : fields.length === 0 ? (
        <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '3rem' }}>
          No pre-filled values found. Form might be parsing or empty.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2.5rem' }}>
          
          {/* Mapped Fields List */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {fields.map((field) => {
              const schema = fieldSchemas.find(s => s.field_id === field.form_field_id) || {};
              const label = schema.label || field.form_field_id;
              
              return (
                <div key={field.form_field_id} className="glass-card" style={{
                  padding: '1.25rem 1.5rem',
                  borderLeft: field.needs_attention ? '4px solid var(--color-danger)' : 
                              field.method === 'llm' ? '4px solid var(--accent-purple)' : '1px solid var(--border-color)'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                    <div>
                      <strong style={{ fontSize: '1rem', color: 'var(--text-main)' }}>{label}</strong>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginLeft: '0.5rem', fontFamily: 'monospace' }}>
                        ({field.form_field_id})
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <span className={`badge ${
                        field.method === 'rule' ? 'badge-success' : 
                        field.method === 'embedding' ? 'badge-success' : 
                        field.method === 'llm' ? 'badge-warning' : 'badge-success'
                      }`} style={{ fontSize: '0.7rem' }}>
                        {field.method}
                      </span>
                    </div>
                  </div>

                  {field.needs_attention && (
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      background: 'rgba(239, 68, 68, 0.05)',
                      color: 'var(--color-danger)',
                      padding: '0.5rem 0.75rem',
                      borderRadius: '8px',
                      fontSize: '0.8rem',
                      marginBottom: '0.75rem',
                      border: '1px solid rgba(239, 68, 68, 0.1)'
                    }}>
                      <AlertCircle size={14} />
                      <span>{field.attention_reason || 'Field attention needed'}</span>
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <input
                      className="input-field"
                      type="text"
                      value={field.value || ''}
                      onChange={(e) => handleFieldChange(field.form_field_id, e.target.value)}
                      placeholder={schema.placeholder || 'Enter value...'}
                      style={{ flex: 1, padding: '0.65rem 0.85rem', fontSize: '0.9rem' }}
                    />
                    
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleSaveField(field.form_field_id, field.value || '')}
                      disabled={savingField === field.form_field_id}
                      style={{ padding: '0.65rem 1rem' }}
                      title="Save manual override"
                    >
                      <Save size={16} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Submission Panel */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            <div className="glass-card" style={{ position: 'sticky', top: '2rem' }}>
              <h3 style={{ fontSize: '1.25rem', marginBottom: '1rem' }}>Review Summary</h3>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Total Form Fields:</span>
                  <strong style={{ color: 'var(--text-main)' }}>{fields.length}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Mapped via DB Rules:</span>
                  <strong style={{ color: 'var(--text-main)' }}>{fields.filter(f => f.method === 'rule').length}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Mapped via pgvector:</span>
                  <strong style={{ color: 'var(--text-main)' }}>{fields.filter(f => f.method === 'embedding').length}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>LLM / High Uncertainty:</span>
                  <strong style={{ color: 'var(--accent-purple)' }}>{fields.filter(f => f.method === 'llm').length}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Missing (Needs Review):</span>
                  <strong style={{ color: 'var(--color-danger)' }}>{fields.filter(f => f.needs_attention).length}</strong>
                </div>
              </div>

              <div style={{
                background: 'rgba(255,255,255,0.01)',
                border: '1px solid var(--border-color)',
                borderRadius: '12px',
                padding: '1rem',
                fontSize: '0.8rem',
                color: 'var(--text-muted)',
                marginBottom: '1.5rem',
                lineHeight: '1.4'
              }}>
                Please ensure all highlighted values are correct. Correct entries will be merged back to update your profile.
              </div>

              <button
                className="btn btn-primary"
                onClick={handleSubmit}
                disabled={submitting || fields.some(f => f.needs_attention)}
                style={{ width: '100%' }}
              >
                Confirm pre-fill & Submit
              </button>
            </div>
          </div>

        </div>
      )}
    </div>
  );
};
