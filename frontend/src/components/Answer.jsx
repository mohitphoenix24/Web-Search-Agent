import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { linkCitations } from "../utils";
import { AlertIcon, SparkIcon } from "./Icons";

export default function Answer({ turn, elapsed }) {
  const { status, answer, error, stats } = turn;
  return (
    <div className="card">
      <div className="card-head">
        <h2>
          <SparkIcon size={14} /> Answer
        </h2>
        {stats && <span className="meta">{describeTools(stats)} · {elapsed.toFixed(1)}s</span>}
      </div>

      <div className="answer-body">
        {error ? (
          <div className="error-box">
            <AlertIcon size={18} />
            <span>{error}</span>
          </div>
        ) : answer ? (
          <Markdown text={answer.text} sources={answer.sources} turnId={turn.id} />
        ) : turn.draft ? (
          // STREAMING: the answer as it's being written, token by token
          <Markdown text={turn.draft} sources={[]} turnId={turn.id} streaming />
        ) : status === "stopped" ? (
          <p className="muted">You stopped the agent before it answered.</p>
        ) : (
          <Skeleton />
        )}
      </div>
    </div>
  );
}

function describeTools({ searches, reads }) {
  if (!searches && !reads) return "answered without tools";
  const parts = [];
  if (searches) parts.push(`${searches} ${searches === 1 ? "search" : "searches"}`);
  if (reads) parts.push(`${reads} ${reads === 1 ? "page" : "pages"} read`);
  return parts.join(" · ");
}

function Markdown({ text, sources, turnId, streaming = false }) {
  const byId = Object.fromEntries(sources.map((s) => [s.id, s]));

  // Citation links (#source-N) become small pills that scroll to the source card.
  const components = {
    a({ href = "", children }) {
      if (href.startsWith("#source-")) {
        const id = Number(href.slice(8));
        return (
          <a className="cite" href={href} title={byId[id]?.title} onClick={(e) => jumpToSource(e, turnId, id)}>
            {children}
          </a>
        );
      }
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
  };

  return (
    <div className={`prose ${streaming ? "streaming" : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
}

// Each turn has its own [1], [2]... so the element id includes the turn id.
function jumpToSource(e, turnId, id) {
  e.preventDefault();
  const el = document.getElementById(`source-${turnId}-${id}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash");
  void el.offsetWidth; // restart the animation
  el.classList.add("flash");
}

function Skeleton() {
  return (
    <div aria-live="polite">
      <div className="skel-label">
        <span className="spinner small" /> The agent is researching…
      </div>
      <div className="skel-line" style={{ width: "92%" }} />
      <div className="skel-line" style={{ width: "100%" }} />
      <div className="skel-line" style={{ width: "78%" }} />
      <div className="skel-line" style={{ width: "60%" }} />
    </div>
  );
}
