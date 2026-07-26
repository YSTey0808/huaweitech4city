"""
Single-conversation message graph -> GraphSAGE -> one conversation-level
binary prediction (harmful/safe), matching the canonical
`binary_conversation_label` schema field.

Nodes are individual messages (their embeddings, unmodified). Three directed
relation types connect them, all pointing from an earlier message to a later
one, never the reverse:
    temporal      message i -> message i+1                (conversation order)
    same_speaker  message j -> message i, for message i's  (turn-taking /
                  last SAME_SPEAKER_WINDOW prior messages   escalation pattern)
                  from the same sender
    reply_to      parent message -> reply                 (explicit threading,
                                                             from reply_to_message_id)

Edges are directed on purpose, not a modeling nicety: with bidirectional
edges, appending one new node could change the computed embedding of every
node within 2 hops of it (they'd have a new neighbor), forcing a full
graph recompute on every incoming message. With forward-only edges, a
node's embedding depends only on nodes that already existed when it
arrived, so once computed it is never invalidated by anything appended
afterward. That property is what makes ConversationGraphState's incremental
path both correct and cheap -- see its docstring below.

Two ways to drive the same trained MessageGraphSAGE weights:
    build_message_graph() + model.forward_full()   -- cold-start / batch:
        score a conversation whose full message list is already known
        (backfill, offline eval).
    ConversationGraphState + state.add_message()    -- live / production:
        extend the graph one message at a time as they actually arrive,
        without ever revisiting earlier messages.
Both paths share one set of weights -- no train/serve skew.
"""

from collections import deque

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.data import HeteroData
from torch_geometric.nn import HeteroConv, SAGEConv

from .config import EMBED_DIM, HIDDEN_DIM, SAME_SPEAKER_WINDOW, DROPOUT

_RELATIONS = ("temporal", "same_speaker", "reply_to")


def build_message_graph(messages: list) -> HeteroData:
    """
    messages: list of dicts, chronological order, each with:
        message_id            str
        sender_id              str
        embedding               FloatTensor [EMBED_DIM]
        reply_to_message_id    str | None

    Builds the full conversation graph in one shot (the cold-start/batch
    path). same_speaker edges are capped to each message's last
    SAME_SPEAKER_WINDOW same-sender predecessors, matching the cap used by
    ConversationGraphState's incremental path, so the two paths agree.

    Empty-relation handling uses zero-size edge_index tensors (shape
    [2, 0]) -- this is what makes a 1-message conversation (zero possible
    edges of any relation) safe: HeteroConv still calls each relation's
    SAGEConv with 0 edges, which falls back to its self/root transform only.
    """
    n = len(messages)
    assert n >= 1, "a conversation must have at least one message"

    data = HeteroData()
    data['message'].x = torch.stack([m["embedding"] for m in messages])

    id_to_idx = {m["message_id"]: i for i, m in enumerate(messages)}

    # temporal: i -> i+1
    if n > 1:
        src = torch.arange(n - 1, dtype=torch.long)
        temporal_edge_index = torch.stack([src, src + 1], dim=0)
    else:
        temporal_edge_index = torch.zeros((2, 0), dtype=torch.long)
    data['message', 'temporal', 'message'].edge_index = temporal_edge_index

    # same_speaker: message i links FROM its last SAME_SPEAKER_WINDOW same-sender predecessors
    src2, dst2 = [], []
    recent_by_sender = {}
    for i, m in enumerate(messages):
        history = recent_by_sender.setdefault(m["sender_id"], deque(maxlen=SAME_SPEAKER_WINDOW))
        for j in history:
            src2.append(j)
            dst2.append(i)
        history.append(i)
    same_speaker_edge_index = (
        torch.tensor([src2, dst2], dtype=torch.long) if src2
        else torch.zeros((2, 0), dtype=torch.long)
    )
    data['message', 'same_speaker', 'message'].edge_index = same_speaker_edge_index

    # reply_to: parent -> reply
    src3, dst3 = [], []
    for i, m in enumerate(messages):
        parent_id = m.get("reply_to_message_id")
        if parent_id is not None and parent_id in id_to_idx:
            src3.append(id_to_idx[parent_id])
            dst3.append(i)
    reply_to_edge_index = (
        torch.tensor([src3, dst3], dtype=torch.long) if src3
        else torch.zeros((2, 0), dtype=torch.long)
    )
    data['message', 'reply_to', 'message'].edge_index = reply_to_edge_index

    return data


class MessageGraphSAGE(nn.Module):
    """
    conv_head is a single bare nn.Linear(hidden_dim, 1) -- NOT a 2-layer
    MLP. This is load-bearing, not a style choice: because pooling is a
    plain arithmetic mean and Linear is affine,
        conv_head(mean_i(h_i)) == mean_i(conv_head(h_i))    (exact equality,
    since mean distributes over an affine map). So the SAME conv_head
    weights, applied to individual node embeddings BEFORE pooling, yield a
    per-message logit that is an exact additive decomposition of the
    conversation-level logit -- a principled per-message "contribution to
    the verdict" evidence score with zero extra trained parameters. It also
    makes ConversationGraphState's running-sum pooling an O(1) update
    instead of an O(n) re-sum. If conv_head ever grows a hidden layer plus a
    nonlinearity, this identity breaks (ReLU doesn't commute with
    averaging) -- keep it a bare Linear.

    Per-message scores derived this way are a ranking/"contribution to the
    verdict" signal, not an independently-calibrated probability that that
    message alone is harmful -- treat them as a score, not a probability.

    Regularization: dropout is applied after input_proj and after each
    GraphSAGE layer's ReLU, in both forward_full and the incremental path
    (ConversationGraphState.add_message) -- same nn.Dropout module
    instance either way, so it's governed by the same .training flag and
    behaves identically (a no-op) once model.eval() is set, which is the
    only mode ConversationGraphState is ever driven in. Added specifically
    to counter memorization on a small (~800-conversation) dataset with a
    ~1M-parameter model -- see docs/pipeline.md's Known Limitations.
    """

    def __init__(self, embed_dim=EMBED_DIM, hidden_dim=HIDDEN_DIM, num_layers=2, dropout=DROPOUT):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.input_proj = nn.Linear(embed_dim, hidden_dim)
        self.dropout = nn.Dropout(dropout)

        self.layers = nn.ModuleList()
        for _ in range(num_layers):
            self.layers.append(HeteroConv({
                ('message', rel, 'message'): SAGEConv((-1, -1), hidden_dim)
                for rel in _RELATIONS
            }, aggr='mean'))

        self.conv_head = nn.Linear(hidden_dim, 1)   # bare Linear -- see class docstring

    def forward_full(self, data: HeteroData):
        """
        Cold-start / batch path: score a conversation whose full message
        list is already known. Builds every node's embedding in one shot
        via full-graph message passing.

        Returns:
            conv_score: FloatTensor [1] -- sigmoid P(harmful) for the whole
                conversation.
            per_message_scores: FloatTensor [seq_len] -- sigmoid of each
                message's additive contribution to the conv logit above.
        """
        x_dict = {'message': self.dropout(self.input_proj(data.x_dict['message']))}

        for layer in self.layers:
            x_dict = layer(x_dict, data.edge_index_dict)
            x_dict = {k: self.dropout(F.relu(v)) for k, v in x_dict.items()}

        node_embeddings = x_dict['message']              # [seq_len, hidden_dim]
        conv_embedding = node_embeddings.mean(dim=0)       # [hidden_dim]

        conv_score = torch.sigmoid(self.conv_head(conv_embedding))
        per_message_scores = torch.sigmoid(self.conv_head(node_embeddings).squeeze(-1))

        return conv_score, per_message_scores

    def _incremental_step(self, hetero_conv_layer, own_feat, neighbor_features, relation_neighbors):
        """
        Runs ONE HeteroConv layer (already-trained weights) for a single new
        node against an explicit, small set of causal neighbors, instead of
        the whole graph -- the mechanism behind ConversationGraphState's
        incremental path. Reuses HeteroConv/SAGEConv's own forward()
        unmodified by constructing a tiny local subgraph: local index 0 is
        always the new node, and each relation's edge_index references the
        shared local indices assigned to its causal neighbors. Because
        GraphSAGE's mean aggregation over a node's neighbor set depends only
        on that neighbor set (not on the size of the rest of the graph), the
        result for local index 0 is identical to what a full-graph forward
        pass would produce for that node -- this is the property the
        incremental path relies on for correctness.

        own_feat: Tensor[hidden_dim] -- the new node's feature at this
            layer's input (layer0 for the first GraphSAGE layer, the first
            layer's output for the second).
        neighbor_features: dict[global_idx -> Tensor[hidden_dim]] -- this
            layer's cached feature for every distinct neighbor referenced by
            any relation below.
        relation_neighbors: dict[relation_name -> list[global_idx]] -- which
            of those neighbors participate in which relation.
        """
        all_neighbors = list(neighbor_features.keys())
        local_idx = {g: i + 1 for i, g in enumerate(all_neighbors)}  # 0 = the new node
        local_x = torch.stack([own_feat] + [neighbor_features[g] for g in all_neighbors], dim=0)

        edge_index_dict = {}
        for rel in _RELATIONS:
            gidxs = relation_neighbors.get(rel, [])
            if gidxs:
                src = torch.tensor([local_idx[g] for g in gidxs], dtype=torch.long)
                dst = torch.zeros(len(gidxs), dtype=torch.long)
            else:
                src = torch.zeros((0,), dtype=torch.long)
                dst = torch.zeros((0,), dtype=torch.long)
            edge_index_dict[('message', rel, 'message')] = torch.stack([src, dst], dim=0)

        out_dict = hetero_conv_layer({'message': local_x}, edge_index_dict)
        return F.relu(out_dict['message'][0])


class ConversationGraphState:
    """
    Per-conversation incremental state for the live/production path.

    Invariant this all depends on: every relation's edges point only from
    an earlier message to a later one (see module docstring), so a cached
    hidden state, once written for message i, is never invalidated by
    anything appended after message i. That means add_message() only ever
    needs to compute state for the *new* message -- every earlier message's
    cached state is read, never recomputed.

    Caches, per message index i:
        layer0[i]        MessageGraphSAGE.input_proj(embedding_i)
        layer_states[k][i]   output of GraphSAGE layer k for message i (post-ReLU)
    plus a running sum of the final layer's embeddings, so the pooled
    conversation embedding (and thus conv_score) is an O(1) update per
    message instead of an O(n) re-sum over the whole conversation.
    """

    def __init__(self, model: MessageGraphSAGE):
        self.model = model
        self.message_ids = []
        self.layer0 = []
        self.layer_states = [[] for _ in range(len(model.layers))]
        self.message_scores = []
        self._id_to_idx = {}
        self._sender_history = {}
        self._running_sum = None
        self.n = 0

    @torch.no_grad()
    def add_message(self, message_id, sender_id, embedding, reply_to_message_id=None):
        """
        embedding: FloatTensor [EMBED_DIM] for the new message.
        Returns (conv_score: float, message_score: float) -- both updated
        for the conversation as of this message.
        """
        idx = self.n

        temporal_neighbors = [idx - 1] if idx > 0 else []
        same_speaker_neighbors = list(self._sender_history.get(sender_id, ()))
        reply_to_neighbors = []
        if reply_to_message_id is not None and reply_to_message_id in self._id_to_idx:
            reply_to_neighbors = [self._id_to_idx[reply_to_message_id]]

        relation_neighbors = {
            'temporal': temporal_neighbors,
            'same_speaker': same_speaker_neighbors,
            'reply_to': reply_to_neighbors,
        }
        all_neighbor_idxs = set(temporal_neighbors) | set(same_speaker_neighbors) | set(reply_to_neighbors)

        h = self.model.dropout(self.model.input_proj(embedding))
        self.layer0.append(h)

        for layer_i, hetero_conv_layer in enumerate(self.model.layers):
            source_cache = self.layer0 if layer_i == 0 else self.layer_states[layer_i - 1]
            neighbor_features = {g: source_cache[g] for g in all_neighbor_idxs}
            h = self.model.dropout(self.model._incremental_step(hetero_conv_layer, h, neighbor_features, relation_neighbors))
            self.layer_states[layer_i].append(h)

        final_embedding = h
        message_score = torch.sigmoid(self.model.conv_head(final_embedding)).item()

        self._running_sum = final_embedding if self._running_sum is None else self._running_sum + final_embedding
        self.n += 1
        conv_embedding = self._running_sum / self.n
        conv_score = torch.sigmoid(self.model.conv_head(conv_embedding)).item()

        self.message_ids.append(message_id)
        self._id_to_idx[message_id] = idx
        self.message_scores.append(message_score)
        history = self._sender_history.setdefault(sender_id, deque(maxlen=SAME_SPEAKER_WINDOW))
        history.append(idx)

        return conv_score, message_score
