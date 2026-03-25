import { useState, useEffect, useCallback } from 'react';

interface SettingsProps {
  host: string;
  setHost: (host: string) => void;
  model: string;
  setModel: (model: string) => void;
}

export default function Settings({ host, setHost, model, setModel }: SettingsProps) {
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchModels = useCallback(async (currentHost: string) => {
    setLoading(true);
    setError(null);
    try {
      const url = currentHost.endsWith('/') ? `${currentHost}api/tags` : `${currentHost}/api/tags`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`Failed to fetch models: ${response.statusText}`);
      }

      const data = await response.json();
      if (data && data.models) {
        const modelNames = data.models.map((m: { name: string }) => m.name);
        setModels(modelNames);

        // If current model is not in the list, set it to the first available model
        if (!model && modelNames.length > 0) {
          setModel(modelNames[0]);
        } else if (model && !modelNames.includes(model) && modelNames.length > 0) {
          setModel(modelNames[0]);
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message || 'Could not connect to Ollama host.');
      } else {
        setError('Could not connect to Ollama host.');
      }
      setModels([]);
    } finally {
      setLoading(false);
    }
  }, [model, setModel]);

  useEffect(() => {
    fetchModels(host);
  }, [host, fetchModels]);

  return (
    <div className="flex-1 p-8 bg-gray-50 flex justify-center">
      <div className="max-w-2xl w-full bg-white shadow-sm border border-gray-200 rounded-2xl p-8">
        <h2 className="text-2xl font-semibold mb-6 text-gray-800">Settings</h2>

        <div className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Ollama Host URL</label>
            <input
              type="text"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-shadow"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="http://localhost:11434"
            />
            <p className="mt-2 text-sm text-gray-500">
              The URL where your Ollama instance is running. Make sure CORS is configured to allow requests from this frontend.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Select Model</label>
            {loading ? (
              <div className="text-sm text-gray-500 flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                Loading models...
              </div>
            ) : error ? (
              <div className="text-sm text-red-500 p-3 bg-red-50 rounded-lg border border-red-100">
                {error}
                <br />
                <button
                  onClick={() => fetchModels(host)}
                  className="mt-2 text-red-600 font-medium hover:underline"
                >
                  Retry Connection
                </button>
              </div>
            ) : models.length === 0 ? (
              <div className="text-sm text-yellow-600 p-3 bg-yellow-50 rounded-lg border border-yellow-100">
                No models found on this host. Pull a model using `ollama run model_name` first.
              </div>
            ) : (
              <select
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-white transition-shadow"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
