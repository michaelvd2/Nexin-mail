import { BookOpen, Brain, CheckCircle2, RefreshCw, Reply, ReplyAll, Target } from "lucide-react";

export type BrainMode = "summary" | "actions";

export type BrainInsight = {
  action: BrainMode;
  result?: string;
  cached?: boolean;
};

type Props = {
  contextLabel: string;
  mode: BrainMode;
  insight?: BrainInsight;
  onHighlights: () => void;
  onActionable: () => void;
  onDraft: () => void;
  onReplyAll: () => void;
  onSources: () => void;
  onRefresh: () => void;
};

export function BrainPanel({ contextLabel, mode, insight, onHighlights, onActionable, onDraft, onReplyAll, onSources, onRefresh }: Props) {
  const label = mode === "actions" ? "Belangrijkste actie" : "Highlights";
  const hasResult = Boolean(insight?.result);

  return (
    <section className={`brain-panel${hasResult ? " has-result" : ""}`} aria-label="Brein">
      <header className="brain-header">
        <span className="brain-mark" aria-hidden="true"><Brain /></span>
        <span className="brain-title"><strong>Brein</strong><small>{contextLabel}</small></span>
        <button className="brain-sources" onClick={onSources}><BookOpen />Bronnen</button>
      </header>

      <div className="brain-tabs" role="tablist" aria-label="Breinweergave">
        <button id="brain-actions-tab" role="tab" aria-selected={mode === "actions"} aria-controls="brain-tab-panel" className={mode === "actions" ? "selected" : ""} onClick={onActionable}><CheckCircle2 />Acties</button>
        <button id="brain-summary-tab" role="tab" aria-selected={mode === "summary"} aria-controls="brain-tab-panel" className={mode === "summary" ? "selected" : ""} onClick={onHighlights}><Brain />Highlights</button>
      </div>

      <div id="brain-tab-panel" className="brain-tab-panel" role="tabpanel" aria-labelledby={mode === "actions" ? "brain-actions-tab" : "brain-summary-tab"} aria-live="polite">
        {hasResult ? (
          <div className="brain-insight">
            <div className="brain-insight-label">{mode === "actions" ? <Target /> : <Brain />}<strong>{label}</strong></div>
            <pre>{insight?.result}</pre>
            <span className="brain-cache-note">{insight?.cached ? "Lokaal versleuteld hergebruikt" : "Nieuw berekend en lokaal versleuteld"}</span>
            <button className="brain-refresh" onClick={onRefresh} aria-label="Brein opnieuw berekenen" title="Opnieuw berekenen"><RefreshCw /></button>
          </div>
        ) : (
          <p className="brain-empty">Klik op {mode === "actions" ? "Acties" : "Highlights"} om dit overzicht voor de geselecteerde mail te laden.</p>
        )}
      </div>

      <div className="brain-footer" aria-label="Breinacties">
        <button className="brain-reply primary" onClick={onDraft}><Reply />Antwoord opstellen</button>
        <button className="brain-reply" onClick={onReplyAll}><ReplyAll />Allen beantwoorden</button>
      </div>
    </section>
  );
}
