import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: { default:"VeriDeploy AI", template:"%s · VeriDeploy AI" }, description:"Evidence-driven release assurance and incident intelligence", applicationName:"VeriDeploy AI" };
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="en"><body>{children}</body></html>; }
