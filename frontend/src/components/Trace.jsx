import { useState } from "react";
import { faviconOf, hideBrokenImage, hostOf } from "../utils";
import { AlertIcon, BookIcon, CheckIcon, ChevronIcon, MemoryIcon, SearchIcon, SparkIcon } from "./Icons";

// The live timeline of what the agent is doing: Think -> Act -> Observe ...
export default function Trace({ steps, status, writing, elapsed, stats }) {
  const toolRunning = steps.some((s) => s.status === "running");
  const deciding = status === "running" && !toolRunning;

  return (
    <div className="card">
      <div className="card-head">
        <h2>Agent trace</h2>
        <span className="timer">{elapsed.toFixed(1)}s</span>
      </div>

      <ol className="timeline">
        {steps.map((item, i) => {
          switch (item.kind) {
            case "memory":
              return (
                <Item key={i} cls="memory" icon={<MemoryIcon />} title="Remembered the chat">
                  <p className="tl-text">
                    Sent {item.turns} earlier {item.turns === 1 ? "turn" : "turns"} along with this question.
                  </p>
                </Item>
              );
            case "thought":
              return <ThoughtItem key={i} item={item} />;
            case "search":
              return <SearchItem key={i} item={item} />;
            case "read":
              return <ReadItem key={i} item={item} />;
            case "retry":
              return (
                <Item key={i} cls="retry" icon={<AlertIcon />} title="Fixed a bad tool call" step={item.step}>
                  <p className="tl-text">{item.text}</p>
                </Item>
              );
            default:
              return <Item key={i} cls="answer" icon={<CheckIcon />} title="Wrote the final answer" />;
          }
        })}

        {deciding && (
          <Item
            cls="pending"
            icon={<span className="pulse" />}
            title={<>{writing ? "Writing the answer" : "Deciding next step"}<span className="dots" /></>}
          />
        )}
        {status === "stopped" && <Item cls="stopped" icon="■" title="Stopped by you" />}
        {status === "error" && <Item cls="retry" icon={<AlertIcon />} title="Failed — see the answer panel" />}
      </ol>

      {stats && (
        <div className="trace-foot">
          <span><b>{stats.steps}</b> {stats.steps === 1 ? "step" : "steps"}</span>
          <span><b>{stats.searches}</b> {stats.searches === 1 ? "search" : "searches"}</span>
          <span><b>{stats.reads}</b> {stats.reads === 1 ? "page read" : "pages read"}</span>
          <span><b>{elapsed.toFixed(1)}</b>s</span>
          {stats.model && <span className="trace-model">{stats.model.split("/").pop()}</span>}
        </div>
      )}
    </div>
  );
}

function Item({ cls, icon, title, step, children }) {
  return (
    <li className={`tl-item ${cls}`}>
      <span className="tl-dot">{icon}</span>
      <div className="tl-body">
        <div className="tl-title">
          {title}
          {step && <span className="tl-step">step {step}</span>}
        </div>
        {children}
      </div>
    </li>
  );
}

function ThoughtItem({ item }) {
  const [open, setOpen] = useState(false);
  return (
    <Item cls="thought" icon={<SparkIcon />} title="Thought" step={item.step}>
      <p className={`tl-text ${open ? "" : "clamp"}`}>{item.text}</p>
      {item.text.length > 150 && (
        <button className="link-btn" onClick={() => setOpen(!open)}>
          {open ? "Show less" : "Show full reasoning"}
        </button>
      )}
    </Item>
  );
}

function SearchItem({ item }) {
  const [open, setOpen] = useState(false);
  const running = item.status === "running";
  const results = item.result?.results || [];

  return (
    <Item
      cls="search"
      icon={running ? <span className="spinner" /> : <SearchIcon />}
      title={running ? "Searching the web" : "Searched the web"}
      step={item.step}
    >
      <div className="query-chip">
        <SearchIcon size={12} />
        <span>{item.args.query}</span>
      </div>
      {/* which search engine actually ran (Tavily falls back to DuckDuckGo) */}
      {item.result?.engine && (
        <span className={`engine-tag ${item.result.engine}`}>
          {item.result.engine === "tavily" ? "Tavily" : "DuckDuckGo"}
        </span>
      )}

      {!running && (
        <>
          <button className="results-toggle" onClick={() => setOpen(!open)} disabled={!results.length} aria-expanded={open}>
            <span className="favicon-stack">
              {results.slice(0, 5).map((r) => (
                <img key={r.id} src={faviconOf(r.url)} alt="" onError={hideBrokenImage} />
              ))}
            </span>
            {results.length ? `${results.length} results` : item.result?.error ? "Search failed" : "No results"}
            {results.length > 0 && <ChevronIcon size={14} className={`chev ${open ? "open" : ""}`} />}
          </button>

          {item.result?.error && <p className="tl-sub warn">{item.result.error}</p>}
          {open && (
            <ul className="mini-results">
              {results.map((r) => (
                <li key={r.id}>
                  <span className="mini-num">{r.id}</span>
                  <a href={r.url} target="_blank" rel="noreferrer" title={r.title}>
                    {r.title}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Item>
  );
}

function ReadItem({ item }) {
  const running = item.status === "running";
  const r = item.result;
  const failed = r && !r.ok;

  return (
    <Item
      cls={failed ? "retry" : "read"}
      icon={running ? <span className="spinner" /> : failed ? <AlertIcon /> : <BookIcon />}
      title={running ? "Reading a page" : failed ? "Couldn't read the page" : "Read a page"}
      step={item.step}
    >
      <a className="page-chip" href={item.args.url} target="_blank" rel="noreferrer" title={item.args.url}>
        <img src={faviconOf(item.args.url)} alt="" onError={hideBrokenImage} />
        <span>{r?.ok ? r.title : hostOf(item.args.url)}</span>
      </a>
      {r?.ok && (
        <p className="tl-sub">
          [{r.id}] · {r.chars.toLocaleString()} characters read
        </p>
      )}
      {failed && <p className="tl-sub warn">{r.error}</p>}
    </Item>
  );
}
