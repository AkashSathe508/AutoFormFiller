// src/pages/Vault.tsx
import React, { useEffect, useState } from 'react';
import { api, Profile, Document } from '../api';
import { Upload, File, FileText, CheckCircle2, AlertTriangle, XCircle, Info, Lock } from 'lucide-react';

interface VaultProps {
  activeProfile: Profile | null;
}

export const Vault: React.FC<VaultProps> = ({ activeProfile }) => {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [selectedDocDetails, setSelectedDocDetails] = useState<any>(null);
  const [uploadType, setUploadType] = useState('AADHAAR');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const docTypes = [
    { value: 'AADHAAR', label: 'Aadhaar Card' },
    { value: 'PAN', label: 'PAN Card' },
    { value: 'PASSPORT', label: 'Passport' },
    { value: 'DRIVING_LICENSE', label: 'Driving License' },
    { value: 'MARKSHEET_10', label: '10th Marksheet' },
    { value: 'MARKSHEET_12', label: '12th Marksheet' },
    { value: 'DEGREE_CERTIFICATE', label: 'Degree Certificate' },
    { value: 'CASTE_CERTIFICATE', label: 'Caste Certificate' },
    { value: 'INCOME_CERTIFICATE', label: 'Income Certificate' },
    { value: 'UTILITY_BILL', label: 'Utility Bill' },
    { value: 'MEDICAL_DOCUMENT', label: 'Medical Document' },
    { value: 'GOVERNMENT_ID_OTHER', label: 'Other Gov ID' }
  ];

  const fetchDocs = async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const res = await api.documents.list(activeProfile.profile_id);
      setDocuments(res.documents || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocs();
    setSelectedDoc(null);
    setSelectedDocDetails(null);
  }, [activeProfile]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeProfile || !file) {
      setError('Please select a file to upload');
      return;
    }
    setError('');
    setSuccess('');
    setUploading(true);

    try {
      const res = await api.documents.upload(activeProfile.profile_id, uploadType, file);
      setSuccess(res.message || 'File uploaded successfully! Processing started.');
      setFile(null);
      
      // Auto-refresh doc list
      setTimeout(() => {
        fetchDocs();
      }, 1500);
    } catch (err: any) {
      setError(err.message || 'Failed to upload document');
    } finally {
      setUploading(false);
    }
  };

  const handleSelectDoc = async (doc: Document) => {
    setSelectedDoc(doc);
    setSelectedDocDetails(null);
    try {
      const res = await api.documents.getStatus(doc.id);
      setSelectedDocDetails(res);
    } catch (err) {
      console.error('Failed to load doc extractions:', err);
    }
  };

  if (!activeProfile) {
    return <div style={{ padding: '2rem', textAlign: 'center' }}>Please select or create a profile.</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '2.25rem', marginBottom: '0.5rem' }}>Document Vault</h1>
        
        {/* RLS Banner */}
        <div style={{
          background: 'rgba(99, 102, 241, 0.05)',
          border: '1px solid rgba(99, 102, 241, 0.15)',
          padding: '0.85rem 1.25rem',
          borderRadius: '14px',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          color: '#a5b4fc',
          marginBottom: '1.5rem'
        }}>
          <Lock size={16} />
          <span>
            <strong>Row-Level Security Active:</strong> You are viewing isolated vault data belonging strictly to <strong>{activeProfile.display_name}</strong>. Cross-profile reads are blocked at the DB layer.
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: selectedDoc ? '1.2fr 1.8fr' : '1.5fr 1.5fr', gap: '2rem' }}>
        
        {/* Left Column: Form & Doc List */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          
          {/* Upload Card */}
          <div className="glass-card">
            <h3 style={{ fontSize: '1.25rem', marginBottom: '1.2rem' }}>Upload Identity / Certificate</h3>
            
            {error && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                color: 'var(--color-danger)',
                padding: '0.75rem 1rem',
                borderRadius: '12px',
                fontSize: '0.85rem',
                marginBottom: '1rem'
              }}>
                {error}
              </div>
            )}

            {success && (
              <div style={{
                background: 'rgba(16, 185, 129, 0.1)',
                border: '1px solid rgba(16, 185, 129, 0.2)',
                color: 'var(--color-success)',
                padding: '0.75rem 1rem',
                borderRadius: '12px',
                fontSize: '0.85rem',
                marginBottom: '1rem'
              }}>
                {success}
              </div>
            )}

            <form onSubmit={handleUpload} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="form-group">
                <label htmlFor="docType">Document Type</label>
                <select
                  id="docType"
                  className="input-field"
                  value={uploadType}
                  onChange={(e) => setUploadType(e.target.value)}
                  style={{ background: '#111322' }}
                >
                  {docTypes.map(t => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>File Input</label>
                <label className="upload-dropzone">
                  <Upload size={32} style={{ color: 'var(--accent-indigo)' }} />
                  <div>
                    {file ? (
                      <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{file.name}</span>
                    ) : (
                      <span>Drag and drop your document, or <strong style={{ color: 'var(--accent-indigo)' }}>browse</strong></span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                    Supports PDF, PNG, JPEG up to 15MB
                  </div>
                  <input
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg"
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        setFile(e.target.files[0]);
                      }
                    }}
                    style={{ display: 'none' }}
                  />
                </label>
              </div>

              <button className="btn btn-primary" type="submit" disabled={uploading || !file}>
                {uploading ? 'Processing File...' : 'Start Extraction Pipeline'}
              </button>
            </form>
          </div>

          {/* List Card */}
          <div className="glass-card">
            <h3 style={{ fontSize: '1.25rem', marginBottom: '1.2rem' }}>Stored Vault Files</h3>
            
            {loading ? (
              <div style={{ color: 'var(--text-muted)' }}>Loading documents...</div>
            ) : documents.length === 0 ? (
              <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '3rem' }}>
                No documents found for this profile.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {documents.map((doc) => {
                  const isSelected = selectedDoc?.id === doc.id;
                  return (
                    <div 
                      key={doc.id} 
                      className="list-item-row"
                      onClick={() => handleSelectDoc(doc)}
                      style={{
                        cursor: 'pointer',
                        borderColor: isSelected ? 'var(--accent-indigo)' : '',
                        background: isSelected ? 'rgba(99, 102, 241, 0.05)' : ''
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <FileText size={20} style={{ color: 'var(--accent-indigo)' }} />
                        <div>
                          <div style={{ fontWeight: 600 }}>{doc.doc_type}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            Version {doc.version} · {(doc.size_bytes / 1024).toFixed(1)} KB
                          </div>
                        </div>
                      </div>
                      
                      <span className={`badge ${
                        doc.verification_status === 'suspicious' ? 'badge-danger' : 
                        doc.verification_status === 'review' ? 'badge-warning' : 'badge-success'
                      }`}>
                        {doc.verification_status || 'Verified'}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Doc Extraction Details View */}
        {selectedDoc && (
          <div className="glass-card" style={{ height: 'fit-content' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
              <div>
                <h3 style={{ fontSize: '1.4rem' }}>{selectedDoc.doc_type} Analysis</h3>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>ID: {selectedDoc.id}</span>
              </div>
              <span className="badge badge-success">Current Version</span>
            </div>

            {selectedDocDetails ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                
                {/* Verification Check Results */}
                <div>
                  <h4 style={{ fontSize: '1.05rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
                    Authenticity Check
                  </h4>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '1rem',
                    padding: '1rem',
                    borderRadius: '12px',
                    background: selectedDocDetails.verification_status === 'suspicious' ? 'rgba(239, 68, 68, 0.06)' : 'rgba(16, 185, 129, 0.06)',
                    border: `1px solid ${selectedDocDetails.verification_status === 'suspicious' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)'}`
                  }}>
                    {selectedDocDetails.verification_status === 'suspicious' ? (
                      <XCircle size={28} style={{ color: 'var(--color-danger)' }} />
                    ) : selectedDocDetails.verification_status === 'review' ? (
                      <AlertTriangle size={28} style={{ color: 'var(--color-warning)' }} />
                    ) : (
                      <CheckCircle2 size={28} style={{ color: 'var(--color-success)' }} />
                    )}
                    <div>
                      <div style={{ fontWeight: 700 }}>
                        {selectedDocDetails.verification_status === 'suspicious' ? 'Mismatched Checksums / Edited' : 'Verified OK'}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {selectedDocDetails.verification_status === 'suspicious' 
                          ? 'This document failed format/structure checks. Verify details manually.' 
                          : 'Deterministic format validations (e.g. Verhoeff, PAN regex) succeeded.'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Structured Fields */}
                <div>
                  <h4 style={{ fontSize: '1.05rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
                    Extracted Values
                  </h4>
                  
                  {Object.keys(selectedDocDetails.structured_fields || {}).length === 0 ? (
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-dim)', padding: '1rem', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', borderRadius: '12px' }}>
                      No structured fields extracted from this document type.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      {Object.entries(selectedDocDetails.structured_fields).map(([key, field]: [string, any]) => {
                        const val = typeof field === 'object' && field !== null ? field.value : field;
                        const conf = typeof field === 'object' && field !== null ? field.confidence : 1.0;
                        return (
                          <div key={key} style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '0.85rem 1rem',
                            borderRadius: '12px',
                            background: 'rgba(255, 255, 255, 0.01)',
                            border: '1px solid var(--border-color)'
                          }}>
                            <div>
                              <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', textTransform: 'uppercase', display: 'block' }}>
                                {key.replace('_', ' ')}
                              </span>
                              <strong style={{ fontSize: '0.95rem', color: 'var(--text-main)' }}>{String(val)}</strong>
                            </div>
                            {conf !== undefined && (
                              <span style={{
                                fontSize: '0.75rem',
                                color: conf > 0.8 ? 'var(--color-success)' : 'var(--color-warning)',
                                background: conf > 0.8 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
                                border: `1px solid ${conf > 0.8 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)'}`,
                                padding: '0.2rem 0.5rem',
                                borderRadius: '8px',
                                fontWeight: 600
                              }}>
                                {(conf * 100).toFixed(0)}% Conf
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Technical metadata */}
                <div style={{
                  background: 'rgba(255,255,255,0.01)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '12px',
                  padding: '1rem',
                  fontSize: '0.8rem',
                  color: 'var(--text-muted)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.35rem'
                }}>
                  <div><strong>MIME-Type:</strong> {selectedDoc.mime_type}</div>
                  <div><strong>OCR Engine:</strong> {selectedDocDetails.model_used || 'paddleocr'}</div>
                </div>

              </div>
            ) : (
              <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '4rem' }}>
                Analyzing fields & scanning barcodes...
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
};
