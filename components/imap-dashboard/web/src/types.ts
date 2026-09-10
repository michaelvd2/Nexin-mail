export type MessageRef = {
  account_id: string;
  folder_id: string;
  uidvalidity: number;
  uid: number;
};

export type Mailbox = {
  name: string;
  folder_id: string;
  flags: string[];
  messages: number;
  unseen: number;
  uidvalidity: number;
};

export type MailHealth = {
  endpoint: string;
  tls: { verified: boolean; hostname_checked: boolean };
  operator_features: {
    safe_move: boolean;
    drafts: boolean;
    sent: boolean;
    bin: boolean;
    junk: boolean;
    send_configured: boolean;
  };
};

export type MessageHeader = {
  uid: number;
  message_ref: MessageRef;
  date: string;
  from: string;
  subject: string;
  message_id?: string;
  in_reply_to?: string;
  size?: number;
  flags: string[];
  preview?: string;
  category?: "advertising" | null;
  classification_reasons?: string[];
};

export type BodyNode =
  | { type: "text"; text: string }
  | { type: "blocked_image"; remote_image_index?: number }
  | { type: "element"; tag: string; children: BodyNode[] };

export type MailMessage = MessageHeader & {
  folder: string;
  to: string;
  cc?: string;
  references?: string;
  text: string;
  formatted_body?: BodyNode[] | null;
  remote_content_fetched: false;
  untrusted_content: true;
  security_summary?: {
    remote_url_count: number;
    remote_image_count: number;
    link_mismatch_count: number;
    has_attachments: boolean;
  };
};

export type Suspicion = {
  label: "suspicious" | "needs_review" | "no_obvious_indicators";
  reason_codes: string[];
  explanation: string;
  advisory: true;
};

export type Proposal = {
  proposal_id: string;
  action: string;
  targets: MessageRef[];
  before_state: Record<string, unknown>;
  digest: string;
  expires_at: string;
  warnings: string[];
  draft?: { to: string[]; cc: string[]; subject: string; body: string };
  endpoint?: string;
  unsubscribe_candidates?: UnsubscribeCandidate[];
  remote_images?: { count: number; hosts: string[]; blocked_count: number };
  attachment?: AttachmentMetadata;
  approval_required: true;
  review_targets?: Array<MessageRef & {
    display_from: string;
    display_subject: string;
    display_folder: string;
  }>;
};

export type AttachmentMetadata = {
  part_id: string;
  name: string;
  mime_type: string;
  size?: number | null;
  transfer_encoding?: string;
};

export type UnsubscribeCandidate = {
  message_ref: MessageRef;
  display_from: string;
  display_subject: string;
  method: "rfc8058" | "browser" | "mailto_review" | "blocked" | "duplicate" | "unavailable";
  endpoint_host?: string | null;
  reason: string;
  actionable: boolean;
};

export type SendPreview = {
  from: string;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  message_id: string;
  digest: string;
  expires_at: string;
  warnings: string[];
  requires_review_checkbox: true;
};

export type ToolResult<T = unknown> = {
  structuredContent?: T;
  content?: Array<{ type: string; text?: string }>;
  isError?: boolean;
};

export type DraftState = {
  mode?: "compose" | "reply" | "reply_all" | "forward";
  to: string;
  cc: string;
  subject: string;
  body: string;
  source?: MessageRef;
  savedRef?: MessageRef;
  savedMessageId?: string;
};
