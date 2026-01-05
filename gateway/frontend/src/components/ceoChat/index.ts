// gateway/frontend/src/components/ceoChat/index.ts

export { CeoChatbox } from "./CeoChatbox";

// UI strings type treba da dolazi iz types.ts (single source of truth)
export type { UiStrings } from "./types";

// default strings dolaze iz strings.ts
export { defaultStrings } from "./strings";

// optional: export API factory (ako ti treba vani)
export { createCeoConsoleApi } from "./api";
