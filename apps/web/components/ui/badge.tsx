import * as React from "react";
export function Badge({ children, tone="neutral" }: { children: React.ReactNode; tone?: "neutral"|"success"|"warning"|"danger" }) { return <span className={`ui-badge ui-badge--${tone}`}>{children}</span>; }
