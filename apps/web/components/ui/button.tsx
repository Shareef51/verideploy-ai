import * as React from "react";
function cx(...values: Array<string | undefined | false>) { return values.filter(Boolean).join(" "); }
export function Button({ className, variant="default", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default"|"outline"|"danger"|"ghost" }) {
  return <button className={cx("ui-button", `ui-button--${variant}`, className)} {...props} />;
}
