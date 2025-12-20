export type UiStrings = {
  headerTitle: string;
  headerSubtitle: string;
  inputPlaceholder: string;
  sendLabel: string;
  processingLabel: string;
  jumpToLatestLabel: string;
  blockedLabel: string;
  approvedLabel: string;
  executedLabel: string;
  openApprovalsLabel: string;
  approveLabel: string;
  retryLabel: string;
};

export const defaultStrings: UiStrings = {
  headerTitle: "CEO Console",
  headerSubtitle: "Initiator: CEO • Owner: SYSTEM • Executor: Agents (via governance)",
  inputPlaceholder: "Write a CEO command…",
  sendLabel: "Send",
  processingLabel: "SYSTEM is processing…",
  jumpToLatestLabel: "Jump to latest",
  blockedLabel: "BLOCKED",
  approvedLabel: "APPROVED",
  executedLabel: "EXECUTED",
  openApprovalsLabel: "Open approvals",
  approveLabel: "Approve",
  retryLabel: "Retry",
};
