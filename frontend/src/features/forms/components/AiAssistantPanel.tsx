import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, X, Loader2 } from 'lucide-react';
import { api } from '../../../api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  sources?: any[];
}

interface AiAssistantPanelProps {
  onClose: () => void;
  formTemplateId?: string;
}

export const AiAssistantPanel: React.FC<AiAssistantPanelProps> = ({ onClose, formTemplateId }) => {
  const [messages, setMessages] = useState<Message[]>([{
    role: 'assistant',
    content: 'Hi! I am your local AI assistant. I can help you understand this form, definitions of terms, and requirements. What would you like to know?'
  }]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const response = await api.rag.ask(userMessage, undefined, formTemplateId);
      setMessages(prev => [...prev, { role: 'assistant', content: response.answer, sources: response.sources }]);
    } catch (err: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: 'var(--bg-card)', borderLeft: '1px solid var(--border-color)',
      width: '350px', position: 'fixed', right: 0, top: 0, bottom: 0, zIndex: 1000,
      boxShadow: '-4px 0 15px rgba(0,0,0,0.1)'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '1rem', background: 'var(--accent-blue)', color: 'white'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600 }}>
          <Bot size={20} /> AI Assistant
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'white', cursor: 'pointer' }}>
          <X size={20} />
        </button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {messages.map((msg, idx) => (
          <div key={idx} style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%' }}>
            <div style={{
              padding: '0.75rem 1rem', borderRadius: '12px', fontSize: '0.9rem',
              background: msg.role === 'user' ? 'var(--accent-blue)' : 'var(--bg-main)',
              color: msg.role === 'user' ? 'white' : 'var(--text-main)',
              border: msg.role === 'assistant' ? '1px solid var(--border-color)' : 'none',
              borderBottomRightRadius: msg.role === 'user' ? '4px' : '12px',
              borderBottomLeftRadius: msg.role === 'assistant' ? '4px' : '12px',
            }}>
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{msg.content}</div>
              {msg.sources && msg.sources.length > 0 && (
                <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid rgba(0,0,0,0.1)', fontSize: '0.8rem' }}>
                  <div style={{ color: 'var(--text-dim)', marginBottom: '0.25rem' }}>Sources:</div>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem', color: 'var(--accent-blue)' }}>
                    {msg.sources.map((s, i) => (
                      <li key={i}>
                        <a href={s.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                          {s.source_url || 'Internal Document'}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div style={{ alignSelf: 'flex-start', maxWidth: '85%' }}>
            <div style={{ padding: '0.75rem 1rem', borderRadius: '12px', background: 'var(--bg-main)', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-dim)', fontSize: '0.9rem' }}>
              <Loader2 size={16} className="animate-spin" /> Thinking...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '1rem', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '0.5rem', background: 'var(--bg-card)' }}>
        <textarea
          className="input-field"
          style={{ flex: 1, resize: 'none', padding: '0.75rem', fontSize: '0.9rem', minHeight: '44px', maxHeight: '120px' }}
          placeholder="Ask a question..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyPress}
          disabled={isLoading}
          rows={1}
        />
        <button
          className="btn btn-primary"
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          style={{ padding: '0.75rem', height: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  );
};
