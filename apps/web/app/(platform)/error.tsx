"use client";
import { Button } from "../../components/ui/button";
export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) { return <div className="page"><section className="ui-state" role="alert"><h2>Workspace request failed</h2><p>{error.message}</p><Button onClick={reset}>Try again</Button></section></div>; }
