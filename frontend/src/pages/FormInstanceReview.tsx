// src/pages/FormInstanceReview.tsx
import React, { useEffect, useState, useRef } from 'react';
import { api, FormInstance, FormFieldValue, FormTemplate, Profile } from '../api';
import { AlertCircle, Save, CheckCircle2, ArrowLeft, Globe, Loader2, Play, ShieldAlert, Bot } from 'lucide-react';
import { AiAssistantPanel } from '../features/forms/components/AiAssistantPanel';

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
  const [adapters, setAdapters] = useState<any[]>([]);
  const [selectedAdapter, setSelectedAdapter] = useState('');
  
  const [loading, setLoading] = useState(true);
  const [savingField, setSavingField] = useState<string | null>(null);
  
  const [showAiAssistant, setShowAiAssistant] = useState(false);
  
  // Submission State
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);
  const [isApproved, setIsApproved] = useState(false);
  
  const [submitUsername, setSubmitUsername] = useState('');
  const [submitPassword, setSubmitPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string>('');
  const [runError, setRunError] = useState<string | null>(null);
  const [runRef, setRunRef] = useState<string | null>(null);
  const [captchaNote, setCaptchaNote] = useState('');
  
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  const loadInstanceData = async () => {
    setLoading(true);
    try {
      const inst = await api.forms.getInstance(instanceId);
      setInstance(inst);
      setFields(inst.fields || []);
      setIsApproved(inst.status === 'approved' || inst.status === 'submitting' || inst.status === 'submitted');

      const temp = await api.forms.getTemplate(inst.form_template_id);
      setTemplate(temp);
      const dbTemp = temp as any;
      setFieldSchemas(dbTemp.field_schema || []);
      
      const adapterList = await api.submissions.listAdapters();
      setAdapters(adapterList.adapters);
      if (adapterList.adapters.length > 0) {
        setSelectedAdapter(adapterList.adapters[0].adapter_id);
      }
      
      // Check if there is an active run
      if (inst.status === 'submitting' || inst.status === 'submitted') {
        const dbInst = inst as any;
        if (dbInst.submission_run_id) {
          setRunId(dbInst.submission_run_id);
          pollRun(dbInst.submission_run_id);
        }
      }
      
    } catch (err: any) {
      setError('Failed to load instance data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInstanceData();
    return () => {
      if (pollingRef.current) clearTimeout(pollingRef.current);
    };
  }, [instanceId]);

  const pollRun = async (currentRunId: string) => {
    try {
      const runData = await api.submissions.getRun(currentRunId);
      setRunStatus(runData.status);
      
      if (runData.status === 'failed') {
        setRunError(runData.error_detail);
        setIsSubmitting(false);
      } else if (runData.status === 'completed') {
        setRunRef(runData.portal_reference);
        setSuccess('Application successfully submitted! Ref: ' + runData.portal_reference);
        setIsSubmitting(false);
      } else if (runData.status === 'awaiting_user') {
        // Paused for CAPTCHA
      } else {
        // Continue polling
        pollingRef.current = setTimeout(() => pollRun(currentRunId), 3000);
      }
    } catch (err: any) {
      console.error("Polling error", err);
    }
  };

  const handleFieldChange = (fieldId: string, val: string) => {
    setFields(prev => prev.map(f => f.form_field_id === fieldId ? { ...f, value: val } : f));
  };

  const handleSaveField = async (fieldId: string, value: string) => {
    setSavingField(fieldId);
    setError('');
    try {
      await api.forms.updateField(instanceId, fieldId, value);
      setFields(prev => prev.map(f => f.form_field_id === fieldId ? { ...f, human_reviewed: true, method: 'human', needs_attention: false } : f));
    } catch (err: any) {
      setError(`Failed to save field ${fieldId}: ${err.message}`);
    } finally {
      setSavingField(null);
    }
  };

  const handleApprove = async () => {
    setError('');
    setApprovalSubmitting(true);
    try {
      await api.submissions.approve(instanceId, "Approved via UI");
      setIsApproved(true);
      setSuccess("Form approved. You can now initiate the automated submission.");
    } catch (err: any) {
      setError(err.message || 'Approval failed');
    } finally {
      setApprovalSubmitting(false);
    }
  };

  const handleLaunchSubmission = async () => {
    if (!submitUsername || !submitPassword) {
      setError('Please provide portal credentials');
      return;
    }
    setError('');
    setIsSubmitting(true);
    setRunError(null);
    try {
      const res = await api.submissions.submit(instanceId, selectedAdapter, {
        username: submitUsername,
        password: submitPassword
      });
      setRunId(res.run_id);
      setRunStatus(res.status);
      pollRun(res.run_id);
    } catch (err: any) {
      setError(err.message || 'Failed to start submission engine');
      setIsSubmitting(false);
    }
  };

  const handleResolveCaptcha = async () => {
    if (!runId) return;
    try {
      await api.submissions.resolveCaptcha(runId, captchaNote);
      setRunStatus('resume_signalled');
      setCaptchaNote('');
      pollRun(runId);
    } catch (err: any) {
      setError(err.message || 'Failed to signal CAPTCHA resolution');
    }
  };

  if (!activeProfile) return <div>Please select a profile.</div>;

  const needsAttentionCount = fields.filter(f => f.needs_attention && !f.human_reviewed).length;
  const unreviewedCount = fields.filter(f => !f.human_reviewed).length;
  
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <button className="btn btn-secondary" onClick={onBack} style={{ padding: '0.5rem 1rem' }}>
          <ArrowLeft size={16} /> Back
        </button>
        <div>
          <h1 style={{ fontSize: '2rem' }}>Review & Submit</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Verify auto-filled details and automate submission for {activeProfile.display_name}.
          </p>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <button className="btn btn-secondary" onClick={() => setShowAiAssistant(true)} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem' }}>
            <Bot size={16} /> Ask AI Assistant
          </button>
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

      {success && !runRef && (
        <div style={{
          background: 'rgba(16, 185, 129, 0.1)',
          border: '1px solid rgba(16, 185, 129, 0.2)',
          color: 'var(--color-success)',
          padding: '1rem',
          borderRadius: '12px',
          marginBottom: '1.5rem',
          fontWeight: 600
        }}>
          {success}
        </div>
      )}

      {loading ? (
        <div style={{ color: 'var(--text-muted)' }}>Retrieving mapped fields...</div>
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
                  borderLeft: field.needs_attention && !field.human_reviewed ? '4px solid var(--color-danger)' : 
                              !field.human_reviewed ? '4px solid var(--accent-blue)' : '1px solid var(--color-success)',
                  opacity: isApproved ? 0.7 : 1,
                  pointerEvents: isApproved ? 'none' : 'auto'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                    <div>
                      <strong style={{ fontSize: '1rem', color: 'var(--text-main)' }}>{label}</strong>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginLeft: '0.5rem', fontFamily: 'monospace' }}>
                        ({field.form_field_id})
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      {field.human_reviewed && <CheckCircle2 size={16} color="var(--color-success)" />}
                      <span className={`badge ${
                        field.method === 'rule' ? 'badge-success' : 
                        field.method === 'embedding' ? 'badge-success' : 
                        field.method === 'llm' ? 'badge-warning' : 'badge-success'
                      }`} style={{ fontSize: '0.7rem' }}>
                        {field.method}
                      </span>
                    </div>
                  </div>

                  {field.needs_attention && !field.human_reviewed && (
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
                      disabled={savingField === field.form_field_id || (field.human_reviewed && !field.needs_attention)}
                      style={{ padding: '0.65rem 1rem' }}
                      title="Save manual override / Mark Reviewed"
                    >
                      <Save size={16} /> {field.human_reviewed ? 'Reviewed' : 'Confirm'}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Submission Panel */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            <div className="glass-card" style={{ position: 'sticky', top: '2rem' }}>
              
              {!isApproved ? (
                <>
                  <h3 style={{ fontSize: '1.25rem', marginBottom: '1rem' }}>Review Gate</h3>
                  <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1.5rem', lineHeight: '1.5' }}>
                    Before automated submission can proceed, all fields must be verified by a human to ensure accuracy.
                  </div>
                  
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Total Fields:</span>
                      <strong style={{ color: 'var(--text-main)' }}>{fields.length}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Awaiting Review:</span>
                      <strong style={{ color: unreviewedCount > 0 ? 'var(--accent-blue)' : 'var(--color-success)' }}>{unreviewedCount}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Needs Attention:</span>
                      <strong style={{ color: needsAttentionCount > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>{needsAttentionCount}</strong>
                    </div>
                  </div>

                  <button
                    className="btn btn-primary"
                    onClick={handleApprove}
                    disabled={approvalSubmitting || needsAttentionCount > 0 || unreviewedCount > 0}
                    style={{ width: '100%' }}
                  >
                    {approvalSubmitting ? <Loader2 className="animate-spin" size={18} /> : <CheckCircle2 size={18} />} 
                    Approve Application
                  </button>
                  
                  {(needsAttentionCount > 0 || unreviewedCount > 0) && (
                    <div style={{ marginTop: '1rem', fontSize: '0.75rem', color: 'var(--color-danger)', textAlign: 'center' }}>
                      Please confirm all fields before approving.
                    </div>
                  )}
                </>
              ) : (
                <>
                  <h3 style={{ fontSize: '1.25rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Globe size={20} color="var(--accent-blue)" /> Portal Submission
                  </h3>

                  {runRef ? (
                    <div style={{ textAlign: 'center', padding: '1rem 0' }}>
                      <CheckCircle2 size={48} color="var(--color-success)" style={{ margin: '0 auto 1rem' }} />
                      <h4 style={{ color: 'var(--color-success)', marginBottom: '0.5rem' }}>Submission Complete</h4>
                      <div style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--text-main)', letterSpacing: '1px' }}>
                        {runRef}
                      </div>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '1rem' }}>
                        Your application has been filed successfully. Keep this reference number for your records.
                      </p>
                      <button className="btn btn-secondary" onClick={onSubmitSuccess} style={{ width: '100%', marginTop: '1.5rem' }}>
                        Return to Dashboard
                      </button>
                    </div>
                  ) : runStatus === 'awaiting_user' ? (
                    <div style={{
                      background: 'rgba(234, 179, 8, 0.1)',
                      border: '1px solid rgba(234, 179, 8, 0.2)',
                      padding: '1rem',
                      borderRadius: '8px'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--color-warning)', fontWeight: 600, marginBottom: '0.5rem' }}>
                        <ShieldAlert size={18} /> CAPTCHA Detected
                      </div>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                        The submission engine has encountered a CAPTCHA. Please solve the CAPTCHA in the live browser window and confirm here to resume.
                      </p>
                      <input 
                        className="input-field"
                        placeholder="Resolution Note (Optional)" 
                        value={captchaNote}
                        onChange={e => setCaptchaNote(e.target.value)}
                        style={{ width: '100%', marginBottom: '1rem', padding: '0.5rem', fontSize: '0.85rem' }}
                      />
                      <button className="btn btn-primary" onClick={handleResolveCaptcha} style={{ width: '100%' }}>
                        I Have Solved the CAPTCHA
                      </button>
                    </div>
                  ) : isSubmitting || runStatus === 'running' || runStatus === 'resume_signalled' ? (
                    <div style={{ textAlign: 'center', padding: '2rem 0' }}>
                      <Loader2 className="animate-spin" size={32} color="var(--accent-blue)" style={{ margin: '0 auto 1rem' }} />
                      <h4 style={{ marginBottom: '0.5rem' }}>Engine is Running...</h4>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                        Status: <strong style={{ color: 'var(--text-main)' }}>{runStatus.toUpperCase()}</strong>
                      </p>
                      <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '1rem' }}>
                        Do not close this window. The engine is navigating the portal.
                      </p>
                    </div>
                  ) : (
                    <div>
                      {runError && (
                         <div style={{ color: 'var(--color-danger)', fontSize: '0.85rem', marginBottom: '1rem', padding: '0.5rem', background: 'rgba(239,68,68,0.1)', borderRadius: '6px' }}>
                           Error: {runError}
                         </div>
                      )}
                      <div className="form-group" style={{ marginBottom: '1rem' }}>
                        <label style={{ fontSize: '0.85rem' }}>Select Target Portal</label>
                        <select 
                          className="input-field" 
                          value={selectedAdapter} 
                          onChange={e => setSelectedAdapter(e.target.value)}
                          style={{ width: '100%', padding: '0.5rem' }}
                        >
                          {adapters.map(a => (
                            <option key={a.adapter_id} value={a.adapter_id}>{a.display_name}</option>
                          ))}
                        </select>
                      </div>
                      
                      <div className="form-group" style={{ marginBottom: '1rem' }}>
                        <label style={{ fontSize: '0.85rem' }}>Portal Username</label>
                        <input 
                          type="text" 
                          className="input-field" 
                          value={submitUsername} 
                          onChange={e => setSubmitUsername(e.target.value)}
                          style={{ width: '100%', padding: '0.5rem' }}
                          placeholder="User ID / Email"
                        />
                      </div>
                      
                      <div className="form-group" style={{ marginBottom: '1.5rem' }}>
                        <label style={{ fontSize: '0.85rem' }}>Portal Password</label>
                        <input 
                          type="password" 
                          className="input-field" 
                          value={submitPassword} 
                          onChange={e => setSubmitPassword(e.target.value)}
                          style={{ width: '100%', padding: '0.5rem' }}
                          placeholder="Password"
                        />
                      </div>
                      
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '1rem', lineHeight: '1.4' }}>
                        Credentials are held securely in memory only during the active browser session. They are never stored in the database.
                      </div>
                      
                      <button 
                        className="btn btn-primary" 
                        onClick={handleLaunchSubmission} 
                        style={{ width: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem' }}
                      >
                        <Play size={16} fill="currentColor" /> Launch Submission Engine
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

        </div>
      )}

      {showAiAssistant && (
        <AiAssistantPanel 
          onClose={() => setShowAiAssistant(false)} 
          formTemplateId={instance?.form_template_id} 
        />
      )}
    </div>
  );
};
