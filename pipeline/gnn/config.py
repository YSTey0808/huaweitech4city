"""
Shared constants. EMBED_DIM is the one you must change to match whatever
sentence-embedding model you plug in upstream (e.g. LaBSE=768,
multilingual-e5-base=768, paraphrase-multilingual-MiniLM-L12-v2=384).
Everything downstream (the message graph's input projection) reads from this
constant, so changing it here is enough to re-fit the whole pipeline to your
embeddings.
"""

EMBED_DIM = 1024         # aisingapore/SEA-LION-ModernBERT-Embedding-600M (see embed.py's
                          # DEFAULT_MODEL) -- CHANGE ME (and embed.py's DEFAULT_MODEL) together
                          # if you swap encoders, they must always agree
HIDDEN_DIM = 256         # GraphSAGE hidden size (independent of EMBED_DIM)

SAME_SPEAKER_WINDOW = 5  # a message links to at most this many of its sender's
                          # most recent prior messages — bounds per-message cost
                          # in the incremental path regardless of conversation length

DROPOUT = 0.3            # applied after input_proj and after each GraphSAGE layer's
                          # ReLU (MessageGraphSAGE) -- a no-op at inference (model.eval()),
                          # only active during train_model()'s training loop

CONV_LABELS = ["safe", "harmful"]  # binary vocabulary, matches the canonical
                                    # `binary_conversation_label` schema field exactly

TOP_K_EVIDENCE = 3       # max messages the LLM is asked to CITE as evidence in its response.
                          # Not a filter on what it sees -- it sees every message in the
                          # scoring window (see gnn/llm_stage.py) and judges from there;
                          # this only bounds how many it names back in top_evidence_messages.

SKIP_LLM_BELOW = 0.05    # automatic scoring skips the LLM call entirely when the GNN's
                          # conv_score is below this -- a "safe" verdict writes no rows
                          # anyway (absence = safe), so nothing is lost, and the LLM cost
                          # per obviously-benign message drops to zero. NEVER applied when
                          # a user report is present (inference.score_conversation): a
                          # report exists precisely to challenge a low score.

LLM_MODEL = "claude-haiku-4-5-20251001"  # small/fast model — reasoning over a handful of pre-scored messages, not raw generation
