import { AlertTriangle, CheckCircle2, Clock3, Link2, Lock, Paperclip, Send, Users, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { MailHealth, Proposal, SendPreview } from "../types";

const actionLabels: Record<string, string> = {
  mark_read: "Als gelezen markeren", mark_unread: "Als ongelezen markeren", flag: "Markeren",
  unflag: "Markering verwijderen", move_junk: "Naar Ongewenst", move_bin: "Naar prullenbak",
  bulk_move_bin: "Meerdere berichten naar prullenbak", restore: "Verplaatsing herstellen",
  save_draft: "Concept opslaan", send: "E-mail verzenden", unsubscribe: "Afmelden",
  bulk_unsubscribe: "Bevestigde reclame-afmeldingen uitvoeren",
  load_remote_images: "Externe afbeeldingen laden",
  download_attachment: "Bijlage downloaden",
};

const unsubscribeMethodLabels: Record<string, string> = {
  rfc8058: "Veilige éénklik-afmelding",
  browser: "Browserbevestiging door Codex",
  mailto_review: "Aparte concept- en verzendcontrole nodig",
  blocked: "Geblokkeerd door veiligheidscontrole",
  duplicate: "Zelfde mailinglijst — één keer afmelden",
  unavailable: "Geen beveiligde afmeldoptie gevonden",
};

type ConfirmProps = {
  title: string;
  proposal: Proposal;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function ConfirmDialog({ title, proposal, busy, onCancel, onConfirm }: ConfirmProps) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) onCancel(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [busy, onCancel]);
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <button className="modal-close" onClick={onCancel} aria-label="Beoordeling sluiten"><X /></button>
        <h2 id="confirm-title">{title}</h2>
        <p>Er is nog geen actie uitgevoerd. Na deze voorvertoning opent Nexin Mail een native beveiligingsvenster voor de definitieve bevestiging.</p>
        <div className="proposal-card"><strong>{actionLabels[proposal.action] ?? proposal.action.replaceAll("_", " ")}</strong><code>{proposal.digest.slice(0, 16)}…</code></div>
        {proposal.review_targets?.length ? <section className="proposal-target-list" aria-label="Exacte berichten voor deze actie">
          {proposal.review_targets.map((target) => <article key={`${target.folder_id}-${target.uid}`}>
            <strong>{target.display_from || "Onbekende afzender"}</strong>
            <span>{target.display_subject || "(Geen onderwerp)"}</span>
            <small>{target.display_folder} · UID {target.uid}</small>
          </article>)}
        </section> : null}
        {proposal.draft ? <section className="proposal-draft" aria-label="Exact draft preview">
          <div><strong>Aan</strong><span>{proposal.draft.to.join(", ")}</span></div>
          <div><strong>Cc</strong><span>{proposal.draft.cc.join(", ") || "—"}</span></div>
          <div><strong>Onderwerp</strong><span>{proposal.draft.subject || "(Geen onderwerp)"}</span></div>
          <pre>{proposal.draft.body}</pre>
        </section> : null}
        {proposal.endpoint ? <div className="proposal-endpoint"><strong>HTTPS endpoint</strong><code>{proposal.endpoint}</code></div> : null}
        {proposal.unsubscribe_candidates?.length ? <section className="unsubscribe-review" aria-label="Voorgestelde reclame-afmeldlijst">
          <header><strong>Voorgestelde lijst</strong><span>{proposal.unsubscribe_candidates.filter((item) => item.actionable).length} uitvoerbaar</span></header>
          {proposal.unsubscribe_candidates.map((item) => <article className={item.actionable ? "ready" : "skipped"} key={`${item.message_ref.folder_id}-${item.message_ref.uid}`}>
            <div><strong>{item.display_from || "Onbekende afzender"}</strong><span>{item.display_subject || "(Geen onderwerp)"}</span></div>
            <small>{unsubscribeMethodLabels[item.method] ?? item.method}{item.endpoint_host ? ` · ${item.endpoint_host}` : ""}</small>
          </article>)}
        </section> : null}
        {proposal.remote_images ? <section className="content-review" aria-label="Externe afbeeldingen controleren"><strong>{proposal.remote_images.count} afbeelding(en)</strong><span>{proposal.remote_images.hosts.join(" · ")}</span>{proposal.remote_images.blocked_count ? <small>{proposal.remote_images.blocked_count} onveilige URL(s) blijven geblokkeerd</small> : null}</section> : null}
        {proposal.attachment ? <section className="content-review" aria-label="Bijlage controleren"><strong>{proposal.attachment.name}</strong><span>{proposal.attachment.mime_type} · {proposal.attachment.size == null ? "onbekende grootte" : `${proposal.attachment.size} bytes`}</span></section> : null}
        {proposal.warnings.map((warning) => <div className="proposal-warning" key={warning}><AlertTriangle />{warning}</div>)}
        <div className="expiry"><Clock3 />Deze goedkeuring verloopt na vijf minuten en kan één keer worden gebruikt.</div>
        <div className="dialog-actions"><button onClick={onCancel}>Annuleren</button><button className="primary danger-primary" aria-label="Actie bevestigen" title="Bevestigen in beveiligingsvenster" onClick={onConfirm} disabled={busy}>{busy ? "Beveiligingsvenster…" : "Bevestigen in beveiligingsvenster"}</button></div>
      </section>
    </div>
  );
}

type SendProps = {
  proposal: Proposal;
  preview: SendPreview;
  busy: boolean;
  onCancel: () => void;
  onSend: () => void;
};

export function SendReviewDialog({ proposal, preview, busy, onCancel, onSend }: SendProps) {
  const [reviewed, setReviewed] = useState(false);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) onCancel(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [busy, onCancel]);
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="send-dialog" role="dialog" aria-modal="true" aria-labelledby="send-review-title">
        <button className="modal-close" onClick={onCancel} aria-label="Verzendcontrole sluiten"><X /></button>
        <h2 id="send-review-title">Controleren vóór verzenden</h2>
        <p>Er is nog niets verzonden. Na deze voorvertoning opent Nexin Mail een native beveiligingsvenster voor de definitieve bevestiging.</p>
        <div className="send-preview">
          <div><strong>Van</strong><span>{preview.from}</span></div>
          <div><strong>Aan</strong><span>{preview.to.join(", ")}</span></div>
          <div><strong>Cc</strong><span>{preview.cc.join(", ") || "—"}</span></div>
          <div><strong>Onderwerp</strong><span>{preview.subject}</span></div>
          <pre>{preview.body}</pre>
        </div>
        <div className="review-checks">
          <div><Users /><span><strong>Ontvangers</strong>{preview.to.length + preview.cc.length} totaal</span>{preview.cc.length ? <em>Allen beantwoorden</em> : <CheckCircle2 />}</div>
          <div><Link2 /><span><strong>Links</strong>Externe links blijven uitgeschakeld</span><CheckCircle2 /></div>
          <div><Paperclip /><span><strong>Bijlagen</strong>Uitgeschakeld in versie 1</span><CheckCircle2 /></div>
        </div>
        {preview.warnings.map((warning) => <div className="proposal-warning" key={warning}><AlertTriangle />{warning}</div>)}
        <div className="expiry"><Lock />Elke wijziging aan ontvangers of bericht annuleert deze goedkeuring.</div>
        <div className="expiry"><Clock3 />De controle verloopt om {new Date(preview.expires_at).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" })}.</div>
        <label className="review-checkbox"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} /><span>Ik heb de ontvangers en het bericht gecontroleerd</span></label>
        <div className="dialog-actions"><button onClick={onCancel}>Terug naar concept</button><button className="primary" aria-label="Deze e-mail verzenden" title="Bevestigen in beveiligingsvenster" onClick={onSend} disabled={!reviewed || busy}><Send />{busy ? "Beveiligingsvenster…" : "Bevestigen in beveiligingsvenster"}</button><small>Wordt één keer verzonden. Automatisch opnieuw proberen is onmogelijk.</small></div>
      </section>
    </div>
  );
}

type SettingsProps = {
  packs: { phishing: boolean; priority: boolean; cleanup: boolean };
  firstSetup: boolean;
  priorityRules: { important_senders: string[]; high_keywords: string[]; low_keywords: string[] };
  health?: MailHealth;
  profile: string;
  busy: boolean;
  onClose: () => void;
  onSave: (value: { phishing: boolean; priority: boolean; cleanup: boolean }, rules: { important_senders: string[]; high_keywords: string[]; low_keywords: string[] }) => void;
};

export function SettingsDialog({ packs, firstSetup, priorityRules, health, profile, busy, onClose, onSave }: SettingsProps) {
  const [value, setValue] = useState(firstSetup ? { ...packs, phishing: true } : packs);
  const [rules, setRules] = useState({
    important_senders: priorityRules.important_senders.join(", "),
    high_keywords: priorityRules.high_keywords.join(", "),
    low_keywords: priorityRules.low_keywords.join(", "),
  });
  const parsedRules = {
    important_senders: rules.important_senders.split(",").map((item) => item.trim()).filter(Boolean),
    high_keywords: rules.high_keywords.split(",").map((item) => item.trim()).filter(Boolean),
    low_keywords: rules.low_keywords.split(",").map((item) => item.trim()).filter(Boolean),
  };
  const priorityReady = Object.values(parsedRules).some((items) => items.length > 0);
  return (
    <div className="modal-backdrop" role="presentation"><section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="packs-title">
      <button className="modal-close" onClick={onClose} aria-label="Instellingen sluiten"><X /></button>
      <h2 id="packs-title">Mailbox en functiepakketten</h2><p>De basisfuncties staan altijd aan. Pakketten voegen lokale analyses toe; niets verzendt of verplaatst mail automatisch.</p>
      <section className="connection-card" aria-label="Connection status">
        <div><strong>{health?.tls.verified && health?.tls.hostname_checked ? "Geverifieerde lokale verbinding" : "Verbinding moet worden gecontroleerd"}</strong><small>{health?.endpoint ?? "Voer de veilige lokale installatie uit"}</small></div>
        <span className={profile === "operator" ? "operator-on" : "read-safe"}>{profile === "operator" ? "Gecontroleerde acties actief" : "Veilige leesmodus"}</span>
        <small>Veilige prullenbak: {health?.operator_features.bin ? "beschikbaar" : "niet beschikbaar"} · Bevestigd verzenden: {health?.operator_features.send_configured ? "ingesteld" : "niet beschikbaar"}</small>
      </section>
      <label className="pack-row"><span><strong>Phishingschild</strong><small>{firstSetup ? "Vooraf geselecteerd; start pas na uw bevestiging. " : ""}Adviserende markeringen met redenen. Opent nooit links.</small></span><input type="checkbox" checked={value.phishing} onChange={(event) => setValue({ ...value, phishing: event.target.checked })} /></label>
      <label className="pack-row"><span><strong>Prioriteit</strong><small>Lokale labels op basis van regels die u eerst goedkeurt.</small></span><input type="checkbox" checked={value.priority} onChange={(event) => setValue({ ...value, priority: event.target.checked })} /></label>
      {value.priority ? <section className="priority-rules" aria-label="Prioriteitsregels">
        <label><span>Belangrijke afzenders</span><input value={rules.important_senders} onChange={(event) => setRules({ ...rules, important_senders: event.target.value })} placeholder="owner@example.test, trusted domain" /></label>
        <label><span>Woorden met hoge prioriteit</span><input value={rules.high_keywords} onChange={(event) => setRules({ ...rules, high_keywords: event.target.value })} placeholder="goedkeuring, deadline" /></label>
        <label><span>Woorden met lage prioriteit</span><input value={rules.low_keywords} onChange={(event) => setRules({ ...rules, low_keywords: event.target.value })} placeholder="nieuwsbrief, aanbieding" /></label>
        <small>Komma-gescheiden, lokaal en beschermd met Windows DPAPI. Minstens één regel is vereist.</small>
      </section> : null}
      <label className="pack-row"><span><strong>Opschonen</strong><small>Zoekt beveiligde afmeldopties. Bevestiging is altijd vereist.</small></span><input type="checkbox" checked={value.cleanup} onChange={(event) => setValue({ ...value, cleanup: event.target.checked })} /></label>
      <div className="dialog-actions"><button onClick={onClose}>Annuleren</button><button className="primary" disabled={busy || (value.priority && !priorityReady)} onClick={() => onSave(value, parsedRules)}>{busy ? "Opslaan…" : "Instelling bevestigen"}</button></div>
    </section></div>
  );
}
