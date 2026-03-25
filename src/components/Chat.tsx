import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Send, Loader2 } from 'lucide-react';
import { streamOllamaChat } from '../services/ollama';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatProps {
  host: string;
  model: string;
}

export default function Chat({ host, model }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || !model || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setError(null);

    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    let assistantMessage = '';
    setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

    try {
      await streamOllamaChat(
        host,
        model,
        [...messages, { role: 'user', content: userMessage }],
        (chunk) => {
          assistantMessage += chunk;
          setMessages(prev => {
            const newMessages = [...prev];
            newMessages[newMessages.length - 1].content = assistantMessage;
            return newMessages;
          });
        }
      );
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message || 'Failed to communicate with Ollama.');
      } else {
        setError('Failed to communicate with Ollama.');
      }
      setMessages(prev => {
        const newMessages = [...prev];
        // If we didn't get any response before failing
        if (!newMessages[newMessages.length - 1].content) {
            newMessages.pop();
        }
        return newMessages;
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex flex-col h-full w-full bg-white relative">
      <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-lg">
            {!model ? 'Please select a model in Settings to start chatting.' : 'Start a conversation...'}
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              <div
                className={`max-w-[85%] md:max-w-[75%] rounded-2xl px-6 py-4 shadow-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white font-medium'
                    : 'bg-gray-100 text-gray-800'
                }`}
              >
                {msg.role === 'user' ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : (
                  <div className="prose prose-slate max-w-none dark:prose-invert">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        {error && (
            <div className="flex justify-center my-4">
                <div className="bg-red-50 text-red-600 px-4 py-3 rounded-lg flex items-center gap-2 max-w-md shadow-sm border border-red-100">
                    <span className="font-semibold text-sm">{error}</span>
                </div>
            </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 bg-white border-t border-gray-100 sticky bottom-0">
        <form
          onSubmit={handleSubmit}
          className="max-w-4xl mx-auto relative flex items-end gap-2 bg-gray-50 p-2 rounded-2xl border border-gray-200 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-transparent transition-shadow"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={!model ? "Select a model in settings..." : "Type your message... (Shift+Enter for new line)"}
            className="flex-1 max-h-48 min-h-[44px] bg-transparent resize-none outline-none py-3 px-4 text-gray-800 placeholder-gray-400"
            rows={input.split('\n').length > 1 ? Math.min(input.split('\n').length, 5) : 1}
            disabled={isLoading || !model}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim() || !model}
            className={`p-3 rounded-xl mb-1 flex-shrink-0 transition-colors ${
              input.trim() && !isLoading && model
                ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-md'
                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
            }`}
          >
            {isLoading ? <Loader2 size={20} className="animate-spin" /> : <Send size={20} />}
          </button>
        </form>
        <div className="text-center mt-2 text-xs text-gray-400">
            Powered by Ollama | Host: {host} | Model: {model || 'None selected'}
        </div>
      </div>
    </div>
  );
}
