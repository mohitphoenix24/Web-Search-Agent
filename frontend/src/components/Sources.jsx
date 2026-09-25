import { faviconOf, hideBrokenImage, hostOf } from "../utils";
import { ExternalIcon } from "./Icons";

// Shows the sources the answer cited, plus (collapsed) the ones it read but didn't use.
export default function Sources({ turnId, sources, cited }) {
  const citedList = sources.filter((s) => cited.has(s.id));
  const others = sources.filter((s) => !cited.has(s.id));
  const main = citedList.length ? citedList : sources;

  return (
    <section className="sources">
      <h3 className="section-title">
        {citedList.length ? "Cited sources" : "Sources"} <span className="count">{main.length}</span>
      </h3>
      <div className="source-grid">
        {main.map((s) => (
          <SourceCard key={s.id} source={s} turnId={turnId} />
        ))}
      </div>

      {citedList.length > 0 && others.length > 0 && (
        <details className="more-sources">
          <summary>
            + {others.length} more {others.length === 1 ? "result" : "results"} the agent read but didn't cite
          </summary>
          <div className="source-grid">
            {others.map((s) => (
              <SourceCard key={s.id} source={s} turnId={turnId} />
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function SourceCard({ source, turnId }) {
  return (
    <a id={`source-${turnId}-${source.id}`} className="source-card" href={source.url} target="_blank" rel="noreferrer">
      <div className="source-top">
        <span className="source-num">{source.id}</span>
        <img className="favicon" src={faviconOf(source.url)} alt="" loading="lazy" onError={hideBrokenImage} />
        <span className="source-host">{hostOf(source.url)}</span>
        {source.read && <span className="read-badge">Read in full</span>}
        <ExternalIcon size={13} className="source-ext" />
      </div>
      <div className="source-title">{source.title}</div>
      <div className="source-snippet">{source.snippet}</div>
    </a>
  );
}
