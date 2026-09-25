// Talking to the Python backend (server.py).

async function getJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

export const getInfo = () => getJson("/api/info");

// Saved chats (Phase 5) — stored in SQLite by the backend
export const listChats = () => getJson("/api/chats");
export const getChat = (id) => getJson(`/api/chats/${id}`);
export const deleteChat = (id) => getJson(`/api/chats/${id}`, { method: "DELETE" });

// The backend streams NDJSON: one JSON event per line, sent the moment the
// agent does something (even each word of the answer, as "token" events).
// We read the response bit by bit and call onEvent() for every complete line.
// chatId = which saved chat this question belongs to (null = new chat).
// The server loads that chat's earlier turns as the agent's memory.
// model = which LLM should answer (an id from /api/info).
export async function askAgent(question, chatId, model, onEvent, signal) {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, chat_id: chatId, model }),
    signal,
  });
  if (!res.ok) {
    throw new Error(
      res.status >= 500
        ? "Can't reach the agent backend. Is it running? (uvicorn server:app --port 8000)"
        : `Request failed (${res.status})`
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop(); // the last piece may be an incomplete line — keep it
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line));
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}
