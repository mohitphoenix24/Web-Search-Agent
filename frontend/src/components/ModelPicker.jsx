import { useEffect, useRef, useState } from "react";
import { CheckIcon, ChevronIcon } from "./Icons";

// Dropdown to choose which LLM answers the next question.
// Models come from the backend (/api/info), grouped by provider.
export default function ModelPicker({ models, value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = models.find((m) => m.id === value);

  // Close when clicking outside or pressing Escape
  useEffect(() => {
    if (!open) return;
    const onClick = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = [...new Set(models.map((m) => m.provider_label))];

  return (
    <div className="model-picker" ref={ref}>
      <button
        className="model-btn"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Choose the model"
      >
        <span className={`status-dot ${selected?.available ? "" : "off"}`} />
        <span className="model-btn-name">{selected?.name ?? "Choose a model"}</span>
        {selected && <span className={`provider-tag ${selected.provider}`}>{selected.provider === "ollama" ? "Local" : "Online"}</span>}
        <ChevronIcon size={14} className={`chev ${open ? "open" : ""}`} />
      </button>

      {open && (
        <div className="model-menu" role="listbox" aria-label="Models">
          {groups.map((group) => (
            <div key={group} className="model-group">
              <div className="model-group-label">{group}</div>
              {models
                .filter((m) => m.provider_label === group)
                .map((m) => (
                  <button
                    key={m.id}
                    role="option"
                    aria-selected={m.id === value}
                    className={`model-option ${m.id === value ? "selected" : ""}`}
                    disabled={!m.available}
                    onClick={() => {
                      onChange(m.id);
                      setOpen(false);
                    }}
                  >
                    <span className="model-option-text">
                      <span className="model-option-name">
                        {m.name} <code>{m.id}</code>
                      </span>
                      <span className={`model-option-note ${m.available ? "" : "warn"}`}>
                        {m.available ? m.note : `Unavailable: ${m.problem}`}
                      </span>
                    </span>
                    {m.id === value && <CheckIcon size={16} className="model-check" />}
                  </button>
                ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
