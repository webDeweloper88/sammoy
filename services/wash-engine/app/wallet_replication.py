"""Synchronous two-node journal protocol; no fallback on an ambiguous response."""
from dataclasses import dataclass
from typing import Callable
from .wallet_domain import WalletConflict, WalletPolicy


class WalletUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Authority:
    site_id: str
    local_post: int
    primary_post: int
    standby_post: int
    generation: int = 1
    single_node: bool = False

    def __post_init__(self):
        if not self.site_id or self.primary_post == self.standby_post or self.generation < 1:
            raise WalletConflict("Invalid wallet authority")
        if any(type(p) is not int or not 1 <= p <= 100 for p in (self.local_post,self.primary_post,self.standby_post)):
            raise WalletConflict("Invalid post number")

    def envelope(self, payload):
        return {"site_id": self.site_id, "generation": self.generation,
                "primary_post": self.primary_post, "sender_post": self.local_post, "payload": payload}

    def require_primary(self):
        if self.local_post != self.primary_post:
            raise WalletUnavailable("This post is not the wallet primary")

    def require_replica_sender(self, envelope):
        if self.local_post != self.standby_post:
            raise WalletConflict("This post is not the standby")
        if any(envelope.get(k) != v for k,v in (("site_id",self.site_id),
                ("generation",self.generation),("primary_post",self.primary_post),("sender_post",self.primary_post))):
            raise WalletConflict("Stale or foreign wallet authority")


class ReplicaReceiver:
    def __init__(self, store, authority):
        self.store, self.authority = store, authority

    def stage(self, envelope):
        self.authority.require_replica_sender(envelope)
        return self.store.receive_replica(envelope["payload"])

    def commit(self, envelope):
        self.authority.require_replica_sender(envelope)
        return self.store.commit_prepared(envelope["payload"]["operation_id"])


class ReplicatedWallet:
    def __init__(self, store, authority: Authority, stage: Callable, commit: Callable):
        self.store, self.authority = store, authority
        self.remote_stage, self.remote_commit = stage, commit

    def execute(self, operation_id, uid, command, policy: WalletPolicy):
        self.authority.require_primary()
        # An uncertain operation blocks its card, not unrelated customers or
        # currency operations when a reporting/configuration replica is delayed.
        # Store.prepare enforces per-card revision order and operation-ID reuse.
        receipt = self.store.prepare(operation_id, uid, command, policy)
        if not self.authority.single_node:
            payload = self.store.export_operation(operation_id)
            ack = self.remote_stage(self.authority.envelope(payload))
            if ack.get('operation_id') != operation_id or ack.get('status') not in {'prepared','committed'}:
                raise WalletUnavailable("Standby did not confirm durable receipt")
            ack = self.remote_commit(self.authority.envelope({'operation_id':operation_id}))
            if ack.get('operation_id') != operation_id or ack.get('status') != 'committed':
                raise WalletUnavailable("Standby did not confirm commit")
        # After this commit, acknowledged transfers exist on both nodes. A
        # dropped reply is resolved using the same operation ID, not a new load.
        return self.store.commit_prepared(operation_id)

    def catch_up(self, remote_summaries=None):
        self.authority.require_primary()
        if self.authority.single_node:
            raise WalletUnavailable("Re-enable replication only after standby catch-up")
        count = 0
        for rows in self.store.history_pages():
            known=remote_summaries([r['operation_id'] for r in rows]) if remote_summaries else {}
            for row in rows:
                operation_id=row['operation_id']
                payload=self.store.export_operation(operation_id)
                existing=known.get(operation_id)
                if existing and existing['digest']!=self.store.operation_digest(payload):
                    raise WalletConflict('Standby operation differs from the primary journal')
                if not existing or existing['status']!='committed':
                    ack=self.remote_stage(self.authority.envelope(payload))
                    if ack.get('operation_id')!=operation_id or ack.get('status') not in {'prepared','committed'}:
                        raise WalletUnavailable('Standby catch-up stage not acknowledged')
                    ack=self.remote_commit(self.authority.envelope({'operation_id':operation_id}))
                    if ack.get('operation_id')!=operation_id or ack.get('status')!='committed':
                        raise WalletUnavailable('Standby catch-up commit not acknowledged')
                self.store.commit_prepared(operation_id)
                count += 1
        return count



def promotion_plan(authority: Authority, *, old_primary_fenced: bool,
                   single_node_confirmed: bool) -> Authority:
    """Manual promotion only. Physical fencing is an operator responsibility.

    No timeout/heartbeat can substitute for fencing. A recovered old primary
    must receive the new generation/config before participating again.
    """
    if authority.local_post != authority.standby_post:
        raise WalletConflict("Only the configured standby can be promoted")
    if not old_primary_fenced or not single_node_confirmed:
        raise WalletConflict("Old primary fencing and single-copy operation confirmation required")
    return Authority(authority.site_id,authority.local_post,authority.standby_post,
                     authority.primary_post,authority.generation+1,True)
