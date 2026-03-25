import { useState, useEffect } from 'react';
import Chat from './components/Chat';
import Settings from './components/Settings';
import { Settings as SettingsIcon, MessageSquare } from 'lucide-react';

export default function App() {
  const [showSettings, setShowSettings] = useState(false);
  const [host, setHost] = useState(localStorage.getItem('ollama_host') || 'http://localhost:11434');
  const [model, setModel] = useState(localStorage.getItem('ollama_model') || '');

  useEffect(() => {
    localStorage.setItem('ollama_host', host);
  }, [host]);

  useEffect(() => {
    localStorage.setItem('ollama_model', model);
  }, [model]);

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-gray-900 text-white flex flex-col border-r border-gray-800 flex-shrink-0 transition-all duration-300">
        <div className="p-4 font-bold text-xl border-b border-gray-800 flex items-center gap-2">
          <MessageSquare size={24} />
          <span>Ollama Chat</span>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <button
            onClick={() => setShowSettings(false)}
            className={`w-full text-left px-3 py-2 rounded-lg mb-2 flex items-center gap-2 transition-colors ${!showSettings ? 'bg-gray-800' : 'hover:bg-gray-800/50'}`}
          >
            <MessageSquare size={18} />
            Chat
          </button>
        </div>

        <div className="p-4 border-t border-gray-800">
          <button
            onClick={() => setShowSettings(true)}
            className={`w-full text-left px-3 py-2 rounded-lg flex items-center gap-2 transition-colors ${showSettings ? 'bg-gray-800' : 'hover:bg-gray-800/50'}`}
          >
            <SettingsIcon size={18} />
            Settings
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 bg-white shadow-sm">
        {showSettings ? (
          <Settings
            host={host}
            setHost={setHost}
            model={model}
            setModel={setModel}
          />
        ) : (
          <Chat host={host} model={model} />
        )}
      </main>
    </div>
  );
}
