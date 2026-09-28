import { useEffect, useRef, useState } from "react";
import { askAgent, deleteChat, getChat, getInfo, listChats } from "./api";
import ModelPicker from "./components/ModelPicker";
import Sidebar from "./components/Sidebar";
import ThemeToggle from "./components/ThemeToggle";
import Turn from "./components/Turn";
import { ArrowIcon, BookIcon, Logo, MemoryIcon, MenuIcon, SearchIcon, SparkIcon, StopIcon } from "./components/Icons";

const EXAMPLES = [
  { text: "Who won the latest Formula 1 race?", hint: "then ask: who came second?" },
  { text: "Read https://docs.python.org/3/whatsnew/3.14.html and list the 3 biggest features", hint: "read_page" },
  { text: "What is 17 × 23?", hint: "no tools" },
  { text: "What's new in AI agents this month?", hint: "search + read" },
];

// Every event from the backend updates one turn (one question + its answer).
// Saved chats are rebuilt by replaying their saved events through this same function.
function applyEvent(turn, event) {
  const steps = turn.steps;
  switch (event.type) {
    case "token":
      // STREAMING: the answer grows piece by piece while the model writes it
      return { ...turn, draft: turn.draft + event.text };
    case "memory":
      return event.turns > 0 ? { ...turn, steps: [...steps, { kind: "memory", turns: event.turns }] } : turn;
    case "thought":
      // text streamed before a tool call was a thought, not the answer
      return { ...turn, draft: "", steps: [...steps, { kind: "thought", step: event.step, text: event.text }] };
    case "retry":
      return { ...turn, draft: "", steps: [...steps, { kind: "retry", step: event.step, text: event.message }] };
    case "tool_call": {
      const kind = event.tool === "read_page" ? "read" : "search";
      return { ...turn, draft: "", steps: [...steps, { kind, step: event.step, args: event.args, status: "running" }] };
    }
    case "tool_result": {
      // Fill in the result on the matching "running" step
      const kind = event.tool === "read_page" ? "read" : "search";
      const i = steps.findLastIndex((s) => s.kind === kind && s.status === "running");
      if (i === -1) return turn;
      const next = [...steps];
      next[i] = { ...steps[i], status: "done", result: event };
      return { ...turn, steps: next };
    }
    case "answer":
      return {
        ...turn,
        draft: "",
        answer: { text: event.text, sources: event.sources },
        steps: [...steps, { kind: "answer" }],
      };
    case "done":
      return { ...turn, stats: event };
    default:
      return turn;
  }
}

let nextId = 1;
const newTurn = (question) => ({
  id: nextId++,
  question,
  status: "running", // running | done | stopped | error
  steps: [],
  draft: "", // the answer while it's still being streamed
  answer: null,
  stats: null,
  error: "",
  startedAt: performance.now(),
  endedAt: null,
});

// Rebuild a saved turn from its events (the same events we got live)
function replayTurn(saved) {
  const start = { ...newTurn(saved.question), startedAt: 0, endedAt: saved.seconds * 1000 };
  return { ...saved.events.reduce(applyEvent, start), status: "done" };
}

// The open chat is kept in the URL (#chat-12), so a page refresh reopens it
const chatIdFromUrl = () => Number(location.hash.match(/^#chat-(\d+)$/)?.[1]) || null;
const setUrlChat = (id) => history.replaceState(null, "", id ? `#chat-${id}` : location.pathname);

// Remember the chosen model in this browser (storage can be blocked, so be careful)
const MODEL_KEY = "wsa-model";
const savedModel = () => {
  try {
    return localStorage.getItem(MODEL_KEY);
  } catch {
    return null;
  }
};
const saveModel = (id) => {
  try {
    localStorage.setItem(MODEL_KEY, id);
  } catch {
    /* not important */
  }
};

export default function App() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState([]);
  const [chatId, setChatId] = useState(null);
  const [chats, setChats] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const [info, setInfo] = useState(null);
  const [model, setModel] = useState(null);
  const [now, setNow] = useState(performance.now());
  const controller = useRef(null);
  const inputRef = useRef(null);

  const running = turns.some((t) => t.status === "running");

  const refreshChats = () => listChats().then(setChats).catch(() => {});

  useEffect(() => {
    getInfo()
      .then((i) => {
        setInfo(i);
        // Use the saved model if it can still be used, else the first usable one
        const usable = i.models.filter((m) => m.available);
        const saved = usable.find((m) => m.id === savedModel());
        setModel((saved ?? usable.find((m) => m.id === i.default_model) ?? usable[0] ?? i.models[0])?.id);
      })
      .catch(() => setInfo({ offline: true }));
    refreshChats();
    const id = chatIdFromUrl();
    if (id) openChat(id);
  }, []);

  // Tick a clock while the agent runs, for the live timer
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(timer);
  }, [running]);

  // Scroll to the newest question when it's asked
  useEffect(() => {
    if (!running) return;
    document.getElementById(`turn-${turns.at(-1)?.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [turns.length]);

  function updateTurn(id, fn) {
    setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));
  }

  async function openChat(id) {
    if (running) return;
    setSidebarOpen(false);
    try {
      const chat = await getChat(id);
      setTurns(chat.turns.map(replayTurn));
      setChatId(chat.id);
      setUrlChat(chat.id);
      window.scrollTo({ top: 0 });
    } catch {
      setUrlChat(null); // chat was deleted
    }
  }

  function newChat(e) {
    e?.preventDefault();
    controller.current?.abort();
    setTurns([]);
    setChatId(null);
    setUrlChat(null);
    setInput("");
    setSidebarOpen(false);
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  async function removeChat(id) {
    if (!confirm("Delete this chat?")) return;
    await deleteChat(id);
    if (id === chatId) newChat();
    refreshChats();
  }

  async function ask(q) {
    q = q.trim();
    if (!q || running) return;

    const turn = newTurn(q);
    setTurns((ts) => [...ts, turn]);
    setInput("");

    controller.current = new AbortController();
    let finished = false;
    try {
      await askAgent(
        q,
        chatId, // MEMORY: the server loads this chat's earlier turns
        model, // which LLM answers
        (event) => {
          if (event.type === "error") throw new Error(event.message);
          if (event.type === "done") finished = true;
          if (event.type === "saved") {
            // The server saved this turn (and created the chat if it was new)
            setChatId(event.chat_id);
            setUrlChat(event.chat_id);
            refreshChats();
            return;
          }
          updateTurn(turn.id, (t) => applyEvent(t, event));
        },
        controller.current.signal
      );
      if (!finished) throw new Error("The agent stopped unexpectedly.");
      updateTurn(turn.id, (t) => ({ ...t, status: "done", endedAt: performance.now() }));
    } catch (e) {
      const stopped = e.name === "AbortError";
      if (!stopped) controller.current.abort(); // stop reading the stream
      updateTurn(turn.id, (t) => ({
        ...t,
        status: stopped ? "stopped" : "error",
        error: stopped ? "" : e.message || "Something went wrong.",
        endedAt: performance.now(),
      }));
    }
    inputRef.current?.focus();
  }

  const idle = turns.length === 0;
  const composer = (
    <form
      className="askbar"
      onSubmit={(e) => {
        e.preventDefault();
        ask(input);
      }}
    >
      <SearchIcon size={18} className="askbar-icon" />
      <input
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder={idle ? "Ask a question…" : "Ask a follow-up…"}
        aria-label="Ask a question"
        autoFocus
      />
      {running ? (
        <button type="button" className="ask-btn stop" onClick={() => controller.current?.abort()}>
          <StopIcon size={14} /> Stop
        </button>
      ) : (
        <button type="submit" className="ask-btn" disabled={!input.trim()}>
          Ask <ArrowIcon size={16} />
        </button>
      )}
    </form>
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open chats">
            <MenuIcon size={18} />
          </button>
          <a className="brand" href="/" onClick={newChat}>
            <Logo />
            <span className="brand-name">Web Search Agent</span>
          </a>
          <span className="phase-badge">Phase 6 · Pick your model</span>
          <div className="spacer" />
          <ThemeToggle />
          {info?.offline ? (
            <span className="model-pill" title="Start the backend on port 8000">
              <span className="status-dot off" /> Backend offline
            </span>
          ) : (
            info && (
              <ModelPicker
                models={info.models}
                value={model}
                onChange={(id) => {
                  setModel(id);
                  saveModel(id);
                }}
              />
            )
          )}
        </div>
      </header>

      <div className="shell">
        <Sidebar
          chats={chats}
          activeId={chatId}
          open={sidebarOpen}
          disabled={running}
          onClose={() => setSidebarOpen(false)}
          onNew={newChat}
          onOpen={openChat}
          onDelete={removeChat}
        />

        <main className={`main ${idle ? "is-idle" : ""}`}>
          {idle ? (
            <div className="idle-wrap">
              <div className="hero">
                <h1>
                  Ask anything.
                  <br />
                  <span className="grad">Pick the brain behind it.</span>
                </h1>
                <p>
                  Choose a fast <em>online</em> model or a private <em>local</em> one from the menu at the top. The
                  agent searches, reads pages, and streams the answer — and every chat is saved.
                </p>
              </div>
              {composer}
              <div className="examples">
                {EXAMPLES.map((ex) => (
                  <button key={ex.text} className="example" onClick={() => ask(ex.text)}>
                    {ex.text.length > 60 ? ex.text.slice(0, 58) + "…" : ex.text} <small>· {ex.hint}</small>
                  </button>
                ))}
              </div>
              <HowItWorks info={info} />
            </div>
          ) : (
            <>
              <div className="thread">
                {turns.map((t, i) => (
                  <Turn key={t.id} turn={t} index={i} now={now} />
                ))}
              </div>
              <div className="composer-dock">{composer}</div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function HowItWorks({ info }) {
  const cards = [
    {
      cls: "think",
      icon: <SparkIcon />,
      title: "Any model",
      text: "Online models on Groq, or Qwen3 on your own GPU. Same agent, same tools.",
    },
    {
      cls: "memory",
      icon: <MemoryIcon />,
      title: "Memory",
      text: `Chats are saved in SQLite. The last ${info?.memory_turns ?? 5} turns go with each question.`,
    },
    {
      cls: "read",
      icon: <BookIcon />,
      title: "Search + read",
      text: "web_search finds pages; read_page opens one and reads it when snippets aren't enough.",
    },
  ];
  return (
    <div className="how">
      {cards.map((c) => (
        <div key={c.title} className={`how-card ${c.cls}`}>
          <div className="how-icon">{c.icon}</div>
          <h3>{c.title}</h3>
          <p>{c.text}</p>
        </div>
      ))}
    </div>
  );
}
