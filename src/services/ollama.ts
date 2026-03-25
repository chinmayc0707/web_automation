export interface ChatMessage {
    role: 'user' | 'assistant' | 'system';
    content: string;
}

export async function streamOllamaChat(
    host: string,
    model: string,
    messages: ChatMessage[],
    onChunk: (chunk: string) => void
): Promise<void> {
    const url = host.endsWith('/') ? `${host}api/chat` : `${host}/api/chat`;

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                model,
                messages,
                stream: true,
            }),
        });

        if (!response.ok) {
            throw new Error(`Failed to generate response: ${response.statusText}`);
        }

        if (!response.body) {
            throw new Error('ReadableStream not supported by the browser.');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');

        let isDone = false;

        while (!isDone) {
            const { done, value } = await reader.read();
            if (done) {
                isDone = true;
                break;
            }

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n').filter((line) => line.trim() !== '');

            for (const line of lines) {
                try {
                    const parsed = JSON.parse(line);
                    if (parsed.message?.content) {
                        onChunk(parsed.message.content);
                    }
                    if (parsed.done) {
                        isDone = true;
                    }
                } catch (e) {
                    console.error('Error parsing Ollama stream chunk:', e, line);
                }
            }
        }
    } catch (error) {
        console.error('Error streaming from Ollama:', error);
        throw error;
    }
}
