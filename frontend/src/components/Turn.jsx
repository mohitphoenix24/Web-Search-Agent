import { useMemo } from "react";
import { citedIds } from "../utils";
import Answer from "./Answer";
import Sources from "./Sources";
import Trace from "./Trace";

// One question in the chat: the question, the answer + sources, and the agent trace.
export default function Turn({ turn, index, now }) {
  const elapsed = ((turn.endedAt ?? now) - turn.startedAt) / 1000;
  const cited = useMemo(() => (turn.answer ? citedIds(turn.answer.text) : new Set()), [turn.answer]);

  return (
    <article className="turn" id={`turn-${turn.id}`}>
      <h1 className="question">
        {index > 0 && <span className="turn-num">Q{index + 1}</span>}
        {turn.question}
      </h1>
      <div className="results">
        <section className="answer-col">
          <Answer turn={turn} elapsed={elapsed} />
          {turn.answer?.sources.length > 0 && (
            <Sources turnId={turn.id} sources={turn.answer.sources} cited={cited} />
          )}
        </section>
        <aside className="trace-col">
          <Trace steps={turn.steps} status={turn.status} writing={!!turn.draft} elapsed={elapsed} stats={turn.stats} />
        </aside>
      </div>
    </article>
  );
}
