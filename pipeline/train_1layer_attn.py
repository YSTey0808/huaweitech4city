"""
One-off comparison: does a 1-layer, attention-based (GATv2Conv) variant of
the message graph model do better or worse than the production 2-layer
SAGEConv MessageGraphSAGE, trained on the same new dataset?

Experimental only -- MessageGraphAttn1Layer here is NOT part of
gnn/conversation_gnn.py and backend/ never loads it. There is no surviving
source for the original message_graph_sage_1layer_attn.pt checkpoint (it
predates this repo's current code, and nothing here references it) -- this
is a fresh, reasonable reconstruction of "1 layer + attention," not a
reproduction of that exact architecture.

Reuses train.py's data loading and eval helpers unmodified -- train_epoch/
evaluate/predict_all/print_validation_report are written against any model
with a .forward_full(graph) method, so only the model class and the
training-loop wrapper (train.py's train_model() hardcodes MessageGraphSAGE)
are new here.

Usage (run with pipeline/ as the working directory):
    cd pipeline
    python train_1layer_attn.py \\
        --train-jsonl dataset/train_new.jsonl --train-embeddings dataset/train_new_embeddings.npz \\
        --val-jsonl dataset/validation_new.jsonl --val-embeddings dataset/validation_new_embeddings.npz
"""

import argparse
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import AdamW
from torch_geometric.nn import HeteroConv, GATv2Conv

sys.path.insert(0, str(Path(__file__).resolve().parent))  # pipeline/ -- so train/gnn resolve as siblings

from train import load_conversations, load_embeddings, prepare_example, train_epoch, evaluate, print_validation_report  # noqa: E402
from gnn.config import EMBED_DIM, HIDDEN_DIM, DROPOUT  # noqa: E402

_RELATIONS = ("temporal", "same_speaker", "reply_to")  # matches build_message_graph()'s edge types


class MessageGraphAttn1Layer(nn.Module):
    """
    1-layer GATv2 variant for comparison against the production
    MessageGraphSAGE (2-layer SAGEConv, see gnn/conversation_gnn.py).
    conv_head stays a bare Linear so the same per-message
    contribution-score identity used throughout the pipeline still holds
    (conv_head(mean(h)) == mean(conv_head(h)) -- see MessageGraphSAGE's
    docstring for why that matters).

    add_self_loops=True (unlike this repo's SAGEConv usage, which relies on
    explicit zero-edge handling instead): GATv2Conv's attention is
    undefined over an empty neighbor set with no self-loop, so a
    first-message node (zero real in-edges by the directed-graph design)
    needs the self-loop to produce a defined output at all.
    """

    def __init__(self, embed_dim=EMBED_DIM, hidden_dim=HIDDEN_DIM, dropout=DROPOUT, heads=4):
        super().__init__()
        assert hidden_dim % heads == 0, "hidden_dim must be divisible by heads"
        self.input_proj = nn.Linear(embed_dim, hidden_dim)
        self.dropout = nn.Dropout(dropout)
        self.layer = HeteroConv({
            ('message', rel, 'message'): GATv2Conv((-1, -1), hidden_dim // heads, heads=heads, add_self_loops=True)
            for rel in _RELATIONS
        }, aggr='mean')
        self.conv_head = nn.Linear(hidden_dim, 1)

    def forward_full(self, data):
        x_dict = {'message': self.dropout(self.input_proj(data.x_dict['message']))}
        x_dict = self.layer(x_dict, data.edge_index_dict)
        x_dict = {k: self.dropout(F.relu(v)) for k, v in x_dict.items()}

        node_embeddings = x_dict['message']
        conv_embedding = node_embeddings.mean(dim=0)

        conv_score = torch.sigmoid(self.conv_head(conv_embedding))
        per_message_scores = torch.sigmoid(self.conv_head(node_embeddings).squeeze(-1))
        return conv_score, per_message_scores


def train_attn_model(train_examples, val_examples, epochs, lr, pos_weight, checkpoint_path, weight_decay):
    model = MessageGraphAttn1Layer()
    optimizer = AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    checkpoint_path = Path(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    best_val_f1 = -1.0
    for epoch in range(1, epochs + 1):
        train_loss = train_epoch(model, train_examples, optimizer, pos_weight)
        val_f1 = evaluate(model, val_examples)
        marker = ""
        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            torch.save(model.state_dict(), checkpoint_path)
            marker = "  <- new best, saved"
        print(f"epoch {epoch:3d}  train_loss={train_loss:.4f}  val_macro_f1={val_f1:.4f}{marker}")

    print(f"\nLoading best checkpoint (val_macro_f1={best_val_f1:.4f})...")
    model.load_state_dict(torch.load(checkpoint_path))
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-jsonl", default="dataset/train_new.jsonl")
    parser.add_argument("--val-jsonl", default="dataset/validation_new.jsonl")
    parser.add_argument("--train-embeddings", required=True)
    parser.add_argument("--val-embeddings", required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--pos-weight", type=float, default=1.0)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--checkpoint", default="experiments/checkpoints/message_graph_attn_1layer_new.pt")
    args = parser.parse_args()

    print("Loading conversations and embeddings...")
    train_examples = [
        prepare_example(c, load_embeddings(args.train_embeddings))
        for c in load_conversations(args.train_jsonl)
    ]
    val_examples = [
        prepare_example(c, load_embeddings(args.val_embeddings))
        for c in load_conversations(args.val_jsonl)
    ]
    print(f"  train={len(train_examples)} conversations, val={len(val_examples)} conversations\n")

    model = train_attn_model(
        train_examples, val_examples, args.epochs, args.lr, args.pos_weight, args.checkpoint, args.weight_decay,
    )
    print_validation_report(model, val_examples)


if __name__ == "__main__":
    main()
