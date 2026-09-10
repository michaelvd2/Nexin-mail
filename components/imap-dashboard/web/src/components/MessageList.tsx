import { Inbox, MailX, Megaphone, PenSquare, RefreshCw, Search, Settings2, ShieldAlert, Star, Trash2 } from "lucide-react";
import { useMemo } from "react";
import type { MessageHeader } from "../types";

type Props = { messages: MessageHeader[]; selectedUid?: number; query: string; loading: boolean; suspiciousUids: Set<number>; advertisingView?: boolean; advertisingCount?: number; canUnsubscribeAdvertising?: boolean; onQuery: (value: string) => void; onSearch: () => void; onSelect: (message: MessageHeader) => void; onRefresh: () => void; onInbox?: () => void; onAdvertising?: () => void; onCompose?: () => void; onSettings?: () => void; onMoveAllAdvertising?: () => void; onUnsubscribeAdvertising?: () => void };
function senderName(value: string) { return value.split("<", 1)[0].trim() || value; }
function compactDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const now = new Date();
  if (parsed.toDateString() === now.toDateString()) {
    return parsed.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (parsed.toDateString() === yesterday.toDateString()) return "Gisteren";
  return parsed.toLocaleDateString("nl-NL", {
    day: "numeric",
    month: "short",
    year: parsed.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

export function MessageList({ messages, selectedUid, query, loading, suspiciousUids, advertisingView, advertisingCount = 0, canUnsubscribeAdvertising, onQuery, onSearch, onSelect, onRefresh, onInbox, onAdvertising, onCompose, onSettings, onMoveAllAdvertising, onUnsubscribeAdvertising }: Props) {
  const filtered = useMemo(() => { const needle = query.trim().toLowerCase(); if (!needle) return messages; return messages.filter((message) => `${message.from}\n${message.subject}\n${message.preview ?? ""}`.toLowerCase().includes(needle)); }, [messages, query]);
  return <section className="message-list" aria-label={advertisingView ? "Reclameberichten" : "Berichtenlijst"}>
    <nav className="compact-list-nav" aria-label="Compacte mailnavigatie">
      <button aria-label="Postvak compact" className={!advertisingView ? "active" : ""} onClick={onInbox}><Inbox /><span>Postvak</span></button>
      <button aria-label={`Reclame compact ${advertisingCount}`} className={advertisingView ? "active" : ""} onClick={onAdvertising}><Megaphone /><span>Reclame {advertisingCount}</span></button>
      <button aria-label="Nieuw bericht compact" onClick={onCompose}><PenSquare /><span>Nieuw</span></button>
      <button aria-label="Instellingen compact" onClick={onSettings}><Settings2 /><span>Instellingen</span></button>
    </nav>
    <div className="search-row"><Search /><input aria-label="Zoeken in uw mail" value={query} onChange={(event) => onQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") onSearch(); }} placeholder="Zoeken in uw mail · Enter voor zoeken op server" /><kbd>Ctrl K</kbd></div>
    <div className="list-heading"><span>{advertisingView ? "Automatisch ingedeelde reclame" : "Nieuwste"}</span><span>{filtered.length} getoond</span></div>
    {advertisingView && filtered.length ? <div className="bulk-actions" aria-label="Reclameacties">
      {canUnsubscribeAdvertising ? <button className="bulk-unsubscribe-button" onClick={onUnsubscribeAdvertising}><MailX />Afmelden bij {filtered.length}</button> : null}
      <button className="bulk-bin-button" onClick={onMoveAllAdvertising}><Trash2 />Alle {filtered.length} naar prullenbak</button>
    </div> : null}
    <div className="message-rows" role="listbox" aria-label={advertisingView ? "Reclame" : "Berichten"}>{filtered.length === 0 ? <div className="empty-state">{advertisingView ? "Geen reclame gevonden in de laatste 31 dagen." : "Geen berichten in deze weergave."}</div> : null}
      {filtered.map((message) => { const unread = !message.flags.includes("\\Seen"); const suspicious = suspiciousUids.has(message.uid); return <button type="button" role="option" aria-selected={selectedUid === message.uid} className={`message-row ${selectedUid === message.uid ? "selected" : ""}`} key={`${message.message_ref.folder_id}-${message.uid}`} onClick={() => onSelect(message)}>
        <span className={`unread-dot ${unread ? "visible" : ""}`} aria-label={unread ? "Ongelezen" : "Gelezen"} /><span className="message-copy"><span className="sender-line"><strong>{senderName(message.from)}</strong><time title={message.date}>{compactDate(message.date)}</time></span><span className="subject-line"><strong>{message.subject || "(Geen onderwerp)"}</strong>{suspicious ? <ShieldAlert className="suspicious-icon" aria-label="Verdachte markering" /> : <Star />}</span><span className="preview-line">{message.preview || "Geen berichtvoorbeeld beschikbaar."}</span></span>
      </button>; })}</div>
    <footer className="list-footer"><span>{filtered.length ? `1–${filtered.length} van ${messages.length}` : "0 berichten"}</span><button onClick={onRefresh} aria-label="Berichten vernieuwen" disabled={loading}><RefreshCw className={loading ? "spinning" : ""} /></button></footer>
  </section>;
}
