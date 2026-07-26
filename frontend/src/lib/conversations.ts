import { supabase } from './supabase'

// Returns the id of the 1-to-1 DM with the given friend, creating it if none
// exists yet. All the work happens in the `open_dm` RPC (migration 006):
// atomic find-or-create via a unique dm_key, so concurrent calls from any
// client resolve to the same conversation. The caller must be friends with
// the target — the RPC rejects otherwise.
export async function openOrCreateDm(friendId: string): Promise<string> {
  const { data, error } = await supabase.rpc('open_dm', { other_user: friendId })
  if (error) throw error
  return data as string
}
