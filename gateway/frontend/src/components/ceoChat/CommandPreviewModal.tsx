// gateway/frontend/src/components/ceoChat/CommandPreviewModal.tsx
import React, { useEffect, useMemo, useState } from "react";

type Props = {
  open: boolean;
  title?: string;
  loading?: boolean;
  error?: string | null;
  data?: any;
  onApplyPatch?: (patch: Record<string, any>) => void;
  onClose: () => void;
};

function clampJson(obj: any, maxLen = 16000): string {
  let s = "";
  try {
    s = JSON.stringify(obj ?? {}, null, 2);
  } catch {
    s = String(obj ?? "");
  }
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "\n...(truncated)...";
}

export const CommandPreviewModal: React.FC<Props> = ({
  open,
  title,
  loading,
  error,
  data,
  onApplyPatch,
  onClose,
}) => {
  const header = (title || "Preview") as string;

  const notion = data?.notion;
  const command = data?.command;
  const notionRows: any[] | null = Array.isArray((notion as any)?.rows)
    ? ((notion as any).rows as any[])
    : null;
  const isBatchPreview = Boolean(notionRows && notionRows.length > 0);

  const [showRaw, setShowRaw] = useState(false);
  const [showAllFields, setShowAllFields] = useState(false);
  const [patchLocal, setPatchLocal] = useState<Record<string, string>>({});

  // Batch composer (single approval, multiple ops)
  const [batchOps, setBatchOps] = useState<any[] | null>(null);
  const [newItemKind, setNewItemKind] = useState<
    "create_task" | "create_goal" | "create_project" | "create_page"
  >("create_task");
  const [newItemDbKey, setNewItemDbKey] = useState<string>("");
  const [newItemGoalOpId, setNewItemGoalOpId] = useState<string>("");
  const [newItemProjectOpId, setNewItemProjectOpId] = useState<string>("");
  const [newItemParentGoalOpId, setNewItemParentGoalOpId] =
    useState<string>("");
  const [newItemTitle, setNewItemTitle] = useState<string>("");
  const [newItemDescription, setNewItemDescription] = useState<string>("");
  const [newItemStatus, setNewItemStatus] = useState<string>("");
  const [newItemPriority, setNewItemPriority] = useState<string>("");
  const [newItemDueDate, setNewItemDueDate] = useState<string>("");

  useEffect(() => {
    if (!open) return;
    setPatchLocal({});
    setShowAllFields(false);
    setBatchOps(null);
    setNewItemKind("create_task");
    setNewItemDbKey("");
    setNewItemGoalOpId("");
    setNewItemProjectOpId("");
    setNewItemParentGoalOpId("");
    setNewItemTitle("");
    setNewItemDescription("");
    setNewItemStatus("");
    setNewItemPriority("");
    setNewItemDueDate("");
  }, [open, data]);

  const propertiesPreview: Record<string, any> | null =
    notion &&
    typeof notion === "object" &&
    (notion as any).properties_preview &&
    typeof (notion as any).properties_preview === "object"
      ? Object.keys((notion as any).properties_preview as Record<string, any>)
          .length
        ? ((notion as any).properties_preview as Record<string, any>)
        : null
      : null;

  const validation: any =
    notion && typeof notion === "object" ? (notion as any).validation : null;
  const validationIssues: any[] = Array.isArray(validation?.issues)
    ? validation.issues
    : [];
  const validationSummary =
    validation?.summary && typeof validation.summary === "object"
      ? validation.summary
      : null;
  const validationMode =
    typeof validation?.mode === "string" ? validation.mode : "warn";

  const propertySpecs: Record<string, any> | null =
    notion &&
    typeof notion === "object" &&
    (notion as any).property_specs &&
    typeof (notion as any).property_specs === "object"
      ? Object.keys((notion as any).property_specs as Record<string, any>)
          .length
        ? ((notion as any).property_specs as Record<string, any>)
        : null
      : null;

  const review =
    data?.review && typeof data.review === "object" ? data.review : null;
  const reviewSchema: Record<string, any> | null =
    review?.fields_schema && typeof review.fields_schema === "object"
      ? (review.fields_schema as Record<string, any>)
      : null;
  const reviewSchemaByDb: Record<string, any> | null =
    review?.fields_schema_by_db_key &&
    typeof review.fields_schema_by_db_key === "object"
      ? (review.fields_schema_by_db_key as Record<string, any>)
      : null;
  const effectiveReviewSchema = useMemo(() => {
    if (reviewSchema && Object.keys(reviewSchema).length) return reviewSchema;
    if (!reviewSchemaByDb) return null;
    const union: Record<string, any> = {};
    for (const v of Object.values(reviewSchemaByDb)) {
      if (!v || typeof v !== "object") continue;
      for (const [k, val] of Object.entries(v as Record<string, any>)) {
        if (!(k in union)) union[k] = val;
      }
    }
    return Object.keys(union).length ? union : null;
  }, [reviewSchema, reviewSchemaByDb]);
  const reviewMissing: string[] = Array.isArray(review?.missing_fields)
    ? (review.missing_fields as any[]).filter((x) => typeof x === "string")
    : [];

  const editableTypes = new Set([
    "title",
    "rich_text",
    "select",
    "status",
    "date",
    "number",
    "checkbox",
    "multi_select",
    "people",
  ]);

  // Backend applies schema-backed patches at execution time; keep UI conservative for types needing IDs.
  const supportedPatchFields = useMemo(() => {
    const schema = effectiveReviewSchema || {};
    const keys = Object.keys(schema).filter((k) => {
      const t = (schema as any)?.[k]?.type;
      return typeof t === "string" && editableTypes.has(t);
    });

    // Prefer common enterprise fields near the top.
    const preferredOrder = [
      "Name",
      "Title",
      "Status",
      "Priority",
      "Deadline",
      "Due Date",
      "Description",
    ];
    const preferred = preferredOrder.filter((k) => keys.includes(k));
    const rest = keys.filter((k) => !preferred.includes(k)).sort();
    return [...preferred, ...rest];
  }, [effectiveReviewSchema]);

  const editableFields = useMemo(() => {
    const schemaKeys = Object.keys(effectiveReviewSchema || {}).filter((k) =>
      supportedPatchFields.includes(k),
    );
    if (!schemaKeys.length) return [];

    const preferred = supportedPatchFields.filter((k) =>
      schemaKeys.includes(k),
    );
    const base = reviewMissing.filter((k) => schemaKeys.includes(k));
    const picked = base.length ? base : preferred;
    return showAllFields ? schemaKeys : picked.length ? picked : schemaKeys;
  }, [effectiveReviewSchema, reviewMissing, showAllFields]);

  function fieldOptions(fieldKey: string): string[] {
    const fs: any = (effectiveReviewSchema as any)?.[fieldKey] ?? {};
    const opts = Array.isArray(fs?.options)
      ? fs.options.filter((x: any) => typeof x === "string")
      : [];
    return opts;
  }

  function currentValueForField(fieldKey: string): string {
    if (typeof patchLocal?.[fieldKey] === "string") return patchLocal[fieldKey];
    if (propertiesPreview) {
      const pv = propertiesPreview[fieldKey];
      if (pv?.select?.name) return String(pv.select.name);
      if (pv?.status?.name) return String(pv.status.name);
      if (pv?.date?.start) return String(pv.date.start);
      if (typeof pv?.number === "number") return String(pv.number);
      if (typeof pv?.checkbox === "boolean")
        return pv.checkbox ? "true" : "false";
      if (Array.isArray(pv?.multi_select)) {
        const names = pv.multi_select
          .map((o: any) => (o && typeof o === "object" ? o.name : null))
          .filter((x: any) => typeof x === "string" && x.trim());
        if (names.length) return names.join(", ");
      }
      if (Array.isArray(pv?.people)) {
        const names = pv.people
          .map((o: any) =>
            o && typeof o === "object" ? o.name || o.email : null,
          )
          .filter((x: any) => typeof x === "string" && x.trim());
        if (names.length) return names.join(", ");
      }
      if (Array.isArray(pv?.title)) return renderNotionValue(pv);
      if (Array.isArray(pv?.rich_text)) return renderNotionValue(pv);
    }
    if (propertySpecs) {
      const sp = propertySpecs[fieldKey];
      if (sp?.name) return String(sp.name);
      if (sp?.start) return String(sp.start);
      if (sp?.text) return String(sp.text);
      if (typeof sp?.number === "number") return String(sp.number);
      if (typeof sp?.checkbox === "boolean")
        return sp.checkbox ? "true" : "false";
      if (Array.isArray(sp?.names)) {
        const names = (sp.names as any[]).filter(
          (x) => typeof x === "string" && x.trim(),
        );
        if (names.length) return names.join(", ");
      }
    }
    return "";
  }

  const columns = useMemo(() => {
    // Batch preview columns: union of per-row columns.
    if (notionRows && notionRows.length > 0) {
      const colSet = new Set<string>();
      colSet.add("op_id");
      colSet.add("intent");
      colSet.add("db_key");

      for (const r of notionRows) {
        const pp0 =
          r?.properties_preview && typeof r.properties_preview === "object"
            ? (r.properties_preview as any)
            : null;
        const ps0 =
          r?.property_specs && typeof r.property_specs === "object"
            ? (r.property_specs as any)
            : null;
        const pp = pp0 && Object.keys(pp0).length ? pp0 : null;
        const ps = ps0 && Object.keys(ps0).length ? ps0 : null;
        const src = pp || ps || {};
        for (const k of Object.keys(src)) colSet.add(k);
      }

      // If backend provided schema-only (no values yet), still show full table.
      for (const k of Object.keys(effectiveReviewSchema || {})) colSet.add(k);

      const keys = Array.from(colSet);
      const preferred = [
        "op_id",
        "intent",
        "db_key",
        "Goal Ref",
        "Project Ref",
        "Parent Goal Ref",
        "Name",
        "Title",
        "Status",
        "Priority",
        "Owner",
        "Deadline",
        "Due Date",
        "Project",
        "Goal",
        "Description",
      ];
      const ordered: string[] = [];
      for (const p of preferred) if (keys.includes(p)) ordered.push(p);
      for (const k of keys) if (!ordered.includes(k)) ordered.push(k);
      return ordered;
    }

    const keys = Object.keys(
      propertiesPreview || propertySpecs || effectiveReviewSchema || {},
    );
    // Prefer a Notion-ish order
    const preferred = [
      "Name",
      "Title",
      "Status",
      "Priority",
      "Owner",
      "Deadline",
      "Due Date",
      "Project",
      "Goal",
      "Description",
    ];
    const ordered: string[] = [];
    for (const p of preferred) if (keys.includes(p)) ordered.push(p);
    for (const k of keys) if (!ordered.includes(k)) ordered.push(k);
    return ordered;
  }, [propertiesPreview, propertySpecs, effectiveReviewSchema, notionRows]);

  const tableValidationSummary = useMemo(() => {
    if (!notionRows || notionRows.length === 0) return null;
    const v =
      notion && typeof notion === "object" ? (notion as any).validation : null;
    const sum = v?.summary;
    if (!sum || typeof sum !== "object") return null;
    const errors =
      typeof (sum as any).errors === "number" ? (sum as any).errors : 0;
    const warnings =
      typeof (sum as any).warnings === "number" ? (sum as any).warnings : 0;
    if (!errors && !warnings) return null;
    return {
      errors,
      warnings,
      mode: typeof v?.mode === "string" ? v.mode : "warn",
    };
  }, [notion, notionRows]);

  function schemaHintForField(fieldKey: string): string {
    const fs: any = (effectiveReviewSchema as any)?.[fieldKey];
    if (!fs || typeof fs !== "object") return "";
    const t = typeof fs.type === "string" ? fs.type : "";
    if (!t) return "";
    const opts = Array.isArray(fs.options)
      ? fs.options.filter((x: any) => typeof x === "string")
      : [];
    if ((t === "select" || t === "status") && opts.length)
      return `${t} (${opts.length} options)`;
    return t;
  }

  function renderNotionValue(v: any): string {
    if (!v || typeof v !== "object") return "";

    if (Array.isArray(v.title)) {
      const parts = v.title
        .map((t: any) => t?.plain_text || t?.text?.content || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join("");
    }

    if (Array.isArray(v.rich_text)) {
      const parts = v.rich_text
        .map((t: any) => t?.plain_text || t?.text?.content || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join("");
    }

    if (Array.isArray(v.people)) {
      const parts = v.people
        .map((p: any) => p?.name || p?.email || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join(", ");
    }

    if (Array.isArray(v.multi_select)) {
      const parts = v.multi_select
        .map((o: any) => o?.name || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join(", ");
    }

    if (Array.isArray(v.people)) {
      const parts = v.people
        .map((p: any) => p?.name || p?.email || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join(", ");
    }

    if (Array.isArray(v.multi_select)) {
      const parts = v.multi_select
        .map((o: any) => o?.name || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join(", ");
    }

    if (v.select && typeof v.select === "object") {
      const n = v.select.name;
      return typeof n === "string" ? n : "";
    }

    if (v.status && typeof v.status === "object") {
      const n = v.status.name;
      return typeof n === "string" ? n : "";
    }

    if (v.date && typeof v.date === "object") {
      const s = v.date.start;
      return typeof s === "string" ? s : "";
    }

    if (Array.isArray(v.relation)) {
      return `${v.relation.length} relation(s)`;
    }

    // fallback
    return clampJson(v, 2000);
  }

  function renderSpecValue(spec: any): string {
    if (!spec || typeof spec !== "object") return "";
    const t =
      typeof (spec as any).type === "string" ? String((spec as any).type) : "";
    if (t === "title" || t === "rich_text")
      return typeof (spec as any).text === "string"
        ? String((spec as any).text)
        : "";
    if (t === "select" || t === "status")
      return typeof (spec as any).name === "string"
        ? String((spec as any).name)
        : "";
    if (t === "date")
      return typeof (spec as any).start === "string"
        ? String((spec as any).start)
        : "";
    if (t === "number")
      return typeof (spec as any).number === "number"
        ? String((spec as any).number)
        : "";
    if (t === "checkbox")
      return typeof (spec as any).checkbox === "boolean"
        ? (spec as any).checkbox
          ? "true"
          : "false"
        : "";
    if (t === "multi_select") {
      const names = Array.isArray((spec as any).names)
        ? (spec as any).names.filter(
            (x: any) => typeof x === "string" && x.trim(),
          )
        : [];
      return names.join(", ");
    }
    if (t === "people") {
      const names = Array.isArray((spec as any).names)
        ? (spec as any).names.filter(
            (x: any) => typeof x === "string" && x.trim(),
          )
        : [];
      return names.join(", ");
    }
    if (t === "relation") return "(relation)";
    return "";
  }

  const nlSummary = useMemo(() => {
    const cmd0 = command && typeof command === "object" ? command : null;
    const cmdName =
      typeof (cmd0 as any)?.command === "string" ? (cmd0 as any).command : "";
    if (cmdName !== "notion_write") return null;

    if (isBatchPreview && notionRows) {
      return {
        title: `Batch request (${notionRows.length} operations)` as string,
        lines: ["Review each row below before approval."] as string[],
      };
    }

    const dk =
      typeof (notion as any)?.db_key === "string"
        ? String((notion as any).db_key)
        : "";
    const intent0 =
      typeof (cmd0 as any)?.intent === "string"
        ? String((cmd0 as any).intent)
        : "";
    const humanIntent = intent0 ? intent0.replace(/_/g, " ") : "";
    const head =
      humanIntent && dk
        ? `${humanIntent} → ${dk}`
        : humanIntent || dk || "Notion write";

    const pp = propertiesPreview;
    const ps = propertySpecs;
    const read = (k: string): string => {
      const v1 =
        pp && typeof pp === "object" ? renderNotionValue((pp as any)?.[k]) : "";
      if (v1) return v1;
      const v2 =
        ps && typeof ps === "object" ? renderSpecValue((ps as any)?.[k]) : "";
      return v2;
    };

    const lines: string[] = [];
    const name = read("Name") || read("Title");
    const status = read("Status");
    const priority = read("Priority");
    const due = read("Due Date") || read("Deadline");
    const assigned = read("Assigned To") || read("Owner") || read("Handled By");
    const agent = read("AI Agent");

    if (name) lines.push(`Name: ${name}`);
    if (status) lines.push(`Status: ${status}`);
    if (priority) lines.push(`Priority: ${priority}`);
    if (due) lines.push(`Due: ${due}`);
    if (assigned) lines.push(`Assigned: ${assigned}`);
    if (agent) lines.push(`AI Agent: ${agent}`);

    return {
      title: head,
      lines: lines.length ? lines : ["No readable fields detected."],
    };
  }, [
    command,
    notion,
    isBatchPreview,
    notionRows,
    propertiesPreview,
    propertySpecs,
  ]);

  function _inferDbKeyForCreatePage(): string {
    const dk0 =
      typeof (notion as any)?.db_key === "string"
        ? String((notion as any).db_key)
        : "";
    if (dk0 && dk0.trim()) return dk0.trim();
    const cmd0 = command && typeof command === "object" ? command : null;
    const dk1 =
      typeof (cmd0 as any)?.params?.db_key === "string"
        ? String((cmd0 as any).params.db_key)
        : "";
    return dk1 && dk1.trim() ? dk1.trim() : "";
  }

  function _defaultDbKeyForKind(kind: string): string {
    if (kind === "create_goal") return "goals";
    if (kind === "create_task") return "tasks";
    if (kind === "create_project") return "projects";
    return _inferDbKeyForCreatePage();
  }

  function _statusTypeForDbKey(dbKey: string): "select" | "status" {
    const k = (dbKey || "").trim().toLowerCase();
    if (k === "tasks" || k === "task") return "select";
    return "status";
  }

  function buildBaseOperationFromCurrent(): any | null {
    const cmd0 = command && typeof command === "object" ? command : null;
    if (!cmd0) return null;
    const cmdName =
      typeof (cmd0 as any).command === "string" ? (cmd0 as any).command : "";
    const intent0 =
      typeof (cmd0 as any).intent === "string" ? (cmd0 as any).intent : "";
    if (cmdName !== "notion_write") return null;
    const allowed = new Set([
      "create_page",
      "create_goal",
      "create_task",
      "create_project",
    ]);
    if (!allowed.has(intent0)) return null;

    const params0 =
      (cmd0 as any)?.params && typeof (cmd0 as any).params === "object"
        ? (cmd0 as any).params
        : {};

    // Prefer the previewed specs (post schema-backed patch) when present.
    const previewSpecs =
      notion &&
      typeof notion === "object" &&
      (notion as any).property_specs &&
      typeof (notion as any).property_specs === "object"
        ? (notion as any).property_specs
        : null;

    if (intent0 === "create_page") {
      const dk = _inferDbKeyForCreatePage();
      const ps0 =
        previewSpecs ||
        ((params0 as any)?.property_specs &&
        typeof (params0 as any).property_specs === "object"
          ? (params0 as any).property_specs
          : null);
      if (!dk || !ps0) return null;
      return {
        op_id: "op_1",
        intent: "create_page",
        payload: {
          db_key: dk,
          property_specs: ps0,
        },
      };
    }

    // create_goal/create_task/create_project
    const dbKey =
      intent0 === "create_goal"
        ? "goals"
        : intent0 === "create_task"
          ? "tasks"
          : "projects";
    const payload: any = {
      title:
        typeof (params0 as any)?.title === "string"
          ? String((params0 as any).title)
          : "",
      description:
        typeof (params0 as any)?.description === "string"
          ? String((params0 as any).description)
          : "",
      deadline:
        typeof (params0 as any)?.deadline === "string"
          ? String((params0 as any).deadline)
          : "",
      priority:
        typeof (params0 as any)?.priority === "string"
          ? String((params0 as any).priority)
          : "",
      status:
        typeof (params0 as any)?.status === "string"
          ? String((params0 as any).status)
          : "",
    };

    // carry common relation hints if present
    for (const k of [
      "goal_id",
      "project_id",
      "parent_goal_id",
      "primary_goal_id",
    ]) {
      const v = (params0 as any)?.[k];
      if (typeof v === "string" && v.trim()) payload[k] = v.trim();
    }

    if (previewSpecs && typeof previewSpecs === "object") {
      payload.property_specs = previewSpecs;
    } else if (
      (params0 as any)?.property_specs &&
      typeof (params0 as any).property_specs === "object"
    ) {
      payload.property_specs = (params0 as any).property_specs;
    }

    return {
      op_id: "op_1",
      intent: intent0,
      payload,
    };
  }

  function buildNewOperation(opIndex: number): any | null {
    const opId = `op_${opIndex}`;
    const title = newItemTitle.trim();
    if (!title) return null;

    const schema = effectiveReviewSchema || {};
    const dueField = schema["Due Date"]
      ? "Due Date"
      : schema["Deadline"]
        ? "Deadline"
        : "Deadline";

    const desc = newItemDescription.trim();
    const st = newItemStatus.trim();
    const pr = newItemPriority.trim();
    const due = newItemDueDate.trim();

    if (newItemKind === "create_page") {
      const dk = (newItemDbKey || _inferDbKeyForCreatePage()).trim();
      if (!dk) return null;
      const titleField = schema["Name"]
        ? "Name"
        : schema["Title"]
          ? "Title"
          : "Name";
      const statusType = _statusTypeForDbKey(dk);

      const ps: any = {};
      ps[titleField] = { type: "title", text: title };
      if (desc) ps["Description"] = { type: "rich_text", text: desc };
      if (st) ps["Status"] = { type: statusType, name: st };
      if (pr) ps["Priority"] = { type: "select", name: pr };
      if (due) ps[dueField] = { type: "date", start: due };

      return {
        op_id: opId,
        intent: "create_page",
        payload: {
          db_key: dk,
          property_specs: ps,
        },
      };
    }

    const dbKey = _defaultDbKeyForKind(newItemKind);
    const statusType = _statusTypeForDbKey(dbKey);

    const payload: any = {
      title,
    };
    if (desc) payload.description = desc;
    if (due) payload.deadline = due;
    if (pr) payload.priority = pr;
    if (st) payload.status = st;

    // Build property_specs as an override so preview/validation matches the target DB.
    const ps: any = {
      Name: { type: "title", text: title },
    };
    if (desc) ps.Description = { type: "rich_text", text: desc };
    if (due) ps.Deadline = { type: "date", start: due };
    if (pr) ps.Priority = { type: "select", name: pr };
    if (st) ps.Status = { type: statusType, name: st };
    payload.property_specs = ps;

    // Relations via $op_id refs.
    if (newItemKind === "create_task") {
      if (newItemGoalOpId.trim())
        payload.goal_id = `$${newItemGoalOpId.trim()}`;
      if (newItemProjectOpId.trim())
        payload.project_id = `$${newItemProjectOpId.trim()}`;
    }
    if (newItemKind === "create_project") {
      if (newItemGoalOpId.trim())
        payload.primary_goal_id = `$${newItemGoalOpId.trim()}`;
    }
    if (newItemKind === "create_goal") {
      if (newItemParentGoalOpId.trim())
        payload.parent_goal_id = `$${newItemParentGoalOpId.trim()}`;
    }

    return {
      op_id: opId,
      intent: newItemKind,
      payload,
    };
  }

  const rawBlocks = useMemo(() => {
    const out: Array<{ label: string; payload: any }> = [];
    out.push({
      label: "Command (resolved / unwrapped)",
      payload: command ?? data?.command ?? data,
    });
    if (notion && typeof notion === "object") {
      out.push({
        label: "Notion property_specs",
        payload: notion.property_specs,
      });
      out.push({
        label: "Notion properties_preview",
        payload: notion.properties_preview,
      });
    }
    return out;
  }, [data, notion, command]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={header}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        style={{
          width: "min(860px, 96vw)",
          maxHeight: "92vh",
          borderRadius: 18,
          border: "1px solid rgba(255,255,255,0.10)",
          background: "rgba(15, 23, 32, 0.98)",
          backdropFilter: "blur(14px)",
          boxShadow: "0 18px 60px rgba(0,0,0,0.55)",
          overflow: "hidden",
          color: "rgba(255,255,255,0.92)",
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji"',
        }}
      >
        <div
          style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.08)",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div style={{ fontWeight: 700, fontSize: 14 }}>{header}</div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button
              onClick={() => setShowRaw((v) => !v)}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                cursor: "pointer",
              }}
              title="Toggle raw JSON view"
              disabled={loading}
            >
              {showRaw ? "Hide JSON" : "Show JSON"}
            </button>
            <button
              onClick={() => {
                try {
                  void navigator.clipboard.writeText(clampJson(data));
                } catch {
                  // ignore
                }
              }}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                cursor: "pointer",
              }}
              title="Copy full preview JSON"
              disabled={loading}
            >
              Copy JSON
            </button>
            <button
              onClick={onClose}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>
        </div>

        <div
          style={{
            padding: 16,
            overflow: "auto",
            maxHeight: "calc(92vh - 58px)",
          }}
        >
          {loading ? (
            <div style={{ opacity: 0.85 }}>Loading preview…</div>
          ) : error ? (
            <div style={{ color: "#ffb3b3" }}>{error}</div>
          ) : (
            <>
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
                  Notion table preview
                </div>

                {nlSummary ? (
                  <div
                    style={{
                      marginBottom: 12,
                      borderRadius: 14,
                      border: "1px solid rgba(255,255,255,0.10)",
                      background: "rgba(255,255,255,0.03)",
                      padding: 12,
                    }}
                  >
                    <div style={{ fontWeight: 700, fontSize: 13 }}>
                      {nlSummary.title}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        opacity: 0.82,
                        marginTop: 6,
                        display: "flex",
                        flexDirection: "column",
                        gap: 4,
                      }}
                    >
                      {nlSummary.lines.map((s: string, idx: number) => (
                        <div key={idx}>{s}</div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {tableValidationSummary ? (
                  <div
                    style={{
                      marginBottom: 12,
                      borderRadius: 14,
                      border: "1px solid rgba(255,255,255,0.10)",
                      background: "rgba(255,255,255,0.03)",
                      padding: 12,
                    }}
                  >
                    <div style={{ fontWeight: 700, fontSize: 13 }}>
                      Validation
                    </div>
                    <div style={{ fontSize: 12, opacity: 0.8 }}>
                      mode: {tableValidationSummary?.mode} • errors:{" "}
                      {tableValidationSummary?.errors} • warnings:{" "}
                      {tableValidationSummary?.warnings}
                    </div>
                  </div>
                ) : null}

                {!notionRows &&
                validationSummary &&
                (validationSummary.errors || validationSummary.warnings) ? (
                  <div
                    style={{
                      marginBottom: 12,
                      borderRadius: 14,
                      border: "1px solid rgba(255,255,255,0.10)",
                      background: "rgba(255,255,255,0.03)",
                      padding: 12,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 13 }}>
                          Validation
                        </div>
                        <div style={{ fontSize: 12, opacity: 0.8 }}>
                          mode: {validationMode} • errors:{" "}
                          {validationSummary.errors || 0} • warnings:{" "}
                          {validationSummary.warnings || 0}
                        </div>
                      </div>
                    </div>

                    {validationIssues.length > 0 ? (
                      <div
                        style={{
                          marginTop: 10,
                          display: "flex",
                          flexDirection: "column",
                          gap: 6,
                        }}
                      >
                        {validationIssues
                          .slice(0, 8)
                          .map((it: any, idx: number) => {
                            const sev =
                              typeof it?.severity === "string"
                                ? it.severity
                                : "warning";
                            const code =
                              typeof it?.code === "string" ? it.code : "issue";
                            const field =
                              typeof it?.field === "string" ? it.field : "";
                            const msg =
                              typeof it?.message === "string" ? it.message : "";
                            const allowed = Array.isArray(it?.allowed)
                              ? (it.allowed as any[]).filter(
                                  (x) => typeof x === "string",
                                )
                              : [];
                            const color =
                              sev === "error"
                                ? "rgba(248,113,113,0.95)"
                                : "rgba(251,191,36,0.95)";
                            return (
                              <div
                                key={idx}
                                style={{
                                  borderRadius: 12,
                                  border: `1px solid ${sev === "error" ? "rgba(248,113,113,0.25)" : "rgba(251,191,36,0.22)"}`,
                                  background: "rgba(0,0,0,0.10)",
                                  padding: "8px 10px",
                                  fontSize: 12,
                                  color: "rgba(255,255,255,0.88)",
                                }}
                              >
                                <span
                                  style={{
                                    color,
                                    fontWeight: 700,
                                    marginRight: 8,
                                  }}
                                >
                                  {sev.toUpperCase()}
                                </span>
                                <span style={{ opacity: 0.85 }}>{code}</span>
                                {field ? (
                                  <span style={{ opacity: 0.85 }}>
                                    {" "}
                                    • {field}
                                  </span>
                                ) : null}
                                {msg ? (
                                  <div style={{ opacity: 0.9, marginTop: 4 }}>
                                    {msg}
                                  </div>
                                ) : null}
                                {allowed.length ? (
                                  <div style={{ opacity: 0.75, marginTop: 6 }}>
                                    Allowed: {allowed.slice(0, 12).join(", ")}
                                    {allowed.length > 12 ? "…" : ""}
                                  </div>
                                ) : null}
                              </div>
                            );
                          })}
                        {validationIssues.length > 8 ? (
                          <div style={{ fontSize: 12, opacity: 0.7 }}>
                            +{validationIssues.length - 8} more… (open JSON to
                            inspect)
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {columns.length === 0 ? (
                  <div style={{ opacity: 0.85 }}>
                    No Notion properties detected in preview. Click "Show JSON"
                    to verify the response contains a `notion` block.
                  </div>
                ) : (
                  <div
                    style={{
                      borderRadius: 14,
                      border: "1px solid rgba(255,255,255,0.08)",
                      background: "rgba(255,255,255,0.04)",
                      overflow: "auto",
                    }}
                  >
                    <table
                      style={{
                        width: "100%",
                        borderCollapse: "separate",
                        borderSpacing: 0,
                        minWidth: 760,
                        fontSize: 12,
                      }}
                    >
                      <thead>
                        <tr>
                          {columns.map((c) => (
                            <th
                              key={c}
                              style={{
                                textAlign: "left",
                                padding: "10px 12px",
                                position: "sticky",
                                top: 0,
                                background: "rgba(15, 23, 32, 0.98)",
                                borderBottom:
                                  "1px solid rgba(255,255,255,0.10)",
                                fontWeight: 700,
                                color: "rgba(255,255,255,0.88)",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {notionRows && notionRows.length > 0 ? (
                          notionRows.map((r, ridx) => (
                            <tr key={r?.op_id || ridx}>
                              {columns.map((c) => {
                                const isMeta =
                                  c === "op_id" ||
                                  c === "intent" ||
                                  c === "db_key";
                                const pp0 =
                                  r?.properties_preview &&
                                  typeof r.properties_preview === "object"
                                    ? (r.properties_preview as any)
                                    : null;
                                const ps0 =
                                  r?.property_specs &&
                                  typeof r.property_specs === "object"
                                    ? (r.property_specs as any)
                                    : null;
                                const pp =
                                  pp0 && Object.keys(pp0).length ? pp0 : null;
                                const ps =
                                  ps0 && Object.keys(ps0).length ? ps0 : null;

                                const v = pp ? pp?.[c] : null;
                                const display = isMeta
                                  ? String(r?.[c] ?? "")
                                  : pp
                                    ? renderNotionValue(v)
                                    : ps
                                      ? renderSpecValue(ps?.[c] ?? null) ||
                                        schemaHintForField(c)
                                      : schemaHintForField(c);

                                return (
                                  <td
                                    key={`${ridx}_${c}`}
                                    style={{
                                      padding: "10px 12px",
                                      borderBottom:
                                        "1px solid rgba(255,255,255,0.06)",
                                      color: "rgba(255,255,255,0.90)",
                                      verticalAlign: "top",
                                      maxWidth: 320,
                                      whiteSpace: "pre-wrap",
                                      wordBreak: "break-word",
                                    }}
                                  >
                                    {display || "—"}
                                  </td>
                                );
                              })}
                            </tr>
                          ))
                        ) : (
                          <tr>
                            {columns.map((c) => {
                              const v = (propertiesPreview || ({} as any))?.[c];
                              const display = propertiesPreview
                                ? renderNotionValue(v)
                                : propertySpecs
                                  ? renderSpecValue(
                                      propertySpecs?.[c] ?? null,
                                    ) || schemaHintForField(c)
                                  : currentValueForField(c) ||
                                    schemaHintForField(c);
                              return (
                                <td
                                  key={c}
                                  style={{
                                    padding: "10px 12px",
                                    borderBottom:
                                      "1px solid rgba(255,255,255,0.06)",
                                    color: "rgba(255,255,255,0.90)",
                                    verticalAlign: "top",
                                    maxWidth: 320,
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-word",
                                  }}
                                >
                                  {display || "—"}
                                </td>
                              );
                            })}
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {!isBatchPreview && onApplyPatch ? (
                <div
                  style={{
                    marginBottom: 14,
                    borderRadius: 14,
                    border: "1px solid rgba(255,255,255,0.08)",
                    background: "rgba(255,255,255,0.03)",
                    padding: 12,
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: 13 }}>
                    Add another request
                  </div>
                  <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
                    Converts this into a single batch approval (multiple
                    operations).
                  </div>

                  <div style={{ height: 10 }} />

                  <div
                    style={{
                      display: "flex",
                      gap: 8,
                      flexWrap: "wrap",
                      alignItems: "center",
                    }}
                  >
                    <button
                      onClick={() => {
                        const base = buildBaseOperationFromCurrent();
                        if (!base) return;
                        setBatchOps([base]);

                        // Pre-fill defaults for the add form.
                        const k =
                          typeof base?.intent === "string"
                            ? String(base.intent)
                            : "create_task";
                        if (k === "create_page") {
                          setNewItemKind("create_page");
                          const dk =
                            typeof base?.payload?.db_key === "string"
                              ? String(base.payload.db_key)
                              : "";
                          setNewItemDbKey(dk);
                        } else if (
                          k === "create_goal" ||
                          k === "create_task" ||
                          k === "create_project"
                        ) {
                          setNewItemKind("create_task");
                          setNewItemDbKey(_defaultDbKeyForKind("create_task"));
                        }
                      }}
                      style={{
                        padding: "8px 10px",
                        borderRadius: 10,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: "rgba(255,255,255,0.06)",
                        color: "rgba(255,255,255,0.92)",
                        cursor: "pointer",
                      }}
                      title="Start a batch with the current request"
                      disabled={loading || Boolean(batchOps)}
                    >
                      Start batch
                    </button>

                    {batchOps ? (
                      <div style={{ fontSize: 12, opacity: 0.8 }}>
                        Operations: {batchOps.length}
                      </div>
                    ) : (
                      <div style={{ fontSize: 12, opacity: 0.7 }}>
                        Supports mixed Goal/Task/Project/Page in one approval.
                      </div>
                    )}
                  </div>

                  {batchOps ? (
                    <>
                      <div style={{ height: 12 }} />

                      <div
                        style={{
                          display: "flex",
                          gap: 10,
                          flexWrap: "wrap",
                          alignItems: "center",
                          marginBottom: 10,
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                            minWidth: 220,
                          }}
                        >
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(255,255,255,0.78)",
                            }}
                          >
                            Type
                          </div>
                          <select
                            value={newItemKind}
                            onChange={(e) => {
                              const v = e.target.value as any;
                              if (
                                v !== "create_goal" &&
                                v !== "create_task" &&
                                v !== "create_project" &&
                                v !== "create_page"
                              )
                                return;
                              setNewItemKind(v);
                              setNewItemDbKey(_defaultDbKeyForKind(v));
                              setNewItemGoalOpId("");
                              setNewItemProjectOpId("");
                              setNewItemParentGoalOpId("");
                            }}
                            style={{
                              border: "1px solid rgba(255,255,255,0.12)",
                              background: "rgba(255,255,255,0.02)",
                              color: "rgba(255,255,255,0.92)",
                              borderRadius: 12,
                              padding: "10px 10px",
                              fontSize: 13,
                              outline: "none",
                            }}
                          >
                            <option
                              value="create_goal"
                              style={{ color: "#000" }}
                            >
                              Goal
                            </option>
                            <option
                              value="create_task"
                              style={{ color: "#000" }}
                            >
                              Task
                            </option>
                            <option
                              value="create_project"
                              style={{ color: "#000" }}
                            >
                              Project
                            </option>
                            <option
                              value="create_page"
                              style={{ color: "#000" }}
                            >
                              Page (db_key)
                            </option>
                          </select>
                        </div>

                        {newItemKind === "create_page" ? (
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: 6,
                              minWidth: 220,
                            }}
                          >
                            <div
                              style={{
                                fontSize: 12,
                                color: "rgba(255,255,255,0.78)",
                              }}
                            >
                              DB key
                            </div>
                            <input
                              value={newItemDbKey}
                              onChange={(e) => setNewItemDbKey(e.target.value)}
                              style={{
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "rgba(255,255,255,0.02)",
                                color: "rgba(255,255,255,0.92)",
                                borderRadius: 12,
                                padding: "10px 10px",
                                fontSize: 13,
                                outline: "none",
                              }}
                              placeholder="tasks / goals / projects"
                            />
                          </div>
                        ) : null}
                      </div>

                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr",
                          gap: 10,
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                          }}
                        >
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(255,255,255,0.78)",
                            }}
                          >
                            Name
                          </div>
                          <input
                            value={newItemTitle}
                            onChange={(e) => setNewItemTitle(e.target.value)}
                            style={{
                              border: "1px solid rgba(255,255,255,0.12)",
                              background: "rgba(255,255,255,0.02)",
                              color: "rgba(255,255,255,0.92)",
                              borderRadius: 12,
                              padding: "10px 10px",
                              fontSize: 13,
                              outline: "none",
                            }}
                            placeholder="New item title"
                          />
                        </div>

                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                          }}
                        >
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(255,255,255,0.78)",
                            }}
                          >
                            Due date (YYYY-MM-DD)
                          </div>
                          <input
                            value={newItemDueDate}
                            onChange={(e) => setNewItemDueDate(e.target.value)}
                            style={{
                              border: "1px solid rgba(255,255,255,0.12)",
                              background: "rgba(255,255,255,0.02)",
                              color: "rgba(255,255,255,0.92)",
                              borderRadius: 12,
                              padding: "10px 10px",
                              fontSize: 13,
                              outline: "none",
                            }}
                            placeholder="2026-01-31"
                          />
                        </div>

                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                          }}
                        >
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(255,255,255,0.78)",
                            }}
                          >
                            Status
                          </div>
                          {fieldOptions("Status").length ? (
                            <select
                              value={newItemStatus}
                              onChange={(e) => setNewItemStatus(e.target.value)}
                              style={{
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "rgba(255,255,255,0.02)",
                                color: "rgba(255,255,255,0.92)",
                                borderRadius: 12,
                                padding: "10px 10px",
                                fontSize: 13,
                                outline: "none",
                              }}
                            >
                              <option value="" style={{ color: "#000" }}>
                                (optional)
                              </option>
                              {fieldOptions("Status").map((o) => (
                                <option
                                  key={o}
                                  value={o}
                                  style={{ color: "#000" }}
                                >
                                  {o}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              value={newItemStatus}
                              onChange={(e) => setNewItemStatus(e.target.value)}
                              style={{
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "rgba(255,255,255,0.02)",
                                color: "rgba(255,255,255,0.92)",
                                borderRadius: 12,
                                padding: "10px 10px",
                                fontSize: 13,
                                outline: "none",
                              }}
                              placeholder="Active"
                            />
                          )}
                        </div>

                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                          }}
                        >
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(255,255,255,0.78)",
                            }}
                          >
                            Priority
                          </div>
                          {fieldOptions("Priority").length ? (
                            <select
                              value={newItemPriority}
                              onChange={(e) =>
                                setNewItemPriority(e.target.value)
                              }
                              style={{
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "rgba(255,255,255,0.02)",
                                color: "rgba(255,255,255,0.92)",
                                borderRadius: 12,
                                padding: "10px 10px",
                                fontSize: 13,
                                outline: "none",
                              }}
                            >
                              <option value="" style={{ color: "#000" }}>
                                (optional)
                              </option>
                              {fieldOptions("Priority").map((o) => (
                                <option
                                  key={o}
                                  value={o}
                                  style={{ color: "#000" }}
                                >
                                  {o}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              value={newItemPriority}
                              onChange={(e) =>
                                setNewItemPriority(e.target.value)
                              }
                              style={{
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "rgba(255,255,255,0.02)",
                                color: "rgba(255,255,255,0.92)",
                                borderRadius: 12,
                                padding: "10px 10px",
                                fontSize: 13,
                                outline: "none",
                              }}
                              placeholder="High"
                            />
                          )}
                        </div>

                        {newItemKind !== "create_page" ? (
                          <>
                            {newItemKind === "create_goal" ? (
                              <div
                                style={{
                                  display: "flex",
                                  flexDirection: "column",
                                  gap: 6,
                                }}
                              >
                                <div
                                  style={{
                                    fontSize: 12,
                                    color: "rgba(255,255,255,0.78)",
                                  }}
                                >
                                  Parent goal (optional)
                                </div>
                                <select
                                  value={newItemParentGoalOpId}
                                  onChange={(e) =>
                                    setNewItemParentGoalOpId(e.target.value)
                                  }
                                  style={{
                                    border: "1px solid rgba(255,255,255,0.12)",
                                    background: "rgba(255,255,255,0.02)",
                                    color: "rgba(255,255,255,0.92)",
                                    borderRadius: 12,
                                    padding: "10px 10px",
                                    fontSize: 13,
                                    outline: "none",
                                  }}
                                >
                                  <option value="" style={{ color: "#000" }}>
                                    (none)
                                  </option>
                                  {(batchOps || [])
                                    .filter(
                                      (op: any) =>
                                        String(op?.intent || "") ===
                                        "create_goal",
                                    )
                                    .map((op: any) => String(op?.op_id || ""))
                                    .filter((x: string) => x)
                                    .map((id: string) => (
                                      <option
                                        key={id}
                                        value={id}
                                        style={{ color: "#000" }}
                                      >
                                        {id}
                                      </option>
                                    ))}
                                </select>
                              </div>
                            ) : null}

                            {newItemKind === "create_project" ? (
                              <div
                                style={{
                                  display: "flex",
                                  flexDirection: "column",
                                  gap: 6,
                                }}
                              >
                                <div
                                  style={{
                                    fontSize: 12,
                                    color: "rgba(255,255,255,0.78)",
                                  }}
                                >
                                  Primary goal (optional)
                                </div>
                                <select
                                  value={newItemGoalOpId}
                                  onChange={(e) =>
                                    setNewItemGoalOpId(e.target.value)
                                  }
                                  style={{
                                    border: "1px solid rgba(255,255,255,0.12)",
                                    background: "rgba(255,255,255,0.02)",
                                    color: "rgba(255,255,255,0.92)",
                                    borderRadius: 12,
                                    padding: "10px 10px",
                                    fontSize: 13,
                                    outline: "none",
                                  }}
                                >
                                  <option value="" style={{ color: "#000" }}>
                                    (none)
                                  </option>
                                  {(batchOps || [])
                                    .filter(
                                      (op: any) =>
                                        String(op?.intent || "") ===
                                        "create_goal",
                                    )
                                    .map((op: any) => String(op?.op_id || ""))
                                    .filter((x: string) => x)
                                    .map((id: string) => (
                                      <option
                                        key={id}
                                        value={id}
                                        style={{ color: "#000" }}
                                      >
                                        {id}
                                      </option>
                                    ))}
                                </select>
                              </div>
                            ) : null}

                            {newItemKind === "create_task" ? (
                              <>
                                <div
                                  style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 6,
                                  }}
                                >
                                  <div
                                    style={{
                                      fontSize: 12,
                                      color: "rgba(255,255,255,0.78)",
                                    }}
                                  >
                                    Link to goal (optional)
                                  </div>
                                  <select
                                    value={newItemGoalOpId}
                                    onChange={(e) =>
                                      setNewItemGoalOpId(e.target.value)
                                    }
                                    style={{
                                      border:
                                        "1px solid rgba(255,255,255,0.12)",
                                      background: "rgba(255,255,255,0.02)",
                                      color: "rgba(255,255,255,0.92)",
                                      borderRadius: 12,
                                      padding: "10px 10px",
                                      fontSize: 13,
                                      outline: "none",
                                    }}
                                  >
                                    <option value="" style={{ color: "#000" }}>
                                      (none)
                                    </option>
                                    {(batchOps || [])
                                      .filter(
                                        (op: any) =>
                                          String(op?.intent || "") ===
                                          "create_goal",
                                      )
                                      .map((op: any) => String(op?.op_id || ""))
                                      .filter((x: string) => x)
                                      .map((id: string) => (
                                        <option
                                          key={id}
                                          value={id}
                                          style={{ color: "#000" }}
                                        >
                                          {id}
                                        </option>
                                      ))}
                                  </select>
                                </div>

                                <div
                                  style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 6,
                                  }}
                                >
                                  <div
                                    style={{
                                      fontSize: 12,
                                      color: "rgba(255,255,255,0.78)",
                                    }}
                                  >
                                    Link to project (optional)
                                  </div>
                                  <select
                                    value={newItemProjectOpId}
                                    onChange={(e) =>
                                      setNewItemProjectOpId(e.target.value)
                                    }
                                    style={{
                                      border:
                                        "1px solid rgba(255,255,255,0.12)",
                                      background: "rgba(255,255,255,0.02)",
                                      color: "rgba(255,255,255,0.92)",
                                      borderRadius: 12,
                                      padding: "10px 10px",
                                      fontSize: 13,
                                      outline: "none",
                                    }}
                                  >
                                    <option value="" style={{ color: "#000" }}>
                                      (none)
                                    </option>
                                    {(batchOps || [])
                                      .filter(
                                        (op: any) =>
                                          String(op?.intent || "") ===
                                          "create_project",
                                      )
                                      .map((op: any) => String(op?.op_id || ""))
                                      .filter((x: string) => x)
                                      .map((id: string) => (
                                        <option
                                          key={id}
                                          value={id}
                                          style={{ color: "#000" }}
                                        >
                                          {id}
                                        </option>
                                      ))}
                                  </select>
                                </div>
                              </>
                            ) : null}
                          </>
                        ) : null}

                        <div
                          style={{
                            gridColumn: "1 / -1",
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                          }}
                        >
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(255,255,255,0.78)",
                            }}
                          >
                            Description
                          </div>
                          <input
                            value={newItemDescription}
                            onChange={(e) =>
                              setNewItemDescription(e.target.value)
                            }
                            style={{
                              border: "1px solid rgba(255,255,255,0.12)",
                              background: "rgba(255,255,255,0.02)",
                              color: "rgba(255,255,255,0.92)",
                              borderRadius: 12,
                              padding: "10px 10px",
                              fontSize: 13,
                              outline: "none",
                            }}
                            placeholder="Optional"
                          />
                        </div>
                      </div>

                      <div style={{ height: 12 }} />
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          justifyContent: "flex-end",
                          flexWrap: "wrap",
                        }}
                      >
                        <button
                          onClick={() => {
                            const next = buildNewOperation(
                              (batchOps?.length || 1) + 1,
                            );
                            if (!next) return;
                            setBatchOps((prev) =>
                              prev ? [...prev, next] : [next],
                            );
                            setNewItemGoalOpId("");
                            setNewItemProjectOpId("");
                            setNewItemParentGoalOpId("");
                            setNewItemTitle("");
                            setNewItemDescription("");
                            setNewItemStatus("");
                            setNewItemPriority("");
                            setNewItemDueDate("");
                          }}
                          style={{
                            padding: "8px 10px",
                            borderRadius: 10,
                            border: "1px solid rgba(255,255,255,0.12)",
                            background: "rgba(255,255,255,0.06)",
                            color: "rgba(255,255,255,0.92)",
                            cursor: "pointer",
                          }}
                          title="Add operation to batch"
                          disabled={loading}
                        >
                          Add item
                        </button>

                        <button
                          onClick={() => {
                            if (!batchOps || batchOps.length < 2) return;
                            onApplyPatch({
                              intent_hint: "batch_request",
                              type: "batch_request",
                              operations: batchOps,
                            });
                          }}
                          style={{
                            padding: "8px 10px",
                            borderRadius: 10,
                            border: "1px solid rgba(255,255,255,0.12)",
                            background: "rgba(59,130,246,0.20)",
                            color: "rgba(255,255,255,0.92)",
                            cursor: "pointer",
                          }}
                          title="Update preview as a batch_request"
                          disabled={loading || !batchOps || batchOps.length < 2}
                        >
                          Preview batch
                        </button>
                      </div>
                    </>
                  ) : null}
                </div>
              ) : null}

              {reviewSchema && editableFields.length > 0 ? (
                <div
                  style={{
                    marginBottom: 14,
                    borderRadius: 14,
                    border: "1px solid rgba(255,255,255,0.08)",
                    background: "rgba(255,255,255,0.03)",
                    padding: 12,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      justifyContent: "space-between",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 13 }}>
                        Complete fields
                      </div>
                      <div style={{ fontSize: 12, opacity: 0.75 }}>
                        These values will be applied to the proposal before
                        approval.
                      </div>
                    </div>
                    <button
                      onClick={() => setShowAllFields((p) => !p)}
                      style={{
                        padding: "8px 10px",
                        borderRadius: 10,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: "rgba(255,255,255,0.06)",
                        color: "rgba(255,255,255,0.92)",
                        cursor: "pointer",
                      }}
                      title="Show more fields"
                      disabled={loading}
                    >
                      {showAllFields ? "Hide extra" : "Show all"}
                    </button>
                  </div>

                  <div style={{ height: 10 }} />

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: 10,
                    }}
                  >
                    {editableFields.map((fieldKey) => {
                      const opts = fieldOptions(fieldKey);
                      const val = currentValueForField(fieldKey);
                      const missing = reviewMissing.includes(fieldKey);

                      return (
                        <div
                          key={fieldKey}
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                          }}
                        >
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(255,255,255,0.78)",
                            }}
                          >
                            {fieldKey}{" "}
                            {missing ? (
                              <span style={{ opacity: 0.7 }}>*</span>
                            ) : null}
                          </div>
                          {opts.length > 0 ? (
                            <select
                              value={val}
                              onChange={(e) =>
                                setPatchLocal((p) => ({
                                  ...p,
                                  [fieldKey]: e.target.value,
                                }))
                              }
                              style={{
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "rgba(255,255,255,0.02)",
                                color: "rgba(255,255,255,0.92)",
                                borderRadius: 12,
                                padding: "10px 10px",
                                fontSize: 13,
                                outline: "none",
                              }}
                            >
                              <option value="" disabled>
                                Select...
                              </option>
                              {opts.map((o) => (
                                <option
                                  key={o}
                                  value={o}
                                  style={{ color: "#000" }}
                                >
                                  {o}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              value={val}
                              onChange={(e) =>
                                setPatchLocal((p) => ({
                                  ...p,
                                  [fieldKey]: e.target.value,
                                }))
                              }
                              style={{
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "rgba(255,255,255,0.02)",
                                color: "rgba(255,255,255,0.92)",
                                borderRadius: 12,
                                padding: "10px 10px",
                                fontSize: 13,
                                outline: "none",
                              }}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>

                  <div style={{ height: 12 }} />
                  <div
                    style={{
                      display: "flex",
                      gap: 8,
                      justifyContent: "flex-end",
                    }}
                  >
                    <button
                      onClick={() => {
                        const schema = effectiveReviewSchema || {};
                        const out: Record<string, any> = {};
                        for (const [k, v0] of Object.entries(
                          patchLocal || {},
                        )) {
                          if (typeof k !== "string" || !k.trim()) continue;
                          const fs: any = (schema as any)?.[k];
                          const t = typeof fs?.type === "string" ? fs.type : "";
                          if (!t || !editableTypes.has(t)) continue;
                          const v = typeof v0 === "string" ? v0.trim() : "";
                          if (!v) continue;
                          out[k] = v;
                        }
                        if (Object.keys(out).length === 0) return;
                        if (!onApplyPatch) return;
                        onApplyPatch(out);
                      }}
                      style={{
                        padding: "8px 10px",
                        borderRadius: 10,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: "rgba(59,130,246,0.20)",
                        color: "rgba(255,255,255,0.92)",
                        cursor: "pointer",
                      }}
                      title="Apply these values to proposal and refresh preview"
                      disabled={loading || !onApplyPatch}
                    >
                      Update preview
                    </button>
                  </div>
                </div>
              ) : null}

              {showRaw
                ? rawBlocks.map((b, i) => (
                    <div key={i} style={{ marginBottom: 14 }}>
                      <div
                        style={{
                          fontWeight: 700,
                          fontSize: 13,
                          marginBottom: 6,
                        }}
                      >
                        {b.label}
                      </div>
                      <pre
                        style={{
                          margin: 0,
                          padding: 12,
                          borderRadius: 14,
                          border: "1px solid rgba(255,255,255,0.08)",
                          background: "rgba(255,255,255,0.04)",
                          overflow: "auto",
                          fontSize: 12,
                          lineHeight: 1.35,
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          color: "rgba(255,255,255,0.90)",
                        }}
                      >
                        {clampJson(b.payload)}
                      </pre>
                    </div>
                  ))
                : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
