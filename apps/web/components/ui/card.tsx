import * as React from "react";
function cx(...values: Array<string | undefined | false>) { return values.filter(Boolean).join(" "); }
export function Card({ className, ...props }: React.HTMLAttributes<HTMLElement>) { return <section className={cx("ui-card",className)} {...props}/>; }
export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) { return <div className={cx("ui-card__header",className)} {...props}/>; }
export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) { return <div className={cx("ui-card__content",className)} {...props}/>; }
