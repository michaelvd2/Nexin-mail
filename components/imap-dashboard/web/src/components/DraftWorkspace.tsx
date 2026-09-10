import { AlertTriangle, ArrowLeft, Brain, CheckCircle2, Lock, Save, Send } from "lucide-react";
import type { DraftState } from "../types";

type Props = {
  draft: DraftState;
  profile: string;
  busy: boolean;
  onChange: (next: DraftState) => void;
  onBack: () => void;
  onSave: () => void;
  onReview: () => void;
};

export function DraftWorkspace({ draft, profile, busy, onChange, onBack, onSave, onReview }: Props) {
  const set = (field: keyof DraftState, value: string) => onChange({ ...draft, [field]: value, savedRef: undefined, savedMessageId: undefined });
  return (
    <main className="draft-workspace">
      <header className="draft-header">
        <button className="icon-button" onClick={onBack} aria-label="Terug naar bericht"><ArrowLeft /></button>
        <h1>{draft.mode === "compose" ? "Nieuw bericht" : draft.mode === "forward" ? "Doorgestuurd concept" : draft.mode === "reply_all" ? "Concept voor allen" : "Antwoordconcept"}</h1>
        <span className={`draft-status ${draft.savedRef ? "saved" : ""}`}>{draft.savedRef ? <><CheckCircle2 />Opgeslagen in Concepten</> : "Niet opgeslagen"}</span>
      </header>
      <div className="draft-fields">
        <label><span>Aan</span><input aria-label="Aan" value={draft.to} onChange={(event) => set("to", event.target.value)} /></label>
        <label><span>Cc</span><input value={draft.cc} onChange={(event) => set("cc", event.target.value)} /></label>
        {draft.cc ? <div className="reply-warning"><AlertTriangle />Allen beantwoorden staat aan. Iedere vermelde ontvanger krijgt dit bericht.</div> : null}
        <label><span>Onderwerp</span><input value={draft.subject} onChange={(event) => set("subject", event.target.value)} /></label>
      </div>
      <textarea className="draft-body" aria-label="Conceptbericht" value={draft.body} onChange={(event) => set("body", event.target.value)} placeholder="Schrijf het bericht hier. Er wordt niets automatisch verzonden." />
      <section className="draft-tools" aria-label="Hulpmiddelen voor toon en helderheid">
        <button type="button">Korter</button><button type="button">Warmer</button><button type="button">Directer</button><button type="button"><Brain />Helderder maken</button>
        <div className="draft-guidance"><strong>Toon en helderheid</strong><p>Houd het bericht duidelijk, beleefd en specifiek. Controleer de ontvangers vóór de beoordeling.</p></div>
      </section>
      <footer className="draft-footer">
        <button className="primary" onClick={onReview} disabled={!draft.savedRef || busy || profile !== "operator"}><Send />Controleren vóór verzenden</button>
        <button onClick={onSave} disabled={!draft.to.trim() || busy || profile !== "operator"}><Save />Concept opslaan</button>
        <span><Lock />Niets wordt zonder uw bevestiging verzonden</span>
      </footer>
    </main>
  );
}
