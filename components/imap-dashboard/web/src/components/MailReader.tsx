import { createElement, type ReactNode } from "react";
import { AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, Download, FileQuestion, Flag, Forward, Image, MailOpen, MoreHorizontal, Reply, ReplyAll, RotateCcw, ShieldCheck, Trash2 } from "lucide-react";
import { BrainPanel, type BrainInsight, type BrainMode } from "./BrainPanel";
import type { AttachmentMetadata, BodyNode, MailMessage, Suspicion } from "../types";

type Props = {
  message?: MailMessage; suspicion?: Suspicion; profile: string; cleanupEnabled: boolean;
  contextLabel: string; brainMode: BrainMode; brainInsight?: BrainInsight; status: string; onDraft: () => void; onReplyAll: () => void;
  onForward: () => void; onAsk: () => void; onSummarize: () => void;
  onFindActions: () => void; onRefreshBrain: () => void; onCleanup: () => void; onSources: () => void;
  onToggleSeen: () => void; onToggleFlag: () => void; onMoveJunk: () => void;
  onMoveBin: () => void; onRestore?: () => void; onBack: () => void;
  attachments: AttachmentMetadata[]; remoteImages: Record<number, string>; busy: boolean;
  onLoadRemoteImages: () => void; onDownloadAttachment: (attachment: AttachmentMetadata) => void;
};

const safeTags = new Set(["p", "div", "span", "br", "strong", "b", "em", "i", "u", "s", "del", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "hr"]);

function renderBodyNode(node: BodyNode, key: string, remoteImages: Record<number, string>): ReactNode {
  if (node.type === "text") return node.text;
  if (node.type === "blocked_image") {
    const loaded = node.remote_image_index === undefined ? undefined : remoteImages[node.remote_image_index];
    return loaded
      ? <img key={key} className="loaded-mail-image" src={loaded} alt="Extern geladen afbeelding uit dit bericht" />
      : <span key={key} className="blocked-image">Externe afbeelding geblokkeerd</span>;
  }
  if (node.tag === "link") return <span key={key} className="inert-mail-link" title="Link uitgeschakeld voor uw veiligheid">{node.children.map((child, index) => renderBodyNode(child, `${key}-${index}`, remoteImages))}</span>;
  if (!safeTags.has(node.tag)) return node.children.map((child, index) => renderBodyNode(child, `${key}-${index}`, remoteImages));
  return createElement(node.tag, { key }, node.children.map((child, index) => renderBodyNode(child, `${key}-${index}`, remoteImages)));
}

function senderName(value: string) { return value.split("<", 1)[0].trim() || value; }
function initials(value: string) { return senderName(value).split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase(); }

export function MailReader(props: Props) {
  const { message, suspicion } = props;
  if (!message) return <main className="reader empty-reader"><MailOpen /><h1>Selecteer een bericht</h1><p>Open een bericht uit de lijst. De inhoud wordt pas dan lokaal opgehaald.</p></main>;
  const unread = !message.flags.includes("\\Seen");
  const flagged = message.flags.includes("\\Flagged");
  const concerning = suspicion && suspicion.label !== "no_obvious_indicators";
  return (
    <main className="reader">
      <header className="reader-header">
        <button className="compact-back" onClick={props.onBack} aria-label="Terug naar berichtenlijst"><ArrowLeft /></button>
        <h1>{message.subject || "(Geen onderwerp)"}</h1>
        <div className="reader-nav"><button aria-label="Vorig bericht"><ChevronLeft /></button><button aria-label="Volgend bericht"><ChevronRight /></button></div>
        <details className="reader-more"><summary aria-label="Meer berichtopties"><MoreHorizontal /></summary><div className="reader-menu"><button onClick={props.onDraft}><Reply />Beantwoorden</button><button onClick={props.onReplyAll}><ReplyAll />Allen beantwoorden</button><button onClick={props.onForward}><Forward />Doorsturen</button><button onClick={props.onAsk}><FileQuestion />Vraag over deze mail</button>{props.cleanupEnabled ? <button onClick={props.onCleanup}><Trash2 />Opschonen</button> : null}</div></details>
      </header>
      <section className="top-mail-actions" aria-label="Berichtacties">
        <button onClick={props.onToggleSeen} disabled={props.profile !== "operator"}><MailOpen />{unread ? "Markeren als gelezen" : "Markeren als ongelezen"}</button>
        <button onClick={props.onToggleFlag} disabled={props.profile !== "operator"}><Flag />{flagged ? "Markering verwijderen" : "Markeren"}</button>
        <button onClick={props.onMoveJunk} disabled={props.profile !== "operator"}><AlertTriangle />Naar ongewenst</button>
        <button onClick={props.onMoveBin} disabled={props.profile !== "operator"}><Trash2 />Naar prullenbak</button>
        {props.onRestore ? <button onClick={props.onRestore} disabled={props.profile !== "operator"}><RotateCcw />Verplaatsing herstellen</button> : null}
        <span className="action-note"><ShieldCheck />Prullenbak is herstelbaar</span>{props.profile !== "operator" ? <span className="read-mode-note">Veilige leesmodus</span> : null}
      </section>
      <section className="sender-card"><span className="avatar">{initials(message.from)}</span><div className="sender-details"><div className="sender-title"><strong>{senderName(message.from)}</strong>{concerning ? <span className="marker warning"><AlertTriangle />Controleren</span> : <span className="marker verified"><ShieldCheck />Geen duidelijke signalen</span>}</div><div><span>Aan:</span> {message.to || "U"}</div>{message.cc ? <div><span>Cc:</span> {message.cc}</div> : null}</div><time className="message-time">{message.date}</time></section>
      {message.security_summary?.remote_image_count || props.attachments.length ? <section className="content-access-bar" aria-label="Afbeeldingen en bijlagen">
        {message.security_summary?.remote_image_count ? <button onClick={props.onLoadRemoteImages} disabled={props.profile !== "operator" || Boolean(concerning) || props.busy}><Image />Afbeeldingen laden ({message.security_summary.remote_image_count})</button> : null}
        {props.attachments.map((attachment) => <button key={attachment.part_id} onClick={() => props.onDownloadAttachment(attachment)} disabled={props.profile !== "operator" || props.busy}><Download /><span>{attachment.name}</span><small>{attachment.size == null ? attachment.mime_type : `${Math.max(1, Math.ceil(attachment.size / 1024))} KB`}</small></button>)}
      </section> : null}
      {concerning ? <section className="suspicion-panel" aria-label="Uitleg verdachte mail"><AlertTriangle /><div><strong>Adviserende phishingmarkering</strong><p>{suspicion.explanation}</p><small>{suspicion.reason_codes.map((reason) => reason.replaceAll("_", " ")).join(" · ")}</small></div></section> : null}
      <article className="mail-body" aria-label="Berichtinhoud">{message.formatted_body?.length ? <div className="formatted-mail">{message.formatted_body.map((node, index) => renderBodyNode(node, `body-${index}`, props.remoteImages))}</div> : <pre>{message.text}</pre>}</article>
      <BrainPanel contextLabel={props.contextLabel} mode={props.brainMode} insight={props.brainInsight} onHighlights={props.onSummarize} onActionable={props.onFindActions} onDraft={props.onDraft} onReplyAll={props.onReplyAll} onSources={props.onSources} onRefresh={props.onRefreshBrain} />
      {props.status ? <span className="operation-status" role="status">{props.status}</span> : null}
    </main>
  );
}
