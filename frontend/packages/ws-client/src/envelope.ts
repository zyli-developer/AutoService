import { z } from 'zod';

/**
 * T0.2 §2 帧信封 (envelope)
 * 所有 FE↔BE 帧必须符合此结构。
 */
export const EnvelopeSchema = z.object({
  v: z.literal(1),
  type: z.string(),
  id: z.string(),
  ts: z.string(),
  ref: z.string().optional(),
  payload: z.unknown(),
});

export type Envelope = z.infer<typeof EnvelopeSchema>;

export function parseEnvelope(raw: unknown): Envelope {
  return EnvelopeSchema.parse(raw);
}

export function safeParseEnvelope(raw: unknown) {
  return EnvelopeSchema.safeParse(raw);
}
