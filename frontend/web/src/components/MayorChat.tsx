import { useEffect, useRef, useState } from 'react';
import type { NeoState } from '../types/NeoState';
import '../styles/MayorChat.css';

interface MayorChatProps {
  state: NeoState;
  onDirective: (directive: string) => void;
}

interface ChatMessage {
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

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  async function handleSendDirective() {
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
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
      const response = await fetch('/api/mayor-directive', {
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

      setMessages((prev) => [
        ...prev,
        {
          role: 'neo',
          text: data.response,
          timestamp: Date.now(),
        },
      ]);

      onDirective(userMessage);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'neo',
          text: `ERROR: ${error instanceof Error ? error.message : 'Failed to process directive'}. Check that the mayor directive API is running on port 5000.`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSendDirective();
    }
  }

  return (
    <div className="mayor-chat">
      <div className="mayor-chat-messages" ref={scrollRef}>
        {messages.map((message) => (
          <div key={`${message.timestamp}-${message.role}`} className={`mayor-chat-message ${message.role}`}>
            <span className="chat-role">{message.role === 'mayor' ? '[MAYOR]' : '[NEO]'}</span>
            <span className="chat-text">{message.text}</span>
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
          className="mayor-chat-textarea"
          placeholder="Enter a power directive..."
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          rows={1}
        />
        <button
          className="mayor-chat-send"
          type="button"
          onClick={() => void handleSendDirective()}
          disabled={!input.trim() || isLoading}
          title="Send directive"
        >
          {isLoading ? '...' : '->'}
        </button>
      </div>
    </div>
  );
}
