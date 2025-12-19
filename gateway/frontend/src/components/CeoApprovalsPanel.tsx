import React from "react";

export type CeoApprovalSummary = {
    pending: number;
    approved_today: number;
    total_completed: number;
    errors: number;
};

type MetricCardProps = {
    label: string;
    value: number;
};

// prvo definišemo MetricCard, da ga TS ne prijavljuje kao "use before declaration"
const MetricCard: React.FC<MetricCardProps> = ({ label, value }) => (
    <div className="metric-card">
        <div className="metric-label">{label}</div>
        <div className="metric-value">{value}</div>
    </div>
);

export interface CeoApprovalsPanelProps {
    approvals: CeoApprovalSummary | null;
}

export const CeoApprovalsPanel: React.FC<CeoApprovalsPanelProps> = ({
    approvals,
}) => {
    const a: CeoApprovalSummary = approvals ?? {
        pending: 0,
        approved_today: 0,
        total_completed: 0,
        errors: 0,
    };

    return (
        <div className="approvals-grid">
            <MetricCard label="Pending" value={a.pending} />
            <MetricCard label="Odobreno danas" value={a.approved_today} />
            <MetricCard label="Ukupno izvršeno" value={a.total_completed} />
            <MetricCard label="Greške" value={a.errors} />
        </div>
    );
};

export default CeoApprovalsPanel;
