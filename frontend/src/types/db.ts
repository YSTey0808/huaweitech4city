// Database row types — mirrors supabase/migrations/ exactly.
//
// Conventions:
//   uuid        -> string
//   timestamptz -> string (ISO; Supabase returns timestamps as strings)
//   float       -> number
//   uuid[]      -> string[]
//   nullable    -> `| null`
//
// `label` and `msg_type` are kept as open-ended `string` on purpose: harm
// labels are open-ended per the model contract, and msg_type may grow beyond
// 'text' later. Do not narrow these to enums.

export interface Profile {
  id: string;
  username: string | null;
  display_name: string | null;
  avatar_color: string | null;
  phone: string | null;
  bio: string | null;
  created_at: string;
}

export interface Friendship {
  user_id: string;
  friend_id: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  is_group: boolean;
  dm_key: string | null;
  created_at: string;
}

export interface ConversationMember {
  conversation_id: string;
  user_id: string;
  last_read_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  content: string | null;
  msg_type: string;
  reply_to: string | null;
  created_at: string;
}

export interface MessageScore {
  id: string;
  msg_id: string;
  label: string | null;
  confidence: number | null;
  created_at: string;
}

export interface ConversationScore {
  id: string;
  conversation_id: string;
  label: string | null;
  confidence: number | null;
  evidence_msg_ids: string[] | null;
  severity: string | null;
  reasoning: string | null;
  created_at: string;
}
