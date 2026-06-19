// src/api.ts

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export interface Profile {
  profile_id: string;
  display_name: string;
  relation_to_account: string;
}

export interface ProfileField {
  field_key: string;
  value: string;
  confidence: number;
  source_document_id: string | null;
  user_confirmed: boolean;
  updated_at: string | null;
}

export interface Document {
  id: string;
  profile_id: string;
  doc_type: string;
  mime_type: string;
  size_bytes: number;
  version: number;
  is_current: boolean;
  uploaded_at: string;
  expires_hint_at: string | null;
  original_filename?: string;
  verification_status?: string; // 'ok' | 'review' | 'suspicious'
}

export interface FormTemplate {
  id: string;
  source_type: string;
  source_url_or_hash: string;
  scheme_name: string | null;
  field_count: number;
  parsed_at: string;
}

export interface FormFieldValue {
  form_field_id: string;
  value: string | null;
  method: string;
  human_reviewed: boolean;
  needs_attention: boolean;
  attention_reason: string | null;
}

export interface FormInstance {
  id: string;
  form_template_id: string;
  profile_id: string;
  status: string; // 'draft' | 'filling' | 'ready' | 'needs_review' | 'submitted'
  created_at: string;
  submitted_at: string | null;
  reference_number: string | null;
  fields?: FormFieldValue[];
}

export interface Application {
  id: string;
  form_template_id: string;
  profile_id: string;
  status: string;
  created_at: string;
  submitted_at: string | null;
  reference_number: string | null;
  scheme_name?: string;
  profile_name?: string;
}

// Token Storage Helpers
export const getAccessToken = () => localStorage.getItem('access_token');
export const setAccessToken = (token: string) => localStorage.setItem('access_token', token);
export const getRefreshToken = () => localStorage.getItem('refresh_token');
export const setRefreshToken = (token: string) => localStorage.setItem('refresh_token', token);
export const clearTokens = () => {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
};

// Base Fetch Wrapper
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getAccessToken();
  const headers = new Headers(options.headers || {});
  
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  
  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401 && getRefreshToken()) {
    // Attempt Token Refresh
    try {
      const refreshRes = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: getRefreshToken() }),
      });
      if (refreshRes.ok) {
        const refreshData = await refreshRes.json();
        setAccessToken(refreshData.access_token);
        setRefreshToken(refreshData.refresh_token);
        
        // Retry original request
        headers.set('Authorization', `Bearer ${refreshData.access_token}`);
        const retryRes = await fetch(`${API_BASE_URL}${path}`, {
          ...options,
          headers,
        });
        if (!retryRes.ok) throw new Error('Retry failed after refresh');
        return await retryRes.json();
      }
    } catch (err) {
      clearTokens();
      window.location.href = '/auth';
      throw new Error('Session expired');
    }
  }

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Request failed with status ${res.status}`);
  }

  return await res.json() as T;
}

export const api = {
  // Authentication
  auth: {
    register: (body: any) => request<{ user_id: string; profile_id: string; message: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
    login: (body: any) => request<{ access_token: string; refresh_token: string; expires_in: number }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
    verifyOtp: (body: { user_id: string; otp: string; purpose?: string }) => request<{ message: string }>('/auth/verify-otp', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
    logout: () => {
      const rt = getRefreshToken();
      clearTokens();
      if (rt) {
        return request('/auth/logout', {
          method: 'POST',
          body: JSON.stringify({ refresh_token: rt }),
        }).catch(() => {});
      }
      return Promise.resolve();
    }
  },

  // Profiles
  profiles: {
    list: () => request<{ profiles: Profile[] }>('/profiles'),
    create: (display_name: string, relation_to_account: string = 'self') => request<Profile>('/profiles', {
      method: 'POST',
      body: JSON.stringify({ display_name, relation_to_account }),
    }),
    getFields: (profile_id: string, reveal: boolean = false) => request<{ profile_id: string; fields: ProfileField[] }>(`/profiles/${profile_id}/fields?reveal=${reveal}`),
    delete: (profile_id: string) => request<{ message: string; profile_id: string }>(`/profiles/${profile_id}`, {
      method: 'DELETE',
    }),
    export: (profile_id: string) => request<any>(`/profiles/${profile_id}/export`),
  },

  // Documents
  documents: {
    list: (profile_id: string) => request<{ documents: Document[] }>(`/documents?profile_id=${profile_id}`),
    upload: (profile_id: string, doc_type: string, file: File) => {
      const formData = new FormData();
      formData.append('profile_id', profile_id);
      formData.append('doc_type', doc_type);
      formData.append('file', file);
      return request<{ document_id: string; message: string }>('/documents', {
        method: 'POST',
        body: formData,
      });
    },
    getStatus: (document_id: string) => request<{ id: string; doc_type: string; status: string; verification_status: string; structured_fields: any }>(`/documents/${document_id}/status`),
  },

  // Forms
  forms: {
    list: (scheme_name?: string) => request<FormTemplate[]>(`/forms${scheme_name ? `?scheme_name=${encodeURIComponent(scheme_name)}` : ''}`),
    parse: (url: string, scheme_name?: string) => request<FormTemplate>('/forms/parse', {
      method: 'POST',
      body: JSON.stringify({ url, scheme_name }),
    }),
    getTemplate: (template_id: string) => request<FormTemplate>(`/forms/${template_id}`),
    createInstance: (form_template_id: string, profile_id: string) => request<FormInstance>('/forms/instances', {
      method: 'POST',
      body: JSON.stringify({ form_template_id, profile_id }),
    }),
    getInstance: (instance_id: string) => request<FormInstance>(`/forms/instances/${instance_id}`),
    updateField: (instance_id: string, form_field_id: string, value: string) => request<{ message: string; form_field_id: string }>(`/forms/instances/${instance_id}/fields`, {
      method: 'PATCH',
      body: JSON.stringify({ form_field_id, value }),
    }),
  },

  // Applications / Tracking
  applications: {
    list: () => request<{ applications: Application[] }>('/applications'),
    updateStatus: (instance_id: string, status: string, note?: string) => request<any>(`/applications/${instance_id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, note }),
    }),
  },

  // Submissions (Phase 3)
  submissions: {
    listAdapters: () => request<{ adapters: { adapter_id: string; display_name: string; portal_url: string }[] }>('/submissions/adapters'),
    approve: (instance_id: string, acknowledgement?: string) => request<{ status: string }>(`/submissions/instances/${instance_id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ acknowledgement: acknowledgement || null }),
    }),
    submit: (instance_id: string, adapter_id: string, credentials: Record<string, string>, form_url: string = '') => request<{ run_id: string; status: string }>(`/submissions/instances/${instance_id}/submit`, {
      method: 'POST',
      body: JSON.stringify({ adapter_id, credentials, form_url }),
    }),
    getRun: (run_id: string) => request<{ run_id: string; status: string; portal_reference: string | null; error_detail: string | null; screenshot_count: number }>(`/submissions/runs/${run_id}`),
    resolveCaptcha: (run_id: string, note?: string) => request<{ status: string }>(`/submissions/runs/${run_id}/resolve-captcha`, {
      method: 'POST',
      body: JSON.stringify({ note: note || null }),
    }),
    getAudit: (run_id: string) => request<any>(`/submissions/runs/${run_id}/audit`),
  },

  // RAG Assistant (Phase 4)
  rag: {
    ask: (question: string, scheme_id?: string, form_template_id?: string) => request<{ answer: string; sources: any[] }>('/rag/ask', {
      method: 'POST',
      body: JSON.stringify({ question, scheme_id, form_template_id }),
    }),
  }
};
