"""
Anonymizes dataset/train.jsonl and dataset/validation.jsonl in place:
  - conversation_id is replaced with a random opaque id (no longer
    conv<labeller_id>_<n> -- that pattern leaked which labeller wrote a
    conversation, see docs/pipeline.md's Known Limitations for why that
    matters). message_id keeps the original <conversation_id>_<n>
    STRUCTURE (n = 1-indexed position in the conversation), just built
    from the new random conversation_id -- kept, not dropped, because
    reply_to_message_id threading and the cached embeddings file both key
    off it; dropping it would silently break the GNN's reply_to edge
    relation and orphan the existing embeddings.
  - sender_id/recipient_id/user1_id/user2_id are replaced with random ids,
    consistent WITHIN a conversation (the same real participant always
    maps to the same random id across their messages in that
    conversation) -- required, not cosmetic: MessageGraphSAGE's
    same_speaker edges depend on knowing which messages share a sender
    within one conversation. Consistency does NOT need to hold ACROSS
    conversations -- nothing in the current architecture tracks user
    identity across conversations (see docs/pipeline.md's Known
    Limitations: no cross-conversation modeling).

Re-keys the cached embeddings (dataset/train_embeddings.npz,
dataset/validation_embeddings.npz) to the new message_ids instead of
re-running the encoder -- message *content* is untouched, so the actual
embedding vectors don't need to be recomputed, only relabeled.

Preserves original conversation order in the output files, so re-running
make_data_splits.py afterward reproduces the exact same 25/50/75%
composition (same underlying conversations), just with anonymized ids.

NOTE: this does NOT fix the labeller-style confound found earlier (scam
only from labellers 1&2, grooming from 3&4, cyberbullying only from
labeller 5) -- that confound lives in the message TEXT/writing style,
which this script never touches. It's an anonymization/hygiene step, not
a fix for that separate finding.

Usage:
    python anonymize_dataset.py
"""

import json
import secrets

import numpy as np

FILES = [
    ("dataset/train.jsonl", "dataset/train_embeddings.npz"),
    ("dataset/validation.jsonl", "dataset/validation_embeddings.npz"),
]


def new_id() -> str:
    return secrets.token_hex(6)


def anonymize_file(jsonl_path: str, embeddings_path: str):
    with open(jsonl_path) as f:
        convs = [json.loads(line) for line in f if line.strip()]

    old_embeddings = np.load(embeddings_path, allow_pickle=True)
    old_vec_by_id = dict(zip(old_embeddings["message_id"], old_embeddings["embedding"]))

    new_message_ids, new_vecs = [], []

    for conv in convs:
        new_conv_id = new_id()

        # message_id: <new_conv_id>_<1-indexed position>, same structure as before
        msg_id_map = {
            m["message_id"]: f"{new_conv_id}_{i + 1}"
            for i, m in enumerate(conv["messages"])
        }

        user_map = {}

        def map_user(old_uid):
            if old_uid is None:
                return None
            if old_uid not in user_map:
                user_map[old_uid] = new_id()
            return user_map[old_uid]

        conv["user1_id"] = map_user(conv.get("user1_id"))
        conv["user2_id"] = map_user(conv.get("user2_id"))

        for m in conv["messages"]:
            old_mid = m["message_id"]
            new_mid = msg_id_map[old_mid]

            old_vec = old_vec_by_id.get(old_mid)
            if old_vec is None:
                raise KeyError(f"no cached embedding found for message_id={old_mid!r} -- "
                                f"re-run embed.py before anonymizing")
            new_message_ids.append(new_mid)
            new_vecs.append(old_vec)

            m["message_id"] = new_mid
            m["sender_id"] = map_user(m.get("sender_id"))
            m["recipient_id"] = map_user(m.get("recipient_id"))
            if m.get("reply_to_message_id") is not None:
                m["reply_to_message_id"] = msg_id_map[m["reply_to_message_id"]]

        conv["conversation_id"] = new_conv_id

    with open(jsonl_path, "w") as f:
        for c in convs:
            f.write(json.dumps(c) + "\n")

    np.savez(embeddings_path, message_id=np.array(new_message_ids), embedding=np.array(new_vecs))

    print(f"{jsonl_path}: anonymized {len(convs)} conversations, "
          f"{len(new_message_ids)} messages; re-keyed {embeddings_path}")


def main():
    for jsonl_path, embeddings_path in FILES:
        anonymize_file(jsonl_path, embeddings_path)


if __name__ == "__main__":
    main()
