// gateway/frontend/src/components/ceoChat/strings.ts

import type { UiStrings } from "./types";

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

  // ------------------------------
  // Notion Search (generic)
  // ------------------------------
  searchNotionLabel: "Search Notion",
  chooseDatabaseLabel: "Database",
  databasePlaceholder: "Select a database…",
  loadDatabasesLabel: "Load databases",
  runSearchLabel: "Search",
  searchQueryPlaceholder: "Search text (e.g. task title)…",
  searchingLabel: "Searching…",
  noResultsLabel: "No results.",
};
