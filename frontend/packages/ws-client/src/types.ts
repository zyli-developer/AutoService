/**
 * T0.2 Frontend WS Schema v1.0 · 类型镜像
 * 与 docs/contracts/frontend-ws-schema.md v1.0 手动对齐；契约 bump 时同步本文件。
 */

export const FE_TO_BE_TYPES = [
  'client_hello',       // F1
  'ping',               // F2
  'client_ack',         // F3
  'customer_message',   // F4
  'csat_response',      // F5
  'subscribe',          // F6
  'unsubscribe',        // F7
  'operator_join',      // F8
  'operator_leave',     // F9
  'operator_message',   // F10
  'operator_command',   // F11
  'admin_command',      // F12
  'history_request',    // F13
  'edit_request',       // F14
  'delete_request',     // F15
] as const;
export type FeToBeType = (typeof FE_TO_BE_TYPES)[number];

export const BE_TO_FE_TYPES = [
  'server_hello',        // S1
  'pong',                // S2
  'ack',                 // S3
  'error',               // S4
  'message',             // S5
  'message_edited',      // S6
  'message_deleted',     // S7
  'event',               // S8
  'history_snapshot',    // S9
  'csat_request',        // S10
  'command_response',    // S11
  'replay_complete',     // S12
  'subscription_added',  // S13
  'subscription_removed',// S14
  'takeover_warning',    // S15
  'takeover_warning_cancelled',// S16
] as const;
export type BeToFeType = (typeof BE_TO_FE_TYPES)[number];

/**
 * ViewerRole (WS 层) · 见 frontend-ws-schema.md §1
 * 大写。ADMIN 不是 ParticipantRole 一员，仅在 WS 层使用。
 */
export type ViewerRole = 'CUSTOMER' | 'OPERATOR' | 'ADMIN';

/** 对齐 autoservice.conversation_engine.types.MessageVisibility */
export type Visibility = 'public' | 'side' | 'system';

/** 对齐 autoservice.conversation_engine.types.ConversationMode */
export type Mode = 'auto' | 'copilot' | 'takeover';

/** 对齐 autoservice.conversation_engine.types.ParticipantRole */
export type ParticipantRole = 'customer' | 'agent' | 'operator' | 'observer';

/** 对齐 autoservice.conversation_engine.types.ConversationState */
export type ConversationState = 'created' | 'active' | 'idle' | 'closed';

/** 对齐 autoservice.conversation_engine.types.Outcome */
export type Outcome = 'resolved' | 'abandoned' | 'escalated';

/** T1B.4: §3.3 reconnect cursor */
export interface LastSeenCursor {
  conv_seq?: Record<string, { msg: number; evt: number }>;
  global_event_id?: string;  // operator/admin only
}

/** T0.2 §3.1 client_hello payload */
export interface ClientHelloPayload {
  protocol_version: number;
  client_app: string;
  last_seen?: LastSeenCursor;   // was: string
  conversation_id?: string;
  operator_id?: string;
  squads?: string[];
}

/** T0.2 §3.1 server_hello payload */
export interface ServerHelloPayload {
  session_id: string;
  protocol_version: number;
  server_time: string;
  viewer_role: ViewerRole;
  accepted_subscriptions: string[];
  server_capabilities: string[];
}

/** T0.2 §6 error payload */
export interface ErrorPayload {
  code: string;
  message: string;
  recoverable: boolean;
  details?: Record<string, unknown>;
}

export interface Message {
  id: string;
  source: string;
  content: string;
  visibility: Visibility;
  sequence_number: number;
  timestamp: string;
  edit_of?: string;
  metadata?: Record<string, unknown>;
}

export interface EngineEvent {
  id: string;
  type: string;
  conversation_id: string;
  data: Record<string, unknown>;
  timestamp: string;
  sequence_number: number;
}

/** T0.2 §6 错误码 */
export const ERROR_CODES = {
  SCHEMA: '4010_SCHEMA',
  AUTH: '4011_AUTH',
  VALIDATION: '4012_VALIDATION',
  PERMISSION: '4013_PERMISSION',
  ILLEGAL_MODE: '4014_ILLEGAL_MODE_TRANSITION',
  TIMER_NOT_FOUND: '4015_TIMER_NOT_FOUND',
  PARTICIPANT_NOT_FOUND: '4016_PARTICIPANT_NOT_FOUND',
  RATE_LIMIT: '4017_RATE_LIMIT',
  SEQ_GAP: '4018_SEQUENCE_GAP',
  VERSION_INCOMPATIBLE: '4040_VERSION_INCOMPATIBLE',
  INTERNAL: '5010_INTERNAL',
  ENGINE: '5011_ENGINE',
} as const;
export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];
