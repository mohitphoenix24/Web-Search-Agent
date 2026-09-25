import { ChatIcon, PlusIcon, TrashIcon } from "./Icons";

// The list of saved chats (from the SQLite database, via the backend).
export default function Sidebar({ chats, activeId, open, disabled, onClose, onNew, onOpen, onDelete }) {
  return (
    <>
      <div className={`backdrop ${open ? "show" : ""}`} onClick={onClose} />
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Saved chats">
        <button className="new-chat-btn" onClick={onNew}>
          <PlusIcon size={16} /> New chat
        </button>

        <div className="sidebar-label">Saved chats</div>
        {chats.length === 0 ? (
          <p className="sidebar-empty">Your chats will appear here once the agent answers.</p>
        ) : (
          <ul className="chat-list">
            {chats.map((c) => (
              <li key={c.id} className={c.id === activeId ? "active" : ""}>
                <button className="chat-link" onClick={() => onOpen(c.id)} disabled={disabled} title={c.title}>
                  <ChatIcon size={15} className="chat-icon" />
                  <span className="chat-text">
                    <span className="chat-title">{c.title}</span>
                    <span className="chat-meta">
                      {c.turn_count} {c.turn_count === 1 ? "question" : "questions"} · {timeAgo(c.updated_at)}
                    </span>
                  </span>
                </button>
                <button className="chat-delete" onClick={() => onDelete(c.id)} disabled={disabled} aria-label="Delete chat">
                  <TrashIcon size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </>
  );
}

function timeAgo(unixSeconds) {
  const s = Date.now() / 1000 - unixSeconds;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
