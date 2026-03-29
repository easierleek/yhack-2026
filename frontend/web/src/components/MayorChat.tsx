import { useState, useRef, useEffect } from 'react';
import type { NeoState } from '../types/NeoState';
import '../styles/MayorChat.css';

export interface MayorChatProps {
  state: NeoState;
  onDirective: (directive: string) => void;
}

export interface ChatMessage {
  role: 'mayor' | 'neo';
  text: string;
  timestamp: number;
}

export function MayorChat({ state, onDirective }: MayorChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'neo',
      text: 'NEO: Ready to receive mayor directives. Describe how you want me to allocate power.',
      timestamp: Date.now(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  async function handleSendDirective() {
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');

    // Add user message to chat
    setMessages((prev) => [
      ...prev,
      {
        role: 'mayor',
        text: userMessage,
        timestamp: Date.now(),
      },
    ]);

    setIsLoading(true);

    try {
      // Send directive to backend API
      // Try localhost:5000 first, fall back to relative path
      const apiUrl = typeof window !== 'undefined'
        ? `http://${window.location.hostname}:5000/api/mayor-directive`
        : 'http://localhost:5000/api/mayor-directive';

      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          directive: userMessage,
          current_state: state,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `API error: ${response.status}`);
      }

      const data = await response.json();

      // Add K2 response to chat
      setMessages((prev) => [
        ...prev,
        {
          role: 'neo',
          text: data.response,
          timestamp: Date.now(),
        },
      ]);

      // Notify parent to update power allocation
      onDirective(userMessage);
    } catch (err) {
      console.error('Mayor directive error:', err);
      setMessages((prev) => [
        ...prev,
        {
          role: 'neo',
          text: `ERROR: ${err instanceof Error ? err.message : 'Failed to process directive'}. Check that mayor_api.py is running on port 5000.`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendDirective();
    }
  }

  return (
    <div className="mayor-chat">
      <div className="mayor-chat-messages" ref={scrollRef}>
        {messages.map((msg, idx) => (
          <div key={idx} className={`mayor-chat-message ${msg.role}`}>
            <span className="chat-role">{msg.role === 'mayor' ? '[MAYOR]' : '[NEO]'}</span>
            <span className="chat-text">{msg.text}</span>
          </div>
        ))}
        {isLoading && (
          <div className="mayor-chat-message neo loading">
            <span className="chat-role">[NEO]</span>
            <span className="chat-text">Processing directive...</span>
          </div>
        )}
      </div>

      <div className="mayor-chat-input-area">
        <textarea
          ref={inputRef}
          className="mayor-chat-textarea"
          placeholder="Enter a power allocation directive (e.g., 'Heat emergency - prioritize residential AC')..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          rows={1}
        />
        <button
          className="mayor-chat-send"
          onClick={handleSendDirective}
          disabled={!input.trim() || isLoading}
          title="Send directive (Shift+Enter)"
        >
          {isLoading ? '...' : '→'}
        </button>
      </div>
    </div>
  );
}
