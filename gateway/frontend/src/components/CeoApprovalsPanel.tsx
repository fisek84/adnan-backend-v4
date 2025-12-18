// gateway/frontend/src/components/CeoApprovalsPanel.tsx

import React, { useEffect, useState, useCallback } from "react";
import {
  fetchCeoSnapshot,
  fetchPendingApprovals,
  approveApproval,
  ApprovalsSnapshot,
  Approval,
} from "../api/aiOpsApi";

type LoadState = "idle" | "loading" | "error";

export const CeoApprovalsPanel: React.FC = () => {
  const [snapshot, setSnapshot] = useState<ApprovalsSnapshot | null>(null);
  const [pending, setPending] = useState<Approval[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoadState("loading");
      setError(null);

      const [snap, pendingRes] = await Promise.all([
        fetchCeoSnapshot(),
        fetchPendingApprovals(),
      ]);

      setSnapshot(snap);
      setPending(pendingRes.approvals ?? []);
      setLoadState("idle");
    } catch (e: any) {
      console.error(e);
      setError(e?.message ?? "Greška pri učitavanju podataka");
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleApprove = async (approval: Approval) => {
    if (!approval.approval_id) return;

    const confirmText = `Odobri izvršenje?\n\nApproval ID: ${approval.approval_id}`;
    const ok = window.confirm(confirmText);
    if (!ok) return;

    try {
      setApprovingId(approval.approval_id);
      await approveApproval(approval.approval_id, "ceo_dashboard");

      // nakon approve, ponovno učitaj snapshot + pending
      await loadData();
    } catch (e: any) {
      console.error(e);
      setError(e?.message ?? "Greška pri odobravanju");
    } finally {
      setApprovingId(null);
    }
  };

  const renderHeader = () => (
    <div className="flex items-center justify-between mb-4">
      <div>
        <h2 className="text-xl font-semibold">Approvals &amp; pipeline</h2>
        {snapshot && (
          <p className="text-sm text-gray-500">
            {snapshot.system.name} · v{snapshot.system.version} ·{" "}
            {snapshot.system.release_channel}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={loadData}
        className="px-3 py-1 text-sm border rounded-md hover:bg-gray-50 disabled:opacity-50"
        disabled={loadState === "loading"}
      >
        {loadState === "loading" ? "Osvježavam..." : "Osvježi"}
      </button>
    </div>
  );

  const renderStats = () => {
    if (!snapshot) return null;

    const a = snapshot.approvals;

    const statBox = (label: string, value: number, extraClass?: string) => (
      <div
        className={`flex flex-col rounded-lg border px-3 py-2 text-sm ${extraClass ?? ""}`}
      >
        <span className="text-gray-500">{label}</span>
        <span className="mt-1 text-lg font-semibold">{value}</span>
      </div>
    );

    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {statBox("Total approvals", a.total)}
        {statBox("Pending", a.pending_count, "border-amber-400")}
        {statBox("Approved", a.approved_count, "border-emerald-500")}
        {statBox("Rejected", a.rejected_count, "border-rose-500")}
        {statBox("Failed", a.failed_count, "border-red-600")}
      </div>
    );
  };

  const renderPendingList = () => {
    if (pending.length === 0) {
      return (
        <div className="rounded-lg border border-dashed p-4 text-sm text-gray-500">
          Trenutno nema pending approvals.
        </div>
      );
    }

    return (
      <div className="space-y-2">
        {pending.map((appr) => {
          const cmd = appr.command ?? {};
          const meta = cmd.metadata ?? {};
          const createdAt = appr.created_at || meta.created_at;

          const createdLabel = createdAt
            ? new Date(createdAt).toLocaleString()
            : "n/a";

          const title =
            meta.title ||
            meta.summary ||
            cmd.intent ||
            cmd.command ||
            "AICommand";

          return (
            <div
              key={appr.approval_id}
              className="flex flex-col md:flex-row md:items-center md:justify-between border rounded-lg px-3 py-2 text-sm bg-white"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                    Pending
                  </span>
                  <span className="font-medium truncate">{title}</span>
                </div>
                <div className="mt-1 text-xs text-gray-500 space-x-2">
                  <span>ID: {appr.approval_id}</span>
                  <span>Exec: {appr.execution_id}</span>
                  <span>Created: {createdLabel}</span>
                </div>
              </div>
              <div className="mt-2 md:mt-0 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleApprove(appr)}
                  className="px-3 py-1 text-xs md:text-sm rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60"
                  disabled={approvingId === appr.approval_id}
                >
                  {approvingId === appr.approval_id
                    ? "Odobravam..."
                    : "Odobri"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <section className="rounded-xl border bg-gray-50 p-4 md:p-5 shadow-sm">
      {renderHeader()}

      {error && (
        <div className="mb-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {renderStats()}

      <h3 className="mt-2 mb-2 text-sm font-semibold text-gray-700">
        Pending approvals
      </h3>

      {renderPendingList()}
    </section>
  );
};
