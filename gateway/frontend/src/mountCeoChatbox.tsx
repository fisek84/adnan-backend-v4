import React from "react";
import { createRoot } from "react-dom/client";
import { CeoChatbox } from "./components/ceoChat/CeoChatbox";

type MountOptions = {
  container: HTMLElement;
  ceoCommandUrl: string;
  approveUrl?: string;
  headers?: Record<string, string>;
};

export const mountCeoChatbox = (opts: MountOptions) => {
  const root = createRoot(opts.container);
  root.render(
    <CeoChatbox
      ceoCommandUrl={opts.ceoCommandUrl}
      approveUrl={opts.approveUrl}
      headers={opts.headers}
    />
  );
  return () => root.unmount();
};
