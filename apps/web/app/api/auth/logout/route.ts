import { NextRequest, NextResponse } from "next/server";
export async function POST(req:NextRequest){const r=NextResponse.redirect(new URL("/sign-in",req.url),303);r.cookies.delete("verideploy_session");return r;}
